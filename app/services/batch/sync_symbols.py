from app.crawler.sources.base import PriceSource
from app.services.batch.context import BatchContext


def sync_symbols(context: BatchContext, source: PriceSource):
    symbols = source.fetch_symbols()
    return context.symbol_repository.upsert_many(symbols)
