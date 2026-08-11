"""시장 단위 EOD 수집과 Naver 누락 fallback."""

import logging
from datetime import date
from time import perf_counter
from typing import Any

from app.core.metrics import (
    increment_metric,
    record_batch_duration,
    record_price_sync_metrics,
    record_provider_request,
)
from app.crawler.sources.base import PriceSource
from app.crawler.sources.eod import (
    BulkEodSource,
    EodBatch,
    EodCanaryPolicy,
    validate_eod_batch,
)
from app.services.batch.context import BatchContext
from app.services.batch.sync_prices import (
    PriceSyncResult,
    PriceTargetResult,
    _safe_error_message,
    sync_prices,
)

logger = logging.getLogger(__name__)


def _batch_url(batch: EodBatch | None, market: str, trade_date: date) -> str:
    if batch is not None and batch.request_url:
        return batch.request_url
    provider = batch.provider if batch is not None else "unknown"
    return f"eod://{provider}/{market}/{trade_date.isoformat()}"


def _record_target_result(
    context: BatchContext,
    *,
    job_id: int | None,
    symbol: Any,
    target: PriceTargetResult,
) -> None:
    repository = context.crawl_target_result_repository
    if repository is None or job_id is None:
        return

    values = {
        "job_id": job_id,
        "step_name": "eod",
        "target_type": getattr(symbol, "symbol_type", "stock"),
        "target_key": target.code,
        "status": target.status,
        "provider": target.provider,
        "rows_received": target.rows_received,
        "rows_persisted": target.rows_persisted,
        "latest_date_before": target.latest_date_before,
        "latest_date_after": target.latest_date_after,
        "trade_date": target.trade_date,
        "url": target.url,
        "http_status": target.http_status,
        "response_bytes": target.response_bytes,
        "error_class": target.error_class,
        "error_message": target.error_message,
        "retry_count": target.retry_count,
    }
    try:
        if context.session is not None:
            with context.session.begin_nested():
                repository.record_result(**values)
        else:
            repository.record_result(**values)
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to record EOD target result for %s: %s", target.code, exc)


def _record_failure(
    context: BatchContext,
    *,
    job_id: int | None,
    code: str,
    batch: EodBatch | None,
    market: str,
    trade_date: date,
    error: Exception,
) -> None:
    repository = context.crawl_failure_repository
    if repository is None or job_id is None:
        return

    values = {
        "job_id": job_id,
        "target_type": "eod",
        "target_key": code,
        "url": _batch_url(batch, market, trade_date),
        "http_status": getattr(error, "http_status", None),
        "response_bytes": (
            getattr(error, "response_bytes", None)
            or (batch.response_bytes if batch is not None else None)
        ),
        "error_class": type(error).__name__,
        "error_message": _safe_error_message(error),
        "retry_count": getattr(error, "retry_count", 0),
    }
    try:
        if context.session is not None:
            with context.session.begin_nested():
                repository.record_failure(**values)
        else:
            repository.record_failure(**values)
    except Exception as record_error:  # noqa: BLE001
        increment_metric("crawl_failure_record_error_total")
        logger.error("failed to record EOD failure for %s: %s", code, record_error)


def _failed_target(
    *,
    symbol: Any,
    batch: EodBatch | None,
    market: str,
    trade_date: date,
    error: Exception,
    latest_before: date | None,
    rows_received: int = 0,
) -> PriceTargetResult:
    return PriceTargetResult(
        code=symbol.code,
        status="failed",
        rows_received=rows_received,
        latest_date_before=latest_before,
        latest_date_after=latest_before,
        trade_date=trade_date,
        provider=batch.provider if batch is not None else None,
        error_class=type(error).__name__,
        error_message=_safe_error_message(error),
        url=_batch_url(batch, market, trade_date),
        http_status=getattr(error, "http_status", None),
        response_bytes=(
            getattr(error, "response_bytes", None)
            or (batch.response_bytes if batch is not None else None)
        ),
        retry_count=getattr(error, "retry_count", 0),
    )


def sync_eod_prices(
    context: BatchContext,
    source: BulkEodSource,
    *,
    trade_date: date | None = None,
    fallback_source: PriceSource | None = None,
    canary_policy: EodCanaryPolicy | None = None,
) -> PriceSyncResult:
    """시장별 bulk EOD를 저장하고 누락 종목만 fallback source로 재수집한다.

    공급자 응답이 검증에 실패하면 해당 시장의 행은 전부 저장하지 않는다.
    fallback 결과가 있으면 최종 작업 통계에는 fallback 결과를 반영하고,
    crawl_target_results에는 eod와 prices 단계가 각각 남는다.
    """
    started_at = perf_counter()
    target_date = trade_date or date.today()
    symbols = context.symbol_repository.list_price_targets()
    symbols_by_market: dict[str, list[Any]] = {}
    for symbol in symbols:
        symbols_by_market.setdefault(symbol.market, []).append(symbol)

    result = PriceSyncResult()
    fallback_codes: set[str] = set()

    for market, market_symbols in symbols_by_market.items():
        if canary_policy is not None:
            canary_symbols = [
                symbol
                for symbol in market_symbols
                if canary_policy.allows(market=market, code=symbol.code)
            ]
            excluded_symbols = [
                symbol for symbol in market_symbols if symbol not in canary_symbols
            ]
            for symbol in excluded_symbols:
                latest_before = context.price_repository.get_latest_symbol_trade_date(symbol.code)
                target = PriceTargetResult(
                    code=symbol.code,
                    status="skipped",
                    latest_date_before=latest_before,
                    latest_date_after=latest_before,
                    trade_date=latest_before,
                    provider="eod-canary",
                    error_class="EodCanaryExcluded",
                    error_message="outside EOD provider canary; fallback queued",
                    url=f"eod://canary/{market}/{target_date.isoformat()}",
                )
                result.add_target(target)
                _record_target_result(
                    context,
                    job_id=context.job_id,
                    symbol=symbol,
                    target=target,
                )
                fallback_codes.add(symbol.code)
            market_symbols = canary_symbols
            if not market_symbols:
                continue

        eligible_codes = {symbol.code for symbol in market_symbols}
        batch: EodBatch | None = None
        provider_started = perf_counter()
        provider_ok = False
        try:
            batch = source.fetch_eod_prices(market, target_date)
            validate_eod_batch(
                batch,
                eligible_codes=eligible_codes,
                expected_trade_date=target_date,
                expected_market=market,
            )
            provider_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("EOD batch failed for %s: %s", market, exc)
            for symbol in market_symbols:
                latest_before = context.price_repository.get_latest_symbol_trade_date(symbol.code)
                target = _failed_target(
                    symbol=symbol,
                    batch=batch,
                    market=market,
                    trade_date=target_date,
                    error=exc,
                    latest_before=latest_before,
                    rows_received=len((batch.rows_by_code or {}).get(symbol.code, []))
                    if batch is not None
                    else 0,
                )
                result.add_target(target)
                _record_target_result(
                    context,
                    job_id=context.job_id,
                    symbol=symbol,
                    target=target,
                )
                _record_failure(
                    context,
                    job_id=context.job_id,
                    code=symbol.code,
                    batch=batch,
                    market=market,
                    trade_date=target_date,
                    error=exc,
                )
                if fallback_source is not None:
                    fallback_codes.add(symbol.code)
            continue
        finally:
            record_provider_request(
                type(source).__name__,
                elapsed_seconds=perf_counter() - provider_started,
                success=provider_ok,
                retry_count=getattr(batch, "retry_count", 0) if batch is not None else 0,
            )

        rows_by_code = {
            code: list(rows)
            for code, rows in batch.rows_by_code.items()
        }
        latest_before_by_code = {
            symbol.code: context.price_repository.get_latest_symbol_trade_date(symbol.code)
            for symbol in market_symbols
        }
        missing_codes = eligible_codes - set(rows_by_code)
        fallback_codes.update(missing_codes)

        try:
            save_bulk = getattr(context.price_repository, "save_symbol_prices_bulk", None)
            if callable(save_bulk):
                if context.session is not None:
                    persisted_by_code = save_bulk(
                        rows_by_code,
                        crawl_job_id=job_id,
                        provider=type(source).__name__,
                    )
                else:
                    persisted_by_code = save_bulk(rows_by_code)
            else:
                persisted_by_code = {
                    code: (
                        context.price_repository.save_symbol_prices(
                            code,
                            rows,
                            crawl_job_id=job_id,
                            provider=type(source).__name__,
                        )
                        if context.session is not None
                        else context.price_repository.save_symbol_prices(code, rows)
                    )
                    for code, rows in rows_by_code.items()
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("EOD persistence failed for %s: %s", market, exc)
            for symbol in market_symbols:
                latest_before = context.price_repository.get_latest_symbol_trade_date(symbol.code)
                rows_received = len(rows_by_code.get(symbol.code, []))
                target = _failed_target(
                    symbol=symbol,
                    batch=batch,
                    market=market,
                    trade_date=target_date,
                    error=exc,
                    latest_before=latest_before,
                    rows_received=rows_received,
                )
                result.add_target(target)
                _record_target_result(
                    context,
                    job_id=context.job_id,
                    symbol=symbol,
                    target=target,
                )
                _record_failure(
                    context,
                    job_id=context.job_id,
                    code=symbol.code,
                    batch=batch,
                    market=market,
                    trade_date=target_date,
                    error=exc,
                )
                if fallback_source is not None:
                    fallback_codes.add(symbol.code)
            continue

        for symbol in market_symbols:
            rows = rows_by_code.get(symbol.code)
            latest_before = latest_before_by_code.get(symbol.code)
            if not rows:
                if fallback_source is not None:
                    target = PriceTargetResult(
                        code=symbol.code,
                        status="skipped",
                        provider=batch.provider,
                        error_class="EodMissingTarget",
                        error_message="missing from EOD batch; fallback queued",
                        url=_batch_url(batch, market, target_date),
                        response_bytes=batch.response_bytes,
                        latest_date_before=latest_before,
                        latest_date_after=latest_before,
                        trade_date=target_date,
                    )
                else:
                    error = ValueError("symbol missing from EOD batch")
                    target = _failed_target(
                        symbol=symbol,
                        batch=batch,
                        market=market,
                        trade_date=target_date,
                        error=error,
                        latest_before=latest_before,
                    )
                    _record_failure(
                        context,
                        job_id=context.job_id,
                        code=symbol.code,
                        batch=batch,
                        market=market,
                        trade_date=target_date,
                        error=error,
                    )
                result.add_target(target)
                _record_target_result(
                    context,
                    job_id=context.job_id,
                    symbol=symbol,
                    target=target,
                )
                continue

            persisted = persisted_by_code.get(symbol.code, rows)
            latest_after = context.price_repository.get_latest_symbol_trade_date(symbol.code)
            status = (
                "fetched"
                if latest_before is None or latest_after is None or latest_after > latest_before
                else "no_new_data"
            )
            target = PriceTargetResult(
                code=symbol.code,
                status=status,
                prices=persisted,
                rows_received=len(rows),
                rows_persisted=len(rows),
                latest_date_before=latest_before,
                latest_date_after=latest_after,
                trade_date=target_date,
                provider=batch.provider,
                url=batch.request_url,
                response_bytes=batch.response_bytes,
            )
            result.add_target(target)
            _record_target_result(
                context,
                job_id=context.job_id,
                symbol=symbol,
                target=target,
            )

    if fallback_source is not None and fallback_codes:
        fallback_result = sync_prices(
            context,
            fallback_source,
            target_codes=fallback_codes,
            use_checkpoints=False,
        )
        for target in fallback_result.target_results.values():
            result.add_target(target)

    result.validate_status_invariant()
    record_price_sync_metrics(result)
    record_batch_duration(perf_counter() - started_at)
    return result
