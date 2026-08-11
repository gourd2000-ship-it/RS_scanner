from app.crawler.sources.base import SymbolUniverseFetchResult
from app.schemas.market_data import SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_symbols import sync_symbols


class UniverseSource:
    def __init__(self, symbols=None, error: Exception | None = None):
        self.symbols = symbols or []
        self.error = error

    def fetch_symbols(self):
        if self.error:
            raise self.error
        return self.symbols

    def fetch_etf_codes(self):
        return {"000002"}


class PartialUniverseSource(UniverseSource):
    def fetch_symbol_universe(self):
        return SymbolUniverseFetchResult(
            symbols=self.symbols,
            pages_total=3,
            pages_succeeded=2,
            complete=False,
            error_message="KOSDAQ:symbol_page_TimeoutError",
        )


def context_with_existing_symbol():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="OLD", name="Old", market="KOSPI")]
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id
    return context


def test_completed_snapshot_reconciles_missing_and_filters_price_targets():
    context = context_with_existing_symbol()
    source = UniverseSource(
        symbols=[
            SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
            SymbolPayload(code="000001", name="Alpha duplicate", market="KOSPI"),
            SymbolPayload(code="000002", name="ETF", market="KOSPI"),
        ]
    )

    sync_symbols(context, source)

    snapshot = context.universe_snapshot_repository.list_recent()[0]
    assert snapshot.status == "completed"
    assert snapshot.symbols_seen == 3
    assert snapshot.symbols_valid == 2
    assert snapshot.duplicate_count == 1
    assert snapshot.deactivation_candidates == ["OLD"]
    assert context.universe_snapshot_status == "completed"

    active_items, _ = context.symbol_repository.list_filtered(is_active=True)
    assert {item.code for item in active_items} == {"000001", "000002"}
    assert [item.code for item in context.symbol_repository.list_price_targets()] == ["000001"]


def test_partial_snapshot_keeps_previous_active_symbols():
    context = context_with_existing_symbol()
    source = UniverseSource(
        symbols=[
            SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
            SymbolPayload(code="", name="invalid", market="KOSPI"),
        ]
    )

    sync_symbols(context, source)

    snapshot = context.universe_snapshot_repository.list_recent()[0]
    assert snapshot.status == "partial"
    assert snapshot.invalid_count == 1
    assert context.universe_snapshot_status == "partial"
    assert {symbol.code for symbol in context.symbol_repository.list_price_targets()} == {
        "OLD",
        "000001",
    }


def test_failed_snapshot_keeps_previous_active_symbols():
    context = context_with_existing_symbol()
    source = UniverseSource(error=RuntimeError("provider down"))

    sync_symbols(context, source)

    snapshot = context.universe_snapshot_repository.list_recent()[0]
    assert snapshot.status == "failed"
    assert context.universe_snapshot_status == "failed"
    assert [symbol.code for symbol in context.symbol_repository.list_price_targets()] == ["OLD"]


def test_incomplete_page_snapshot_records_page_progress_without_reconcile():
    context = context_with_existing_symbol()
    source = PartialUniverseSource(
        symbols=[SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )

    sync_symbols(context, source)

    snapshot = context.universe_snapshot_repository.list_recent()[0]
    assert snapshot.status == "partial"
    assert snapshot.pages_total == 3
    assert snapshot.pages_succeeded == 2
    assert snapshot.error_message == "KOSDAQ:symbol_page_TimeoutError"
    assert snapshot.deactivation_candidates == []
    assert {symbol.code for symbol in context.symbol_repository.list_price_targets()} == {
        "OLD",
        "000001",
    }
