import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.core.config import get_settings
from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_combined_rs
from app.services.rs.corporate_action_filter import detect_corporate_action
from app.services.validation.market_data import validate_prices

logger = logging.getLogger(__name__)


def _latest_date(prices) -> date | None:
    if not prices:
        return None
    return max(row.trade_date for row in prices)


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
        "provider": type(source).__name__,
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
        "retry_count": getattr(error, "retry_count", 0) if error else 0,
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
    for code in codes:
        existing_prices = context.price_repository.get_symbol_prices(code)
        latest_before = _latest_date(existing_prices)
        try:
            prices = source.fetch_daily_prices(code, since_date=None)
            if prices:
                invalid_rows = int(getattr(prices, "invalid_rows", 0) or 0)
                validate_prices(prices)
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
                )
                refetched += 1
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
    effective_target_date = target_date or date.today()

    settings = get_settings()
    ca_threshold = Decimal(str(settings.corporate_action_threshold))

    series_by_market: dict[str, list[SymbolSeries]] = defaultdict(list)
    skipped_ca = 0
    ca_codes: list[str] = []

    for symbol in context.symbol_repository.list_stocks_only():
        prices = context.price_repository.get_symbol_prices(symbol.code)
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
                prices = context.price_repository.get_symbol_prices(code)
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
        results[market] = context.rs_repository.save_many(market, rows)
    return results
