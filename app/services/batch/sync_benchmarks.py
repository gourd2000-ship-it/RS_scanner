from datetime import timedelta

from app.crawler.sources.base import PriceSource, provider_id
from app.services.batch.context import BatchContext
from app.services.rs.policy import MARKET_BENCHMARKS


def sync_benchmarks(context: BatchContext, source: PriceSource):
    context.benchmark_repository.upsert_defaults()
    rows_by_market = {}
    for market in MARKET_BENCHMARKS:
        latest_trade_date = context.price_repository.get_latest_benchmark_trade_date(MARKET_BENCHMARKS[market])
        fetch_since_date = latest_trade_date
        if fetch_since_date is not None and provider_id(source) == "naver":
            fetch_since_date -= timedelta(days=1)
        prices = source.fetch_benchmark_prices(market, since_date=fetch_since_date)
        if context.target_date is not None:
            prices = [row for row in prices if row.trade_date <= context.target_date]
        if prices:
            if context.session is not None:
                rows_by_market[market] = context.price_repository.save_benchmark_prices(
                    MARKET_BENCHMARKS[market],
                    prices,
                    crawl_job_id=context.job_id,
                    provider=provider_id(source),
                )
            else:
                rows_by_market[market] = context.price_repository.save_benchmark_prices(
                    MARKET_BENCHMARKS[market], prices
                )
        else:
            rows_by_market[market] = context.price_repository.get_benchmark_prices(MARKET_BENCHMARKS[market])
    return rows_by_market
