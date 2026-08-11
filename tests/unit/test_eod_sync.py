from datetime import date
from decimal import Decimal

from app.crawler.sources.eod import EodBatch
from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_eod import sync_eod_prices


def price(trade_date: date, close: int) -> DailyPricePayload:
    value = Decimal(close)
    return DailyPricePayload(
        trade_date=trade_date,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=1000,
        change_rate=Decimal("0"),
    )


class FakeEodSource:
    def __init__(self, rows_by_code):
        self.rows_by_code = rows_by_code
        self.calls: list[tuple[str, date]] = []

    def fetch_eod_prices(self, market: str, trade_date: date) -> EodBatch:
        self.calls.append((market, trade_date))
        return EodBatch(
            provider="fixture-eod",
            trade_date=trade_date,
            rows_by_code=self.rows_by_code,
            request_url=f"https://eod.test/{market}/{trade_date.isoformat()}",
            response_bytes=128,
        )


class FakeFallbackSource:
    def __init__(self):
        self.calls: list[str] = []

    def build_daily_price_url(self, code: str, since_date=None) -> str:
        return f"https://fallback.test/{code}"

    def fetch_daily_prices(self, code: str, since_date=None):
        self.calls.append(code)
        return [price(date(2026, 8, 11), 101)]


def make_context():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [
            SymbolPayload(code="A", name="Alpha", market="KOSPI"),
            SymbolPayload(code="B", name="Beta", market="KOSPI"),
        ]
    )
    context.job_id = context.crawl_job_repository.create_job("test").id
    return context


def test_bulk_eod_persists_rows_and_falls_back_only_for_missing_codes():
    context = make_context()
    trade_date = date(2026, 8, 11)
    eod = FakeEodSource({"A": [price(trade_date, 100)]})
    fallback = FakeFallbackSource()

    result = sync_eod_prices(
        context,
        eod,
        trade_date=trade_date,
        fallback_source=fallback,
    )

    assert eod.calls == [("KOSPI", trade_date)]
    assert fallback.calls == ["B"]
    assert result.target_count == 2
    assert result.fetched_count == 2
    assert result.failed_count == 0
    assert context.price_repository.get_latest_symbol_trade_date("A") == trade_date
    assert context.price_repository.get_latest_symbol_trade_date("B") == trade_date

    eod_results = context.crawl_target_result_repository.list_by_job(
        context.job_id,
        step_name="eod",
    )
    assert {item.target_key: item.status for item in eod_results} == {
        "A": "fetched",
        "B": "skipped",
    }

    fallback_results = context.crawl_target_result_repository.list_by_job(
        context.job_id,
        step_name="prices",
    )
    assert [item.target_key for item in fallback_results] == ["B"]


def test_invalid_bulk_eod_is_not_saved_and_marks_all_market_targets_failed():
    context = make_context()
    trade_date = date(2026, 8, 11)
    eod = FakeEodSource(
        {
            "A": [price(trade_date, 100)],
            "UNKNOWN": [price(trade_date, 100)],
        }
    )

    result = sync_eod_prices(context, eod, trade_date=trade_date)

    assert result.target_count == 2
    assert result.failed_count == 2
    assert context.price_repository.get_latest_symbol_trade_date("A") is None
    assert context.price_repository.get_latest_symbol_trade_date("B") is None
    failures = context.crawl_failure_repository.list_by_job(context.job_id)
    assert {failure.target_key for failure in failures} == {"A", "B"}
