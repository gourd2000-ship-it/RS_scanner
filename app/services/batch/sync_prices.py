"""가격 데이터 동기화 - 청크 기반 처리"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from time import perf_counter
from typing import Any, Literal


from app.core.config import get_settings
from app.core.exceptions import ProviderConflictError
from app.core.metrics import (
    increment_metric,
    record_batch_duration,
    record_price_sync_metrics,
    record_provider_request,
)
from app.core.database import session_scope
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource, provider_id
from app.repositories.memory_price_repository import MemoryPriceRepository
from app.services.batch.context import BatchContext, build_db_batch_context
from app.services.validation.market_data import validate_prices

logger = logging.getLogger(__name__)
settings = get_settings()
notification_service = get_notification_service()

PriceStatus = Literal["fetched", "no_new_data", "partial", "failed", "skipped"]


@dataclass
class PriceTargetResult:
    code: str
    status: PriceStatus
    prices: list[Any] | None = None
    rows_received: int = 0
    rows_persisted: int = 0
    latest_date_before: date | None = None
    latest_date_after: date | None = None
    trade_date: date | None = None
    provider: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    url: str | None = None
    http_status: int | None = None
    response_bytes: int | None = None
    retry_count: int = 0


class PriceSyncResult(dict[str, Any]):
    """가격 단계의 기존 code->rows 결과와 종목별 상태를 함께 보관한다."""

    def __init__(self) -> None:
        super().__init__()
        self.target_results: dict[str, PriceTargetResult] = {}

    def add_target(self, target: PriceTargetResult) -> None:
        self.target_results[target.code] = target
        if target.prices is not None and target.status in {"fetched", "no_new_data", "partial"}:
            self[target.code] = target.prices

    def merge(self, chunk_result: "ChunkPriceResult") -> None:
        for target in chunk_result.target_results.values():
            self.add_target(target)

    @property
    def target_count(self) -> int:
        return len(self.target_results)

    def count(self, status: PriceStatus) -> int:
        return sum(target.status == status for target in self.target_results.values())

    @property
    def fetched_count(self) -> int:
        return self.count("fetched")

    @property
    def no_new_data_count(self) -> int:
        return self.count("no_new_data")

    @property
    def partial_count(self) -> int:
        return self.count("partial")

    @property
    def failed_count(self) -> int:
        return self.count("failed")

    @property
    def skipped_count(self) -> int:
        return self.count("skipped")

    @property
    def succeeded_count(self) -> int:
        """작업 수준의 비실패 종목 수. checkpoint 재개로 건너뛴 성공도 포함한다."""
        return self.fetched_count + self.no_new_data_count + self.skipped_count

    @property
    def attempted_succeeded_count(self) -> int:
        return self.fetched_count + self.no_new_data_count

    @property
    def unsuccessful_count(self) -> int:
        return self.partial_count + self.failed_count

    def validate_status_invariant(self) -> None:
        counted = (
            self.fetched_count
            + self.no_new_data_count
            + self.partial_count
            + self.failed_count
            + self.skipped_count
        )
        if counted != self.target_count:
            raise ValueError(
                f"price target status mismatch: counted={counted}, total={self.target_count}"
            )


class RequestBudget:
    """Thread-safe logical request budget for one price stage."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.used = 0
        self._lock = Lock()

    def reserve(self) -> bool:
        if self.limit is None:
            return True
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


@dataclass
class ChunkPriceResult:
    target_results: dict[str, PriceTargetResult]

    @property
    def synced_prices(self) -> dict[str, list[Any]]:
        return {
            code: target.prices
            for code, target in self.target_results.items()
            if target.prices is not None and target.status in {"fetched", "no_new_data", "partial"}
        }

    @property
    def unsuccessful_count(self) -> int:
        return sum(
            target.status in {"partial", "failed"}
            for target in self.target_results.values()
        )


def chunk_list(items: list, chunk_size: int) -> list[list]:
    """리스트를 청크로 분할"""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _list_price_targets(context: BatchContext) -> list:
    list_price_targets = getattr(context.symbol_repository, "list_price_targets", None)
    if callable(list_price_targets):
        return list_price_targets()
    return context.symbol_repository.list_all()


def sync_prices(
    context: BatchContext,
    source: PriceSource,
    *,
    target_codes: set[str] | None = None,
    target_lineage: dict[str, Any] | None = None,
    use_checkpoints: bool = True,
    max_requests: int | None = None,
    fallback_source: PriceSource | None = None,
    fallback_max_requests: int | None = None,
    record_target_results: bool = True,
) -> PriceSyncResult:
    """가격 데이터 동기화 - 종목별 최종 상태를 보존하는 청크 처리."""
    started_at = perf_counter()
    if target_codes is None and target_lineage is None:
        selection = _resolve_universe_price_selection(context, source)
        if selection is not None:
            target_codes = set(selection.target_codes)
            target_lineage = selection.lineage_by_code
    all_symbols = _list_price_targets(context)
    if target_codes is not None:
        target_code_set = set(target_codes)
        all_symbols = [symbol for symbol in all_symbols if symbol.code in target_code_set]
    total_symbols = len(all_symbols)
    logger.info("sync_prices: %d eligible symbols to process", total_symbols)

    result = PriceSyncResult()
    if not all_symbols:
        logger.warning("no eligible symbols found, skipping price sync")
        record_price_sync_metrics(result)
        record_batch_duration(perf_counter() - started_at)
        return result

    request_budget = RequestBudget(
        settings.naver_max_requests_per_batch if max_requests is None else max_requests
    )

    chunks = chunk_list(all_symbols, settings.batch_chunk_size)
    total_chunks = len(chunks)
    logger.info(
        "sync_prices: %d symbols in %d chunks (size=%d)",
        total_symbols,
        total_chunks,
        settings.batch_chunk_size,
    )

    completed_chunks = _get_completed_chunks(context) if use_checkpoints else set()
    previous_targets = _get_previous_target_results(context) if use_checkpoints else {}
    if completed_chunks:
        logger.info("resuming from checkpoint: %d chunks already completed", len(completed_chunks))

    for chunk_idx, symbol_chunk in enumerate(chunks):
        if chunk_idx in completed_chunks:
            logger.info("skipping already completed chunk %d/%d", chunk_idx, total_chunks - 1)
            for symbol in symbol_chunk:
                previous = previous_targets.get(symbol.code)
                if previous is not None:
                    result.add_target(_target_from_record(previous, symbol.code))
                else:
                    result.add_target(
                        PriceTargetResult(
                            code=symbol.code,
                            status="skipped",
                            provider=provider_id(source),
                            error_class="checkpoint",
                            error_message="target was already completed in a previous attempt",
                        )
                    )
            continue

        logger.info(
            "processing chunk %d/%d: %d symbols",
            chunk_idx,
            total_chunks - 1,
            len(symbol_chunk),
        )
        chunk_result = _process_chunk(
            chunk_idx=chunk_idx,
            total_chunks=total_chunks,
            symbol_chunk=symbol_chunk,
            source=source,
            job_id=context.job_id,
            context=context,
            update_checkpoint=use_checkpoints,
            request_budget=request_budget,
            record_target_results=record_target_results,
            target_lineage=target_lineage,
        )
        result.merge(chunk_result)
        logger.info(
            "chunk %d/%d completed: %d symbols processed, %d unsuccessful",
            chunk_idx,
            total_chunks - 1,
            len(chunk_result.target_results),
            chunk_result.unsuccessful_count,
        )

    if fallback_source is not None:
        fallback_codes = {
            code
            for code, target in result.target_results.items()
            if _fallback_eligible(target)
        }
        if "kiwoom" in provider_id(fallback_source).lower():
            configured_codes = {
                code.strip()
                for code in settings.kiwoom_fallback_codes.split(",")
                if code.strip()
            }
            if configured_codes:
                fallback_codes &= configured_codes
        if fallback_codes:
            logger.info(
                "sync_prices: sending %d failed/partial targets to fallback %s",
                len(fallback_codes),
                provider_id(fallback_source),
            )
            fallback_result = sync_prices(
                context,
                fallback_source,
                target_codes=fallback_codes,
                target_lineage=target_lineage,
                use_checkpoints=False,
                max_requests=fallback_max_requests,
                record_target_results=False,
            )
            _record_fallback_metrics(fallback_codes, fallback_result, fallback_source)
            for target in fallback_result.target_results.values():
                final_target = target
                if target.status == "skipped":
                    # A fallback budget skip must not turn the primary failure
                    # into a successful-looking skipped target.
                    final_target = result.target_results.get(target.code, target)
                result.add_target(final_target)
                symbol = context.symbol_repository.get_by_code(target.code)
                if symbol is not None:
                    _record_target_result_safely(
                        chunk_context=context,
                        job_id=context.job_id,
                        symbol=symbol,
                        target=final_target,
                        lineage=(target_lineage or {}).get(target.code),
                    )

    result.validate_status_invariant()
    record_price_sync_metrics(result)
    record_batch_duration(perf_counter() - started_at)
    logger.info(
        "sync_prices completed: %d targets, fetched=%d, no_new_data=%d, partial=%d, failed=%d, skipped=%d",
        result.target_count,
        result.fetched_count,
        result.no_new_data_count,
        result.partial_count,
        result.failed_count,
        result.skipped_count,
    )
    return result


def _resolve_universe_price_selection(context: BatchContext, source: PriceSource):
    """Build a job-local canary selection, or preserve the legacy path.

    The resolver deliberately requires both snapshots from the same job.  A
    previous completed KRX snapshot must not mask a current partial/failed
    observation when deciding whether the canary may run.
    """
    if context.session is None or context.job_id is None or not isinstance(context.target_date, date):
        return None
    try:
        from sqlalchemy import select

        from app.models.krx_universe import KrxUniverseSnapshot
        from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
        from app.services.canonical_universe import materialize_completed_universe
        from app.services.universe_price_selection import select_price_targets

        naver_snapshot = context.session.scalar(
            select(SymbolUniverseSnapshot)
            .where(SymbolUniverseSnapshot.job_id == context.job_id)
            .order_by(SymbolUniverseSnapshot.id.desc())
            .limit(1)
        )
        krx_snapshot = context.session.scalar(
            select(KrxUniverseSnapshot)
            .where(KrxUniverseSnapshot.crawl_job_id == context.job_id)
            .order_by(KrxUniverseSnapshot.id.desc())
            .limit(1)
        )
        if naver_snapshot is None:
            return None
        if (
            krx_snapshot is not None
            and krx_snapshot.status == "completed"
            and naver_snapshot.status == "completed"
        ):
            materialize_completed_universe(
                context.session,
                krx_snapshot_id=krx_snapshot.id,
                naver_snapshot_id=naver_snapshot.id,
                provider=provider_id(source),
            )
        return select_price_targets(
            context.session,
            provider=provider_id(source),
            as_of_date=context.target_date,
            naver_snapshot_id=naver_snapshot.id,
            krx_snapshot_status=krx_snapshot.status if krx_snapshot is not None else None,
            naver_targets=_list_price_targets(context),
            settings=get_settings(),
        )
    except Exception:  # noqa: BLE001 - canary evidence must not break Naver fallback
        logger.exception("failed to resolve KRX universe canary; using Naver targets")
        return None


def _get_completed_chunks(context: BatchContext) -> set[int]:
    """완료된 청크 인덱스 조회"""
    if not context.job_id or not context.checkpoint_repository:
        return set()
    return context.checkpoint_repository.get_completed_chunks(context.job_id, "prices")


def _get_previous_target_results(context: BatchContext) -> dict[str, Any]:
    repository = context.crawl_target_result_repository
    if repository is None or not context.job_id:
        return {}
    try:
        return {
            record.target_key: record
            for record in repository.list_by_job(context.job_id, step_name="prices")
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to load previous target results: %s", exc)
        return {}


def _target_from_record(record: Any, code: str) -> PriceTargetResult:
    status = record.status if record.status in {"fetched", "no_new_data", "partial", "failed", "skipped"} else "skipped"
    prices = [] if status in {"fetched", "no_new_data", "partial"} else None
    return PriceTargetResult(
        code=code,
        status=status,
        prices=prices,
        rows_received=record.rows_received or 0,
        rows_persisted=record.rows_persisted or 0,
        latest_date_before=record.latest_date_before,
        latest_date_after=record.latest_date_after,
        trade_date=getattr(record, "trade_date", None),
        provider=record.provider,
        error_class=record.error_class,
        error_message=record.error_message,
        url=record.url,
        http_status=record.http_status,
        response_bytes=record.response_bytes,
        retry_count=record.retry_count or 0,
    )


def retry_failed_price_targets(
    context: BatchContext,
    source: PriceSource,
    job_id: int,
    target_keys: set[str] | None = None,
    max_requests: int | None = None,
    max_attempts: int | None = None,
) -> PriceSyncResult:
    """이전 가격 단계에서 failed/partial인 종목만 재수집한다."""
    repository = context.crawl_target_result_repository
    if repository is None:
        logger.warning("failed-target retry requested without target result repository")
        return PriceSyncResult()

    records = repository.list_by_job(
        job_id=job_id,
        step_name="prices",
        statuses=("failed", "partial"),
    )
    if target_keys is not None:
        records = [record for record in records if record.target_key in target_keys]
    if max_attempts is not None:
        records = [
            record
            for record in records
            if (record.attempt_count or 0) < max_attempts
        ]

    symbols = []
    for record in records:
        symbol = context.symbol_repository.get_by_code(record.target_key)
        if symbol is not None:
            symbols.append(symbol)

    result = PriceSyncResult()
    if not symbols:
        return result

    chunk_result = _process_chunk(
        chunk_idx=0,
        total_chunks=1,
        symbol_chunk=symbols,
        source=source,
        job_id=job_id,
        context=context,
        update_checkpoint=False,
        request_budget=RequestBudget(
            settings.naver_max_requests_per_batch if max_requests is None else max_requests
        ),
    )
    result.merge(chunk_result)
    result.validate_status_invariant()
    return result


def _process_chunk(
    chunk_idx: int,
    total_chunks: int,
    symbol_chunk: list,
    source: PriceSource,
    job_id: int | None,
    context: BatchContext,
    update_checkpoint: bool = True,
    request_budget: RequestBudget | None = None,
    record_target_results: bool = True,
    target_lineage: dict[str, Any] | None = None,
) -> ChunkPriceResult:
    """단일 청크를 처리하고 종목별 결과를 반환한다."""
    if isinstance(context.price_repository, MemoryPriceRepository) or context.session is not None:
        chunk_context = context
        chunk_result = _process_chunk_in_context(
            chunk_idx=chunk_idx,
            total_chunks=total_chunks,
            symbol_chunk=symbol_chunk,
            source=source,
            job_id=job_id,
            chunk_context=chunk_context,
            update_checkpoint=update_checkpoint,
            request_budget=request_budget,
            record_target_results=record_target_results,
            target_lineage=target_lineage,
        )
    else:
        with session_scope() as session:
            chunk_context = build_db_batch_context(session)
            chunk_context.job_id = job_id
            chunk_context.price_source = source
            chunk_result = _process_chunk_in_context(
                chunk_idx=chunk_idx,
                total_chunks=total_chunks,
                symbol_chunk=symbol_chunk,
                source=source,
                job_id=job_id,
                chunk_context=chunk_context,
                update_checkpoint=update_checkpoint,
            request_budget=request_budget,
            record_target_results=record_target_results,
            target_lineage=target_lineage,
            )

    _post_commit_validate_chunk(chunk_idx, symbol_chunk, job_id, chunk_context)
    try:
        notification_service.send_chunk_completed_sync(
            step_name="prices",
            chunk_index=chunk_idx,
            total_chunks=total_chunks,
            items_synced=len(chunk_result.synced_prices),
            items_failed=chunk_result.unsuccessful_count,
        )
    except Exception as exc:
        logger.error("failed to send chunk completion notification for chunk %d: %s", chunk_idx, exc)
    return chunk_result


def _process_chunk_in_context(
    chunk_idx: int,
    total_chunks: int,
    symbol_chunk: list,
    source: PriceSource,
    job_id: int | None,
    chunk_context: BatchContext,
    update_checkpoint: bool = True,
    request_budget: RequestBudget | None = None,
    record_target_results: bool = True,
    target_lineage: dict[str, Any] | None = None,
) -> ChunkPriceResult:
    target_results: dict[str, PriceTargetResult] = {}
    source_provider = provider_id(source)

    latest_dates = {
        symbol.code: chunk_context.price_repository.get_latest_symbol_trade_date(symbol.code)
        for symbol in symbol_chunk
    }
    request_urls = {
        symbol.code: _source_url(source, symbol.code, latest_dates.get(symbol.code))
        for symbol in symbol_chunk
    }
    fetched, fetch_errors, budget_skipped, response_meta = _fetch_chunk_prices(
        symbol_chunk=symbol_chunk,
        source=source,
        latest_dates=latest_dates,
        request_budget=request_budget,
    )

    for symbol in symbol_chunk:
        latest_trade_date = latest_dates.get(symbol.code)
        request_url = request_urls.get(symbol.code)
        if symbol.code in budget_skipped:
            target = PriceTargetResult(
                code=symbol.code,
                status="skipped",
                latest_date_before=latest_trade_date,
                latest_date_after=latest_trade_date,
                trade_date=latest_trade_date,
                provider=source_provider,
                error_class="RequestBudgetExceeded",
                error_message="provider request budget exhausted",
                url=request_url,
            )
        else:
            try:
                if symbol.code in fetch_errors:
                    raise fetch_errors[symbol.code]
                prices = fetched.get(symbol.code)
                if prices is None:
                    raise ValueError("price source returned no result")
                invalid_rows = int(getattr(prices, "invalid_rows", 0))
                response_bytes = response_meta.get(symbol.code)

                if prices:
                    validate_prices(prices)
                    conflict_dates = _provider_conflict_dates(
                        chunk_context.price_repository.get_symbol_prices(symbol.code),
                        prices,
                    ) if getattr(source, "reject_provider_conflicts", False) else []
                    if conflict_dates:
                        sample = ", ".join(item.isoformat() for item in conflict_dates[:5])
                        raise ProviderConflictError(
                            f"fallback provider conflicts with persisted prices on {sample}",
                        )
                    if chunk_context.session is not None:
                        with chunk_context.session.begin_nested():
                            saved_prices = chunk_context.price_repository.save_symbol_prices(
                                symbol.code,
                                prices,
                                crawl_job_id=job_id,
                                provider=source_provider,
                            )
                    else:
                        saved_prices = chunk_context.price_repository.save_symbol_prices(
                            symbol.code,
                            prices,
                        )

                    latest_after = _latest_trade_date(saved_prices)
                    target = PriceTargetResult(
                        code=symbol.code,
                        status="partial" if invalid_rows else "fetched",
                        prices=saved_prices,
                        rows_received=len(prices) + invalid_rows,
                        rows_persisted=len(prices),
                        latest_date_before=latest_trade_date,
                        latest_date_after=latest_after,
                        trade_date=latest_after,
                        provider=source_provider,
                        error_class="partial_parse" if invalid_rows else None,
                        error_message=(
                            f"{invalid_rows} invalid rows discarded" if invalid_rows else None
                        ),
                        url=request_url,
                        response_bytes=response_bytes,
                        retry_count=int(getattr(prices, "retry_count", 0) or 0),
                    )
                else:
                    existing_prices = chunk_context.price_repository.get_symbol_prices(symbol.code)
                    latest_after = _latest_trade_date(existing_prices)
                    target = PriceTargetResult(
                        code=symbol.code,
                        status="no_new_data",
                        prices=existing_prices,
                        latest_date_before=latest_trade_date,
                        latest_date_after=latest_after,
                        trade_date=latest_after,
                        provider=source_provider,
                        url=request_url,
                        response_bytes=response_bytes,
                        retry_count=int(getattr(prices, "retry_count", 0) or 0),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to sync prices for %s: %s", symbol.code, exc)
                invalid_rows = int(getattr(exc, "invalid_rows", 0) or 0)
                target = PriceTargetResult(
                    code=symbol.code,
                    status="failed",
                    rows_received=invalid_rows,
                    latest_date_before=latest_trade_date,
                    latest_date_after=latest_trade_date,
                    trade_date=latest_trade_date,
                    provider=source_provider,
                    error_class=type(exc).__name__,
                    error_message=_safe_error_message(exc),
                    url=_failure_url(source, symbol.code, exc),
                    http_status=getattr(exc, "http_status", None),
                    response_bytes=getattr(exc, "response_bytes", None),
                    retry_count=getattr(exc, "retry_count", 0),
                )
                if type(exc).__name__ in {"PriceParseError", "ParseError"}:
                    increment_metric("crawl_parser_error_total")
                if isinstance(exc, ProviderConflictError):
                    increment_metric("kiwoom_conflicts")
                _record_failure_safely(
                    chunk_context=chunk_context,
                    source=source,
                    job_id=job_id,
                    code=symbol.code,
                    error=exc,
                )

        target_results[symbol.code] = target
        target_result_record = None
        if record_target_results:
            target_result_record = _record_target_result_safely(
                chunk_context=chunk_context,
                job_id=job_id,
                symbol=symbol,
                target=target,
                lineage=(target_lineage or {}).get(symbol.code),
            )

    unsuccessful_count = sum(
        target.status in {"partial", "failed"}
        for target in target_results.values()
    )
    successful_count = len(target_results) - unsuccessful_count
    _validate_chunk(
        chunk_idx,
        total_chunks,
        len(symbol_chunk),
        successful_count,
        unsuccessful_count,
    )

    if (
        update_checkpoint
        and chunk_context.checkpoint_repository
        and job_id
        and chunk_context.checkpoint_repository.get_checkpoint(job_id, "prices") is not None
    ):
        chunk_context.checkpoint_repository.update_chunk_progress(
            job_id=job_id,
            step_name="prices",
            chunk_index=chunk_idx,
            total_chunks=total_chunks,
            chunk_size=len(symbol_chunk),
            items_processed_this_chunk=successful_count,
            items_failed_this_chunk=unsuccessful_count,
            chunk_succeeded=unsuccessful_count == 0,
        )

    return ChunkPriceResult(target_results=target_results)


def _fetch_chunk_prices(
    *,
    symbol_chunk: list,
    source: PriceSource,
    latest_dates: dict[str, date | None],
    request_budget: RequestBudget | None,
) -> tuple[dict[str, Any], dict[str, Exception], set[str], dict[str, int | None]]:
    """Fetch one chunk with a bounded worker pool, keeping DB writes serial."""
    fetched: dict[str, Any] = {}
    errors: dict[str, Exception] = {}
    skipped: set[str] = set()
    response_meta: dict[str, int | None] = {}

    def fetch_one(symbol: Any) -> tuple[str, Any | None, Exception | None, int | None, bool]:
        code = symbol.code
        if request_budget is not None and not request_budget.reserve():
            return code, None, None, None, True
        started = perf_counter()
        try:
            source_since_date = (
                None
                if getattr(source, "fetch_full_history_on_fallback", False)
                else latest_dates.get(code)
            )
            rows = source.fetch_daily_prices(code, since_date=source_since_date)
            elapsed = perf_counter() - started
            record_provider_request(
                provider_id(source),
                elapsed_seconds=elapsed,
                success=True,
                retry_count=getattr(rows, "retry_count", 0),
            )
            return code, rows, None, getattr(rows, "response_bytes", None), False
        except Exception as exc:  # noqa: BLE001
            elapsed = perf_counter() - started
            record_provider_request(
                provider_id(source),
                elapsed_seconds=elapsed,
                success=False,
                retry_count=getattr(exc, "retry_count", 0),
            )
            return code, None, exc, getattr(exc, "response_bytes", None), False

    configured_workers = getattr(source, "max_concurrency", None)
    if configured_workers is None:
        configured_workers = settings.naver_max_concurrency
    max_workers = max(1, min(int(configured_workers), len(symbol_chunk)))
    if max_workers == 1:
        outcomes = [fetch_one(symbol) for symbol in symbol_chunk]
    else:
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="price-fetch",
        ) as executor:
            futures = [executor.submit(fetch_one, symbol) for symbol in symbol_chunk]
            outcomes = [future.result() for future in as_completed(futures)]

    for code, rows, error, response_bytes, was_skipped in outcomes:
        if was_skipped:
            skipped.add(code)
        elif error is not None:
            errors[code] = error
        else:
            fetched[code] = rows
        response_meta[code] = response_bytes

    return fetched, errors, skipped, response_meta


def _provider_conflict_dates(existing: list[Any], incoming: list[Any]) -> list[date]:
    """Return overlapping dates whose OHLCV differs between providers."""
    existing_by_date = {row.trade_date: row for row in existing}
    conflicts: list[date] = []
    for row in incoming:
        previous = existing_by_date.get(row.trade_date)
        if previous is None:
            continue
        fields = ("open", "high", "low", "close", "volume")
        if any(getattr(previous, field) != getattr(row, field) for field in fields):
            conflicts.append(row.trade_date)
    return conflicts


def _record_fallback_metrics(
    attempted_codes: set[str],
    fallback_result: PriceSyncResult,
    fallback_source: PriceSource,
) -> None:
    provider_name = provider_id(fallback_source).lower()
    if "kiwoom" not in provider_name:
        return
    increment_metric("kiwoom_fallback_targets", len(attempted_codes))
    increment_metric(
        "kiwoom_recovered_targets",
        fallback_result.fetched_count + fallback_result.no_new_data_count,
    )


def _fallback_eligible(target: PriceTargetResult) -> bool:
    """Limit fallback traffic to provider/data availability failures.

    Validation, persistence, and provider-conflict errors are intentionally
    excluded. Replacing a bad or ambiguous row with another provider would
    hide the original data-quality problem.
    """
    if target.status == "partial":
        return True
    if target.status != "failed":
        return False
    if target.error_class in {"PriceParseError", "ParseError"}:
        return True
    if target.error_class in {"PriceFetchError", "KiwoomApiError"}:
        return target.http_status is None or target.http_status in {408, 425, 429} or (
            target.http_status >= 500
        )
    if target.error_class in {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "TimeoutException",
        "WriteError",
        "WriteTimeout",
    }:
        return True
    return target.http_status in {408, 425, 429} or (
        target.http_status is not None and target.http_status >= 500
    )

def _latest_trade_date(prices: list[Any]) -> date | None:
    if not prices:
        return None
    return max(row.trade_date for row in prices)


def _source_url(source: PriceSource, code: str, since_date: date | None) -> str | None:
    builder = getattr(source, "build_daily_price_url", None)
    if not callable(builder):
        return None
    try:
        return str(builder(code, since_date))
    except TypeError:
        try:
            return str(builder(code))
        except Exception:
            return None
    except Exception:
        return None


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        message = type(error).__name__
    message = re.sub(
        r"(?i)(authorization|token|password|api[_-]?key)=\S+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(r"https?://\S+", "<url>", message)
    return message[:1000]


def _failure_url(source: PriceSource, code: str, error: Exception) -> str:
    error_url = getattr(error, "url", None)
    if error_url:
        return str(error_url)
    return _source_url(source, code, None) or f"unknown://daily_price/{code}"


def _record_failure_safely(
    *,
    chunk_context: BatchContext,
    source: PriceSource,
    job_id: int | None,
    code: str,
    error: Exception,
) -> None:
    repository = chunk_context.crawl_failure_repository
    if repository is None or job_id is None:
        return

    values = {
        "job_id": job_id,
        "target_type": "daily_price",
        "target_key": code,
        "url": _failure_url(source, code, error),
        "http_status": getattr(error, "http_status", None),
        "response_bytes": getattr(error, "response_bytes", None),
        "error_class": type(error).__name__,
        "error_message": _safe_error_message(error),
        "retry_count": getattr(error, "retry_count", 0),
    }
    try:
        if chunk_context.session is not None:
            with chunk_context.session.begin_nested():
                repository.record_failure(**values)
        else:
            repository.record_failure(**values)
    except Exception as record_error:  # noqa: BLE001
        increment_metric("crawl_failure_record_error_total")
        logger.error("failed to record crawl failure for %s: %s", code, record_error)


def _record_target_result_safely(
    *,
    chunk_context: BatchContext,
    job_id: int | None,
    symbol: Any,
    target: PriceTargetResult,
    lineage: Any | None = None,
) -> Any | None:
    repository = chunk_context.crawl_target_result_repository
    if repository is None or job_id is None:
        return None

    values = {
        "job_id": job_id,
        "step_name": "prices",
        "target_type": getattr(symbol, "symbol_type", "stock"),
        "target_key": target.code,
        "krx_snapshot_id": getattr(lineage, "krx_snapshot_id", None),
        "instrument_id": getattr(lineage, "instrument_id", None),
        "price_eligibility": getattr(lineage, "price_eligibility", None),
        "eligibility_reason": getattr(lineage, "reason_code", None),
        "status": target.status,
        "provider": target.provider,
        "rows_received": target.rows_received,
        "rows_persisted": target.rows_persisted,
        "latest_date_before": target.latest_date_before,
        "latest_date_after": target.latest_date_after,
        "trade_date": target.trade_date or target.latest_date_after,
        "url": target.url,
        "http_status": target.http_status,
        "response_bytes": target.response_bytes,
        "error_class": target.error_class,
        "error_message": target.error_message,
        "retry_count": target.retry_count,
    }
    try:
        if chunk_context.session is not None:
            with chunk_context.session.begin_nested():
                return repository.record_result(**values)
        else:
            return repository.record_result(**values)
    except Exception as record_error:  # noqa: BLE001
        logger.error("failed to record crawl target result for %s: %s", target.code, record_error)
    return None


def _validate_chunk(
    chunk_idx: int,
    total_chunks: int,
    chunk_size: int,
    synced_count: int,
    failed_count: int,
) -> None:
    total_processed = synced_count + failed_count
    if total_processed != chunk_size:
        raise ValueError(
            f"chunk {chunk_idx}/{total_chunks - 1} count mismatch: "
            f"processed={total_processed}, expected={chunk_size}"
        )
    logger.debug(
        "chunk %d/%d validation passed: %d synced, %d failed",
        chunk_idx,
        total_chunks - 1,
        synced_count,
        failed_count,
    )


def _post_commit_validate_chunk(
    chunk_idx: int,
    symbol_chunk: list,
    job_id: int | None,
    context: BatchContext,
) -> None:
    """커밋 후 DB 영속성을 확인한다."""
    if isinstance(context.price_repository, MemoryPriceRepository):
        return
    if not job_id or not symbol_chunk:
        return

    sample_symbol_code = symbol_chunk[0].code
    if context.session is not None:
        prices = context.price_repository.get_symbol_prices(sample_symbol_code)
    else:
        with session_scope() as session:
            validation_context = build_db_batch_context(session)
            prices = validation_context.price_repository.get_symbol_prices(sample_symbol_code)

    if not prices:
        logger.warning(
            "post-commit validation: chunk %d sample symbol %s has no prices in DB",
            chunk_idx,
            sample_symbol_code,
        )
    else:
        logger.debug(
            "post-commit validation passed: chunk %d sample symbol %s has %d prices",
            chunk_idx,
            sample_symbol_code,
            len(prices),
        )
