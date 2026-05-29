from app.crawler.sources.base import PriceSource
from app.services.batch.context import BatchContext
from app.services.validation.market_data import validate_prices


def sync_prices(context: BatchContext, source: PriceSource):
    synced = {}
    for symbol in context.symbol_repository.list_all():
        latest_trade_date = context.price_repository.get_latest_symbol_trade_date(symbol.code)
        prices = source.fetch_daily_prices(symbol.code, since_date=latest_trade_date)
        if prices:
            validate_prices(prices)
            synced[symbol.code] = context.price_repository.save_symbol_prices(symbol.code, prices)
        else:
            synced[symbol.code] = context.price_repository.get_symbol_prices(symbol.code)
    return synced
