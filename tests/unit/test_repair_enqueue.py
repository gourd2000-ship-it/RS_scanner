from app.core.exceptions import PriceFetchError
from app.schemas.market_data import SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import sync_prices


class FailingNaverSource:
    provider_name = "naver"
    adjusted_prices = True

    def fetch_symbols(self):
        return []

    def fetch_benchmark_prices(self, market, since_date=None):
        return []

    def build_daily_price_url(self, code, since_date=None):
        return f"https://finance.naver.com/fchart/{code}"

    def fetch_daily_prices(self, code, since_date=None):
        raise PriceFetchError(
            "provider rate limit",
            url=self.build_daily_price_url(code, since_date),
            http_status=429,
            retry_count=1,
            response_bytes=12,
        )


def test_naver_failure_is_logged_but_never_enqueued_for_sam_repair():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="005930", name="삼성전자", market="KOSPI")]
    )
    context.job_id = context.crawl_job_repository.create_job("daily_full").id
    source = FailingNaverSource()

    first = sync_prices(context, source, max_requests=1)
    second = sync_prices(context, source, max_requests=1, use_checkpoints=False)

    assert first.failed_count == 1
    assert second.failed_count == 1
    requests = context.repair_queue_repository.list_all()
    assert requests == []
