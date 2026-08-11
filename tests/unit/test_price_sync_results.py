from datetime import date
from decimal import Decimal

from app.core.exceptions import PriceFetchError
from app.crawler.parsers.fchart import ParsedPriceRows
from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import retry_failed_price_targets, sync_prices


def make_price() -> DailyPricePayload:
    return DailyPricePayload(
        trade_date=date(2026, 8, 10),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        change_rate=Decimal("0"),
    )


class ControlledPriceSource:
    def __init__(self) -> None:
        self.fail = True
        self.partial = False

    def fetch_symbols(self):
        return [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]

    def fetch_benchmark_prices(self, market: str, since_date=None):
        return []

    def build_daily_price_url(self, code: str, since_date=None) -> str:
        return f"https://provider.test/prices/{code}"

    def fetch_daily_prices(self, code: str, since_date=None):
        if self.fail:
            raise PriceFetchError(
                "provider unavailable",
                url=self.build_daily_price_url(code, since_date),
                http_status=503,
                retry_count=2,
                response_bytes=123,
            )
        return ParsedPriceRows(
            [make_price()],
            invalid_rows=1 if self.partial else 0,
            response_bytes=45,
        )


class FailingCrawlFailureRepository:
    def record_failure(self, **_values):
        raise RuntimeError("failure store unavailable")


def make_context():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    job = context.crawl_job_repository.create_job("test")
    context.job_id = job.id
    return context, job.id


def test_failed_target_is_recorded_with_request_metadata():
    context, job_id = make_context()
    source = ControlledPriceSource()

    result = sync_prices(context, source)

    assert result.target_count == 1
    assert result.failed_count == 1
    assert result.succeeded_count == 0

    failure = context.crawl_failure_repository.list_by_job(job_id)[0]
    assert failure.url == "https://provider.test/prices/000001"
    assert failure.http_status == 503
    assert failure.response_bytes == 123
    assert failure.retry_count == 2

    target = context.crawl_target_result_repository.list_by_job(job_id, step_name="prices")[0]
    assert target.status == "failed"
    assert target.attempt_count == 1
    assert target.error_class == "PriceFetchError"


def test_partial_target_preserves_received_and_persisted_row_counts():
    context, job_id = make_context()
    source = ControlledPriceSource()
    source.fail = False
    source.partial = True

    result = sync_prices(context, source)

    assert result.partial_count == 1
    assert result.failed_count == 0
    result.validate_status_invariant()

    target = context.crawl_target_result_repository.list_by_job(job_id, step_name="prices")[0]
    assert target.status == "partial"
    assert target.rows_received == 2
    assert target.rows_persisted == 1
    assert target.response_bytes == 45


def test_retry_failed_targets_updates_final_result_and_attempt_count():
    context, job_id = make_context()
    source = ControlledPriceSource()

    first = sync_prices(context, source)
    assert first.failed_count == 1

    source.fail = False
    retry = retry_failed_price_targets(context, source, job_id)

    assert retry.fetched_count == 1
    assert retry.failed_count == 0

    target = context.crawl_target_result_repository.list_by_job(job_id, step_name="prices")[0]
    assert target.status == "fetched"
    assert target.attempt_count == 2
    assert target.rows_persisted == 1


def test_failure_record_insert_error_does_not_hide_original_failure(caplog):
    context, _job_id = make_context()
    context.crawl_failure_repository = FailingCrawlFailureRepository()
    source = ControlledPriceSource()

    result = sync_prices(context, source)

    assert result.failed_count == 1
    assert result.target_results["000001"].error_class == "PriceFetchError"
    assert "failed to record crawl failure for 000001" in caplog.text
