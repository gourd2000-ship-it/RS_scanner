from datetime import date
import importlib
from types import SimpleNamespace

from app.core.exceptions import PriceFetchError, ValidationError
from app.crawler.kiwoom_client import KiwoomChartResponse
from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices
from app.crawler.sources.kiwoom import KiwoomRestPriceSource
from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import sync_prices


sync_prices_module = importlib.import_module("app.services.batch.sync_prices")


def _kiwoom_row(day: str, close: str = "100") -> dict[str, str]:
    return {
        "dt": day,
        "open_pric": close,
        "high_pric": close,
        "low_pric": close,
        "cur_prc": close,
        "trde_qty": "1,000",
        "flu_rt": "0.00",
    }


def test_parse_kiwoom_daily_chart_rows():
    parsed = parse_kiwoom_daily_prices(
        {
            "return_code": 0,
            "stk_dt_pole_chart_qry": [
                _kiwoom_row("20260811", "+101"),
                _kiwoom_row("20260810", "100"),
            ],
        },
        response_bytes=321,
    )

    assert [row.trade_date for row in parsed] == [
        date(2026, 8, 10),
        date(2026, 8, 11),
    ]
    assert parsed[-1].close == 101
    assert parsed.response_bytes == 321


def test_parse_kiwoom_daily_chart_nested_output_shape():
    parsed = parse_kiwoom_daily_prices(
        {"output": {"ka10081OutBlock1": [_kiwoom_row("20260811")]}}
    )

    assert len(parsed) == 1
    assert parsed[0].trade_date == date(2026, 8, 11)


class FakeKiwoomClient:
    chart_url = "https://api.kiwoom.com/api/dostk/chart"
    max_concurrency = 1
    settings = SimpleNamespace(kiwoom_max_continuations=3)

    def __init__(self):
        self.calls: list[tuple[str, bool, str | None]] = []
        self.retry_counts = (0, 0)

    def fetch_daily_chart_page(self, code, *, base_date, continuation, next_key):
        self.calls.append((code, continuation, next_key))
        if not continuation:
            return KiwoomChartResponse(
                payload={"stk_dt_pole_chart_qry": [_kiwoom_row("20260810")]},
                response_bytes=100,
                status_code=200,
                continuation=True,
                next_key="next-1",
                retry_count=self.retry_counts[0],
            )
        return KiwoomChartResponse(
            payload={"stk_dt_pole_chart_qry": [_kiwoom_row("20260811", "101")]},
            response_bytes=110,
            status_code=200,
            continuation=False,
            next_key=None,
            retry_count=self.retry_counts[1],
        )


def test_kiwoom_source_handles_continuation_and_since_date():
    client = FakeKiwoomClient()
    source = KiwoomRestPriceSource(client)

    rows = source.fetch_daily_prices("000001", since_date=date(2026, 8, 10))

    assert [row.trade_date for row in rows] == [date(2026, 8, 11)]
    assert client.calls == [("000001", False, None), ("000001", True, "next-1")]
    assert rows.response_bytes == 210


def test_kiwoom_source_preserves_retry_count_across_pages():
    client = FakeKiwoomClient()
    client.retry_counts = (1, 2)

    rows = KiwoomRestPriceSource(client).fetch_daily_prices("000001")

    assert rows.retry_count == 3


class FailingPrimarySource:
    max_concurrency = 1

    def build_daily_price_url(self, code, since_date=None):
        return f"https://naver.test/{code}"

    def fetch_daily_prices(self, code, since_date=None):
        raise PriceFetchError(
            "primary unavailable",
            url=self.build_daily_price_url(code, since_date),
            http_status=503,
        )


class MatchingFallbackSource:
    max_concurrency = 1
    fetch_full_history_on_fallback = True
    reject_provider_conflicts = True

    def build_daily_price_url(self, code, since_date=None):
        return f"https://kiwoom.test/{code}"

    def fetch_daily_prices(self, code, since_date=None):
        assert since_date is None
        return [
            DailyPricePayload(
                trade_date=date(2026, 8, 10),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                change_rate=0,
            ),
            DailyPricePayload(
                trade_date=date(2026, 8, 11),
                open=101,
                high=102,
                low=100,
                close=101,
                volume=1100,
                change_rate=1,
            ),
        ]


class InvalidDataPrimarySource(FailingPrimarySource):
    def fetch_daily_prices(self, code, since_date=None):
        raise ValidationError("OHLC fields must be positive")


class SpyFallbackSource(MatchingFallbackSource):
    provider_name = "kiwoom_rest"

    def __init__(self):
        self.calls: list[str] = []

    def fetch_daily_prices(self, code, since_date=None):
        self.calls.append(code)
        return super().fetch_daily_prices(code, since_date=since_date)


def test_sync_prices_uses_kiwoom_only_for_primary_failures():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    context.price_repository.save_symbol_prices(
        "000001",
        [
            DailyPricePayload(
                trade_date=date(2026, 8, 10),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                change_rate=0,
            )
        ],
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id

    result = sync_prices(
        context,
        FailingPrimarySource(),
        fallback_source=MatchingFallbackSource(),
        fallback_max_requests=1,
    )

    assert result.fetched_count == 1
    assert result.failed_count == 0
    target = context.crawl_target_result_repository.list_by_job(
        job.id,
        step_name="prices",
    )[0]
    assert target.provider == "MatchingFallbackSource"
    assert target.attempt_count == 2
    assert context.price_repository.get_latest_symbol_trade_date("000001") == date(2026, 8, 11)
    failures = context.crawl_failure_repository.list_by_job(job.id)
    assert [failure.target_key for failure in failures] == ["000001"]


def test_kiwoom_fallback_rejects_conflicting_persisted_price():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    context.price_repository.save_symbol_prices(
        "000001",
        [
            DailyPricePayload(
                trade_date=date(2026, 8, 10),
                open=99,
                high=100,
                low=98,
                close=99,
                volume=1000,
                change_rate=0,
            )
        ],
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id

    result = sync_prices(
        context,
        FailingPrimarySource(),
        fallback_source=MatchingFallbackSource(),
        fallback_max_requests=1,
    )

    assert result.failed_count == 1
    target = result.target_results["000001"]
    assert target.error_class == "ProviderConflictError"
    assert context.price_repository.get_latest_symbol_trade_date("000001") == date(2026, 8, 10)


def test_kiwoom_fallback_does_not_mask_validation_failures():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id
    fallback = SpyFallbackSource()

    result = sync_prices(
        context,
        InvalidDataPrimarySource(),
        fallback_source=fallback,
        fallback_max_requests=1,
    )

    assert result.failed_count == 1
    assert result.target_results["000001"].error_class == "ValidationError"
    assert fallback.calls == []


def test_kiwoom_fallback_allowlist_limits_canary_targets(monkeypatch):
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [
            SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
            SymbolPayload(code="000002", name="Beta", market="KOSPI"),
        ]
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id
    fallback = SpyFallbackSource()
    monkeypatch.setattr(sync_prices_module.settings, "kiwoom_fallback_codes", "000001")

    result = sync_prices(
        context,
        FailingPrimarySource(),
        fallback_source=fallback,
        fallback_max_requests=2,
    )

    assert fallback.calls == ["000001"]
    assert result.fetched_count == 1
    assert result.failed_count == 1


def test_kiwoom_fallback_budget_skip_preserves_primary_failure(monkeypatch):
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [
            SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
            SymbolPayload(code="000002", name="Beta", market="KOSPI"),
        ]
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id
    fallback = SpyFallbackSource()
    monkeypatch.setattr(sync_prices_module.settings, "kiwoom_fallback_codes", "")

    result = sync_prices(
        context,
        FailingPrimarySource(),
        fallback_source=fallback,
        fallback_max_requests=1,
    )

    assert result.fetched_count == 1
    assert result.failed_count == 1
    records = context.crawl_target_result_repository.list_by_job(
        job.id,
        step_name="prices",
    )
    assert {record.status for record in records} == {"fetched", "failed"}
