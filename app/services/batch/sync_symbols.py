from app.crawler.parsers.symbols import is_etn_name
from app.crawler.sources.base import PriceSource
from app.services.batch.context import BatchContext


def sync_symbols(context: BatchContext, source: PriceSource):
    symbols = source.fetch_symbols()

    etf_codes: set[str] = set()
    if hasattr(source, "fetch_etf_codes"):
        etf_codes = source.fetch_etf_codes()

    typed = []
    for sym in symbols:
        if sym.code in etf_codes:
            sym = sym.model_copy(update={"symbol_type": "etf"})
        elif is_etn_name(sym.name):
            sym = sym.model_copy(update={"symbol_type": "etn"})
        typed.append(sym)

    return context.symbol_repository.upsert_many(typed)
