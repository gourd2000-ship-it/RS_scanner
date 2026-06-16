from collections import defaultdict
from datetime import date

from app.services.batch.context import BatchContext
from app.services.rs.calculator import SymbolSeries, calculate_market_rs
from app.services.rs.policy import MARKET_BENCHMARKS


def calculate_rs(context: BatchContext, target_date: date | None = None) -> dict:
    # 지정 없으면 오늘 날짜 사용 — 모든 종목이 동일한 trade_date를 갖도록 함
    effective_target_date = target_date or date.today()

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
        market_rows = calculate_market_rs(market, series, benchmark_prices, target_date=effective_target_date)
        results[market] = context.rs_repository.save_many(market, market_rows)
    return results
