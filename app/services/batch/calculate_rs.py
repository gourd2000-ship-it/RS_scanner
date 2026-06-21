import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.core.config import get_settings
from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_combined_rs
from app.services.rs.corporate_action_filter import detect_corporate_action

logger = logging.getLogger(__name__)


def calculate_rs(context: BatchContext, target_date: date | None = None) -> dict:
    effective_target_date = target_date or date.today()

    settings = get_settings()
    ca_threshold = Decimal(str(settings.corporate_action_threshold))

    series_by_market: dict[str, list[SymbolSeries]] = defaultdict(list)
    skipped_ca = 0
    for symbol in context.symbol_repository.list_stocks_only():
        prices = context.price_repository.get_symbol_prices(symbol.code)
        if detect_corporate_action(prices, threshold=ca_threshold):
            skipped_ca += 1
            continue
        series_by_market[symbol.market].append(
            SymbolSeries(code=symbol.code, market=symbol.market, prices=prices)
        )

    if skipped_ca:
        logger.info("%d종목 기업이벤트(액면분할/감자 등)으로 제외", skipped_ca)

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
