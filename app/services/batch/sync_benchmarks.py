from app.crawler.sources.base import PriceSource
from app.services.batch.context import BatchContext
from app.services.rs.policy import MARKET_BENCHMARKS


def sync_benchmarks(context: BatchContext, source: PriceSource):
    context.benchmark_repository.upsert_defaults()
    rows_by_market = {}
    for market in MARKET_BENCHMARKS:
        latest_trade_date = context.price_repository.get_latest_benchmark_trade_date(MARKET_BENCHMARKS[market])
        prices = source.fetch_benchmark_prices(market, since_date=latest_trade_date)
        if prices:
            rows_by_market[market] = context.price_repository.save_benchmark_prices(MARKET_BENCHMARKS[market], prices)
        else:
            rows_by_market[market] = context.price_repository.get_benchmark_prices(MARKET_BENCHMARKS[market])
    return rows_by_market
