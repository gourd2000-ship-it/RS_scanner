import hashlib
import logging
from collections import Counter
from math import ceil

from app.core.metrics import set_metric
from app.core.config import get_settings
from datetime import datetime

from app.crawler.parsers.symbols import is_etn_name
from app.crawler.sources.base import PriceSource, SymbolUniverseFetchResult, provider_id
from app.services.batch.context import BatchContext

logger = logging.getLogger(__name__)


def _snapshot_hash(symbols: list) -> str | None:
    if not symbols:
        return None
    payload = "|".join(
        f"{symbol.code}:{symbol.name}:{symbol.market}:{symbol.symbol_type}"
        for symbol in sorted(symbols, key=lambda item: item.code)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _complete_snapshot(
    context: BatchContext,
    *,
    status: str,
    pages_total: int,
    pages_succeeded: int,
    symbols_seen: int,
    symbols_valid: int,
    duplicate_count: int = 0,
    invalid_count: int = 0,
    snapshot_hash: str | None = None,
    deactivation_candidates: list[str] | None = None,
    error_message: str | None = None,
) -> None:
    context.universe_snapshot_status = status
    set_metric(
        "symbols_deactivated_total",
        len(deactivation_candidates or []) if status == "completed" else 0,
    )
    repository = context.universe_snapshot_repository
    if repository is None or context.universe_snapshot_id is None:
        return
    try:
        repository.complete_snapshot(
            context.universe_snapshot_id,
            status=status,
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            symbols_seen=symbols_seen,
            symbols_valid=symbols_valid,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            snapshot_hash=snapshot_hash,
            deactivation_candidates=deactivation_candidates or [],
            error_message=error_message,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to finalize universe snapshot: %s", exc)


def _fetch_universe(source: PriceSource):
    fetch_universe = getattr(source, "fetch_symbol_universe", None)
    if not callable(fetch_universe):
        return source.fetch_symbols(), 1, 1, True, None, {}

    result = fetch_universe()
    if isinstance(result, SymbolUniverseFetchResult):
        return (
            result.symbols,
            result.pages_total,
            result.pages_succeeded,
            result.complete,
            result.error_message,
            result.market_results,
        )

    # 외부 source가 아직 구계약(list)만 반환해도 기존 배치를 유지한다.
    return result, 1, 1, True, None, {}


def _validate_universe_completeness(
    symbols: list,
    *,
    pages_total: int,
    pages_succeeded: int,
    fetch_complete: bool,
    market_results: dict,
    active_items: list,
) -> list[str]:
    """부분 페이지·비정상적으로 작은 목록을 completed로 승인하지 않는다."""
    settings = get_settings()
    errors: list[str] = []
    if pages_total < 1:
        errors.append("pages_total_invalid")
    if pages_succeeded < 0 or pages_succeeded > pages_total:
        errors.append("pages_succeeded_invalid")
    if fetch_complete and pages_succeeded != pages_total:
        errors.append("page_completion_mismatch")

    incoming_by_market = Counter(getattr(symbol, "market", None) for symbol in symbols)
    previous_by_market = Counter(getattr(symbol, "market", None) for symbol in active_items)
    absolute_minimum = settings.universe_min_symbols if market_results else 1
    if market_results:
        for market, page_result in market_results.items():
            if page_result.pages_total < 1 or page_result.pages_succeeded > page_result.pages_total:
                errors.append(f"{market}:page_progress_invalid")
            if page_result.complete and page_result.pages_succeeded != page_result.pages_total:
                errors.append(f"{market}:page_completion_mismatch")
            if page_result.complete and page_result.termination_reason not in {
                None,
                "empty_page",
                "repeated_page",
            }:
                errors.append(f"{market}:invalid_termination:{page_result.termination_reason}")

        # A market that had active names before the fetch must still appear in
        # a provider's per-market result.  This catches a silently omitted
        # market even when the aggregate page counters look healthy.
        for market, previous_count in previous_by_market.items():
            if previous_count and market not in market_results:
                errors.append(f"{market}:missing_market_result")

    if not active_items:
        if len(symbols) < absolute_minimum:
            errors.append(
                f"total_below_minimum:{len(symbols)}<{absolute_minimum}"
            )
    else:
        markets = set(previous_by_market) | set(incoming_by_market)
        for market in markets:
            previous_count = previous_by_market.get(market, 0)
            if not previous_count:
                continue
            minimum = max(
                ceil(previous_count * settings.universe_min_symbol_ratio),
                min(absolute_minimum, previous_count),
            )
            incoming_count = incoming_by_market.get(market, 0)
            if incoming_count < minimum:
                errors.append(f"{market}:below_minimum:{incoming_count}<{minimum}")

    return errors


def sync_symbols(context: BatchContext, source: PriceSource):
    """심볼을 동기화하고 완전한 snapshot에서만 누락 종목을 reconcile한다."""
    context.universe_snapshot_status = "running"
    context.universe_snapshot_id = None
    snapshot_repository = context.universe_snapshot_repository
    if snapshot_repository is not None:
        try:
            snapshot = snapshot_repository.create_snapshot(
                job_id=context.job_id,
                provider=provider_id(source),
                market="ALL",
            )
            context.universe_snapshot_id = snapshot.id
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to create universe snapshot: %s", exc)
            snapshot_repository = None

    pages_total = 1
    pages_succeeded = 0
    fetch_complete = False
    fetch_error: str | None = None
    market_results: dict = {}
    try:
        (
            symbols,
            pages_total,
            pages_succeeded,
            fetch_complete,
            fetch_error,
            market_results,
        ) = _fetch_universe(source)
    except Exception as exc:  # noqa: BLE001
        logger.error("universe fetch failed: %s", exc, exc_info=True)
        _complete_snapshot(
            context,
            status="failed",
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            symbols_seen=0,
            symbols_valid=0,
            error_message=fetch_error or type(exc).__name__,
        )
        return context.symbol_repository.list_all()

    etf_codes: set[str] = set()
    etf_lookup_succeeded = True
    if hasattr(source, "fetch_etf_codes"):
        try:
            etf_codes = source.fetch_etf_codes()
        except Exception as exc:  # noqa: BLE001
            etf_lookup_succeeded = False
            logger.warning("ETF universe fetch failed; continuing without ETF typing: %s", exc)

    validate_symbol_code = getattr(source, "is_valid_symbol_code", None)
    seen_codes: set[str] = set()
    typed = []
    duplicate_count = 0
    invalid_count = 0
    for sym in symbols:
        code = getattr(sym, "code", None)
        name = getattr(sym, "name", None)
        market = getattr(sym, "market", None)
        symbol_type = getattr(sym, "symbol_type", "stock")
        if (
            not isinstance(code, str)
            or not code.strip()
            or (callable(validate_symbol_code) and not validate_symbol_code(code))
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(market, str)
            or not market.strip()
            or market not in {"KOSPI", "KOSDAQ"}
            or symbol_type not in {"stock", "etf", "etn"}
        ):
            invalid_count += 1
            continue
        if code in seen_codes:
            duplicate_count += 1
            continue
        seen_codes.add(code)
        if code in etf_codes:
            sym = sym.model_copy(update={"symbol_type": "etf"})
        elif is_etn_name(sym.name):
            sym = sym.model_copy(update={"symbol_type": "etn"})
        elif not etf_lookup_succeeded:
            existing_symbol = context.symbol_repository.get_by_code(code)
            if existing_symbol is not None:
                sym = sym.model_copy(
                    update={"symbol_type": existing_symbol.symbol_type}
                )
        typed.append(sym)

    snapshot_id = context.universe_snapshot_id
    deactivation_candidates: list[str] = []
    try:
        active_items, _ = context.symbol_repository.list_filtered(
            is_active=True,
            page=1,
            size=1_000_000,
        )
        active_codes = {item.code for item in active_items}
        validation_errors = _validate_universe_completeness(
            symbols,
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            fetch_complete=fetch_complete,
            market_results=market_results,
            active_items=active_items,
        )
        snapshot_duplicate_count = duplicate_count + sum(
            getattr(item, "duplicate_count", 0) for item in market_results.values()
        )
        snapshot_status = (
            "completed"
            if typed and invalid_count == 0 and fetch_complete and not validation_errors
            else ("partial" if typed else "failed")
        )
        validation_error = ";".join(validation_errors) if validation_errors else None
        final_error = ";".join(
            value for value in (fetch_error, validation_error) if value
        ) or None
        if snapshot_status == "completed":
            deactivation_candidates = sorted(active_codes - seen_codes)

        if typed:
            if context.session is not None:
                with context.session.begin_nested():
                    updated_symbols = context.symbol_repository.upsert_many(
                        typed,
                        snapshot_id=snapshot_id,
                        seen_at=datetime.utcnow(),
                    )
            else:
                updated_symbols = context.symbol_repository.upsert_many(
                    typed,
                    snapshot_id=snapshot_id,
                    seen_at=datetime.utcnow(),
                )
        else:
            updated_symbols = context.symbol_repository.list_all()
    except Exception as exc:  # noqa: BLE001
        logger.error("universe persistence failed: %s", exc, exc_info=True)
        _complete_snapshot(
            context,
            status="failed",
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            symbols_seen=len(symbols),
            symbols_valid=len(typed),
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            snapshot_hash=_snapshot_hash(typed),
            error_message=fetch_error or ("invalid_symbol_rows" if invalid_count else type(exc).__name__),
        )
        return context.symbol_repository.list_all()

    _complete_snapshot(
        context,
        status=snapshot_status,
        pages_total=pages_total,
        pages_succeeded=pages_succeeded,
        symbols_seen=len(symbols),
        symbols_valid=len(typed),
        duplicate_count=snapshot_duplicate_count,
        invalid_count=invalid_count,
        snapshot_hash=_snapshot_hash(typed),
        deactivation_candidates=deactivation_candidates,
        error_message=final_error or ("invalid_symbol_rows" if invalid_count else None),
    )
    return updated_symbols
