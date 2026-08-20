from datetime import date, timedelta
from decimal import Decimal

from app.core.exceptions import PriceFetchError
from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.calculate_rs import _refetch_adjusted_prices
from app.services.batch.context import build_memory_batch_context


def price(day: int, close: int) -> DailyPricePayload:
    return DailyPricePayload(
        trade_date=date(2026, 8, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1000,
        change_rate=Decimal("0"),
    )


class RefetchSource:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, object]] = []

    def build_daily_price_url(self, code: str, since_date=None) -> str:
        return f"https://provider.test/refetch/{code}"

    def fetch_daily_prices(self, code: str, since_date=None):
        self.calls.append((code, since_date))
        if self.fail:
            raise PriceFetchError(
                "refetch failed",
                url=self.build_daily_price_url(code, since_date),
                http_status=500,
                retry_count=1,
                response_bytes=77,
            )
        return [price(0, 100), price(1, 110)]


class ConflictingRefetchSource(RefetchSource):
    reject_provider_conflicts = True

    def fetch_daily_prices(self, code: str, since_date=None):
        self.calls.append((code, since_date))
        return [price(0, 100), price(1, 110)]


def make_context():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    context.price_repository.save_symbol_prices("000001", [price(0, 90)])
    context.job_id = context.crawl_job_repository.create_job("test").id
    return context


def test_corporate_action_refetch_uses_injected_source_and_records_result():
    context = make_context()
    source = RefetchSource()
    context.price_source = source

    assert _refetch_adjusted_prices(context, ["000001"]) == 1
    assert source.calls == [("000001", None)]
    assert context.price_repository.get_latest_symbol_trade_date("000001") == date(2026, 8, 2)

    result = context.crawl_target_result_repository.list_by_job(
        context.job_id,
        step_name="corporate_action",
    )[0]
    assert result.status == "fetched"
    assert result.rows_received == 2
    assert result.rows_persisted == 2


def test_corporate_action_refetch_failure_is_recorded():
    context = make_context()
    source = RefetchSource(fail=True)
    context.price_source = source

    assert _refetch_adjusted_prices(context, ["000001"]) == 0

    result = context.crawl_target_result_repository.list_by_job(
        context.job_id,
        step_name="corporate_action",
    )[0]
    assert result.status == "failed"
    assert result.http_status == 500

    failure = context.crawl_failure_repository.list_by_job(context.job_id)[0]
    assert failure.target_type == "corporate_action"
    assert failure.url == "https://provider.test/refetch/000001"
    assert failure.retry_count == 1


def test_corporate_action_refetch_does_not_overwrite_provider_conflict():
    context = make_context()
    source = ConflictingRefetchSource()
    context.price_source = source

    assert _refetch_adjusted_prices(context, ["000001"]) == 0
    assert context.price_repository.get_symbol_prices("000001")[0].close == Decimal("90")

    result = context.crawl_target_result_repository.list_by_job(
        context.job_id,
        step_name="corporate_action",
    )[0]
    assert result.status == "failed"
    assert result.error_class == "ProviderConflictError"
