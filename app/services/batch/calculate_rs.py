import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.core.config import get_settings
from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_combined_rs
from app.services.rs.corporate_action_filter import detect_corporate_action

logger = logging.getLogger(__name__)


def _refetch_adjusted_prices(
    context: BatchContext,
    codes: list[str],
) -> int:
    """기업 액션이 감지된 종목의 전체 가격 이력을 수정주가로 재수집.

    증분 수집 시 과거 수정주가가 갱신되지 않는 문제를 해결한다.
    source가 없으면 재수집을 건너뛴다.
    """
    source = getattr(context, "price_source", None)
    if source is None or not codes:
        return 0

    refetched = 0
    for code in codes:
        try:
            prices = source.fetch_daily_prices(code, since_date=None)
            if prices:
                context.price_repository.save_symbol_prices(code, prices)
                refetched += 1
        except Exception as e:
            logger.warning("수정주가 재수집 실패 %s: %s", code, e)
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

    all_rows = calculate_combined_rs(
        series_by_market,
        target_date=effective_target_date,
    )

    rows_by_market: dict[str, list] = defaultdict(list)
    for row in all_rows:
        rows_by_market[row.market].append(row)

    results = {}
    for market, rows in rows_by_market.items():
        results[market] = context.rs_repository.save_many(market, rows)
    return results
