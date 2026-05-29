from collections import defaultdict

from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_market_rs
from app.services.rs.policy import MARKET_BENCHMARKS


def calculate_rs(context: BatchContext):
    grouped_codes: dict[str, list[str]] = defaultdict(list)
    for symbol in context.symbol_repository.list_all():
        grouped_codes[symbol.market].append(symbol.code)

    results = {}
    for market, codes in grouped_codes.items():
        benchmark_prices = context.price_repository.get_benchmark_prices(MARKET_BENCHMARKS[market])
        series = [
            SymbolSeries(code=code, market=market, prices=context.price_repository.get_symbol_prices(code))
            for code in codes
        ]
        market_rows = calculate_market_rs(market, series, benchmark_prices)
        results[market] = context.rs_repository.save_many(market, market_rows)
    return results
