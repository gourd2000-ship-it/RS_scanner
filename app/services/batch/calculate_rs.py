import logging
import re
from collections import defaultdict
from time import perf_counter
from datetime import date
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ProviderConflictError
from app.core.metrics import increment_metric, record_provider_request
from app.crawler.sources.base import provider_id
from app.models.symbol import Symbol
from app.repositories.data_quality_repository import DataQualityRepository
from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_combined_rs
from app.services.rs.corporate_action_filter import detect_corporate_action
from app.services.validation.clean_layer import hash_price_rows
from app.services.validation.market_data import validate_prices

logger = logging.getLogger(__name__)


def _latest_date(prices) -> date | None:
    if not prices:
        return None
    return max(row.trade_date for row in prices)


def _provider_conflict_dates(existing, incoming) -> list[date]:
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


def _source_url(source, code: str) -> str | None:
    builder = getattr(source, "build_daily_price_url", None)
    if not callable(builder):
        return None
    try:
        return str(builder(code, None))
    except TypeError:
        try:
            return str(builder(code))
        except Exception:
            return None
    except Exception:
        return None


def _safe_refetch_message(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    message = re.sub(
        r"(?i)(authorization|token|password|api[_-]?key)=\S+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(r"https?://\S+", "<url>", message)
    return message[:1000]


def _record_refetch_result(
    context: BatchContext,
    *,
    code: str,
    source,
    status: str,
    rows_received: int = 0,
    rows_persisted: int = 0,
    latest_date_before: date | None = None,
    latest_date_after: date | None = None,
    error: Exception | None = None,
    retry_count: int = 0,
) -> None:
    repository = getattr(context, "crawl_target_result_repository", None)
    job_id = getattr(context, "job_id", None)
    if repository is None or job_id is None:
        return

    values = {
        "job_id": job_id,
        "step_name": "corporate_action",
        "target_type": "corporate_action",
        "target_key": code,
        "status": status,
        "provider": provider_id(source),
        "rows_received": rows_received,
        "rows_persisted": rows_persisted,
        "latest_date_before": latest_date_before,
        "latest_date_after": latest_date_after,
        "trade_date": latest_date_after,
        "url": _source_url(source, code),
        "http_status": getattr(error, "http_status", None) if error else None,
        "response_bytes": getattr(error, "response_bytes", None) if error else None,
        "error_class": type(error).__name__ if error else None,
        "error_message": _safe_refetch_message(error) if error else None,
        "retry_count": getattr(error, "retry_count", retry_count) if error else retry_count,
    }
    try:
        if context.session is not None:
            with context.session.begin_nested():
                repository.record_result(**values)
        else:
            repository.record_result(**values)
    except Exception as record_error:  # noqa: BLE001
        logger.error("failed to record corporate-action target result for %s: %s", code, record_error)


def _record_refetch_failure(context: BatchContext, code: str, source, error: Exception) -> None:
    repository = getattr(context, "crawl_failure_repository", None)
    job_id = getattr(context, "job_id", None)
    if repository is None or job_id is None:
        return

    values = {
        "job_id": job_id,
        "target_type": "corporate_action",
        "target_key": code,
        "url": _source_url(source, code) or f"unknown://daily_price/{code}",
        "http_status": getattr(error, "http_status", None),
        "response_bytes": getattr(error, "response_bytes", None),
        "error_class": type(error).__name__,
        "error_message": _safe_refetch_message(error),
        "retry_count": getattr(error, "retry_count", 0),
    }
    try:
        if context.session is not None:
            with context.session.begin_nested():
                repository.record_failure(**values)
        else:
            repository.record_failure(**values)
    except Exception as record_error:  # noqa: BLE001
        logger.error("failed to record corporate-action failure for %s: %s", code, record_error)


def _refetch_adjusted_prices(
    context: BatchContext,
    codes: list[str],
) -> int:
    """기업 액션 종목의 전체 가격 이력을 재수집하고 결과를 기록한다."""
    source = getattr(context, "price_source", None)
    if not codes:
        return 0

    if source is None:
        error = RuntimeError("price source unavailable for corporate-action refetch")
        for code in codes:
            _record_refetch_result(
                context,
                code=code,
                source=source,
                status="failed",
                error=error,
            )
            _record_refetch_failure(context, code, source, error)
        return 0

    refetched = 0
    source_provider = provider_id(source)
    is_kiwoom = "kiwoom" in source_provider.lower()
    if is_kiwoom:
        increment_metric("kiwoom_fallback_targets", len(codes))
    for code in codes:
        existing_prices = context.price_repository.get_symbol_prices(code)
        latest_before = _latest_date(existing_prices)
        fetch_started = perf_counter()
        provider_fetch_recorded = False
        try:
            prices = source.fetch_daily_prices(code, since_date=None)
            if is_kiwoom:
                record_provider_request(
                    source_provider,
                    elapsed_seconds=perf_counter() - fetch_started,
                    success=True,
                    retry_count=int(getattr(prices, "retry_count", 0) or 0),
                )
                provider_fetch_recorded = True
            if prices:
                invalid_rows = int(getattr(prices, "invalid_rows", 0) or 0)
                validate_prices(prices)
                conflict_dates = (
                    _provider_conflict_dates(existing_prices, prices)
                    if getattr(source, "reject_provider_conflicts", False)
                    else []
                )
                if conflict_dates:
                    sample = ", ".join(item.isoformat() for item in conflict_dates[:5])
                    raise ProviderConflictError(
                        f"fallback provider conflicts with persisted prices on {sample}"
                    )
                if context.session is not None:
                    context.price_repository.save_symbol_prices(
                        code,
                        prices,
                        crawl_job_id=context.job_id,
                        provider=provider_id(source),
                    )
                else:
                    context.price_repository.save_symbol_prices(code, prices)
                latest_after = context.price_repository.get_latest_symbol_trade_date(code)
                _record_refetch_result(
                    context,
                    code=code,
                    source=source,
                    status="fetched",
                    rows_received=len(prices) + invalid_rows,
                    rows_persisted=len(prices),
                    latest_date_before=latest_before,
                    latest_date_after=latest_after,
                    retry_count=int(getattr(prices, "retry_count", 0) or 0),
                )
                refetched += 1
                if is_kiwoom:
                    increment_metric("kiwoom_recovered_targets")
            else:
                _record_refetch_result(
                    context,
                    code=code,
                    source=source,
                    status="no_new_data",
                    latest_date_before=latest_before,
                    latest_date_after=latest_before,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("수정주가 재수집 실패 %s: %s", code, exc)
            if is_kiwoom and not provider_fetch_recorded:
                record_provider_request(
                    source_provider,
                    elapsed_seconds=perf_counter() - fetch_started,
                    success=False,
                    retry_count=getattr(exc, "retry_count", 0),
                )
            if isinstance(exc, ProviderConflictError):
                increment_metric("kiwoom_conflicts")
            _record_refetch_result(
                context,
                code=code,
                source=source,
                status="failed",
                latest_date_before=latest_before,
                latest_date_after=latest_before,
                error=exc,
            )
            _record_refetch_failure(context, code, source, exc)
    return refetched



def calculate_rs(context: BatchContext, target_date: date | None = None) -> dict:
    effective_target_date = target_date or context.target_date or date.today()

    settings = get_settings()
    ca_threshold = Decimal(str(settings.corporate_action_threshold))
    input_repository = (
        context.rs_input_repository
        if settings.validation_use_rs_input_layer and context.rs_input_repository is not None
        else context.price_repository
    )

    rs_run = None
    lineage_repository = None
    if context.session is not None:
        lineage_repository = DataQualityRepository(context.session)
        rs_run = lineage_repository.create_rs_run(
            validation_run_id=context.validation_run_id,
            trade_date=effective_target_date,
            input_policy_version=settings.rs_input_policy_version,
            mode=settings.validation_mode,
        )
        context.rs_run_id = rs_run.id

    series_by_market: dict[str, list[SymbolSeries]] = defaultdict(list)
    input_prices_by_code: dict[str, list] = {}
    skipped_ca = 0
    ca_codes: list[str] = []

    for symbol in context.symbol_repository.list_stocks_only():
        prices = input_repository.get_symbol_prices(symbol.code)
        input_prices_by_code[symbol.code] = prices
        if detect_corporate_action(prices, threshold=ca_threshold):
            skipped_ca += 1
            ca_codes.append(symbol.code)
            continue
        series_by_market[symbol.market].append(
            SymbolSeries(code=symbol.code, market=symbol.market, prices=prices)
        )

    if skipped_ca:
        logger.info("%d종목 기업이벤트(액면분할/감자 등)으로 제외", skipped_ca)

    if ca_codes:
        refetched = _refetch_adjusted_prices(context, ca_codes)
        if refetched:
            logger.info("%d/%d종목 수정주가 재수집 완료, RS 재계산에 포함", refetched, len(ca_codes))
            for code in ca_codes:
                prices = input_repository.get_symbol_prices(code)
                input_prices_by_code[code] = prices
                if not detect_corporate_action(prices, threshold=ca_threshold):
                    symbol = context.symbol_repository.get_by_code(code)
                    if symbol:
                        series_by_market[symbol.market].append(
                            SymbolSeries(code=code, market=symbol.market, prices=prices)
                        )
                else:
                    error = RuntimeError("corporate action remains after adjusted-price refetch")
                    _record_refetch_result(
                        context,
                        code=code,
                        source=getattr(context, "price_source", None),
                        status="failed",
                        latest_date_before=_latest_date(prices),
                        latest_date_after=_latest_date(prices),
                        error=error,
                    )
                    _record_refetch_failure(
                        context,
                        code,
                        getattr(context, "price_source", None),
                        error,
                    )

    if rs_run is not None and lineage_repository is not None:
        symbol_ids = {
            row.code: row.id
            for row in context.session.scalars(
                select(Symbol).where(Symbol.code.in_(input_prices_by_code))
            ).all()
        }
        snapshot_hashes: list[str] = []
        for code, prices in sorted(input_prices_by_code.items()):
            input_date = max(
                (row.trade_date for row in prices if row.trade_date <= effective_target_date),
                default=None,
            )
            lag = (
                (effective_target_date - input_date).days
                if input_date is not None
                else None
            )
            input_status = (
                "fresh"
                if input_date == effective_target_date
                else "stale"
                if input_date is not None
                else "missing"
            )
            row_hash = hash_price_rows(prices)
            snapshot_hashes.append(f"{code}:{row_hash}:{input_status}")
            if code in symbol_ids:
                lineage_repository.add_rs_input_snapshot(
                    rs_run_id=rs_run.id,
                    symbol_id=symbol_ids[code],
                    target_date=effective_target_date,
                    input_trade_date=input_date,
                    stale_lag_days=lag,
                    input_status=input_status,
                    price_row_count=len(prices),
                    price_hash=row_hash,
                )

        snapshot_hash = sha256(
            "|".join(snapshot_hashes).encode("utf-8")
        ).hexdigest()
    else:
        snapshot_hash = None

    all_rows = calculate_combined_rs(
        series_by_market,
        target_date=effective_target_date,
    )

    rows_by_market: dict[str, list] = defaultdict(list)
    for row in all_rows:
        rows_by_market[row.market].append(row)

    results = {}
    for market, rows in rows_by_market.items():
        # ``calculate_combined_rs`` computes the cross-market percentile/rating,
        # while the persisted/API field is explicitly a market-local rank.
        # Re-number it after splitting the combined result by market.
        for market_rank, row in enumerate(rows, start=1):
            row.rank_in_market = market_rank
        if context.session is not None:
            results[market] = context.rs_repository.save_many(
                market,
                rows,
                rs_run_id=rs_run.id if rs_run is not None else None,
            )
        else:
            results[market] = context.rs_repository.save_many(market, rows)

    if rs_run is not None and lineage_repository is not None:
        lineage_repository.finish_rs_run(
            rs_run,
            status="completed",
            symbol_count=sum(len(rows) for rows in results.values()),
            snapshot_hash=snapshot_hash,
        )
    return results
