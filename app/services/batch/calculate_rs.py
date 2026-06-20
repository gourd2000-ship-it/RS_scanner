import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.core.config import get_settings
from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_market_rs
from app.services.rs.corporate_action_filter import detect_corporate_action
from app.services.rs.policy import MARKET_BENCHMARKS

logger = logging.getLogger(__name__)


def calculate_rs(context: BatchContext, target_date: date | None = None) -> dict:
    effective_target_date = target_date or date.today()

    settings = get_settings()
    winsorize_lower = Decimal(str(settings.rs_winsorize_lower_pct))
    winsorize_upper = Decimal(str(settings.rs_winsorize_upper_pct))
    ca_threshold = Decimal(str(settings.corporate_action_threshold))

    grouped_codes: dict[str, list[str]] = defaultdict(list)
    for symbol in context.symbol_repository.list_stocks_only():
        grouped_codes[symbol.market].append(symbol.code)

    results = {}
    for market, codes in grouped_codes.items():
        benchmark_prices = context.price_repository.get_benchmark_prices(MARKET_BENCHMARKS[market])

        series = []
        skipped_ca = 0
        for code in codes:
            prices = context.price_repository.get_symbol_prices(code)
            if detect_corporate_action(prices, threshold=ca_threshold):
                skipped_ca += 1
                continue
            series.append(SymbolSeries(code=code, market=market, prices=prices))

        if skipped_ca:
            logger.info("market=%s: %d종목 기업이벤트(액면분할/감자 등)으로 제외", market, skipped_ca)

        market_rows = calculate_market_rs(
            market, series, benchmark_prices,
            target_date=effective_target_date,
            winsorize_lower_pct=winsorize_lower,
            winsorize_upper_pct=winsorize_upper,
        )
        results[market] = context.rs_repository.save_many(market, market_rows)
    return results
