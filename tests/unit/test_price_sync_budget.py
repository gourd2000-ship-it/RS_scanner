from datetime import date
from decimal import Decimal
from threading import Lock
import time

from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import sync_prices


def test_price_sync_enforces_request_budget_and_worker_bound():
    context = build_memory_batch_context()
    symbols = [
        SymbolPayload(code=f"{index:06d}", name=f"Name {index}", market="KOSPI")
        for index in range(5)
    ]
    context.symbol_repository.upsert_many(symbols)

    class Source:
        max_concurrency = 2

        def __init__(self):
            self._lock = Lock()
            self.active = 0
            self.max_active = 0

        def fetch_daily_prices(self, code, since_date=None):
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.01)
                value = Decimal("100")
                return [
                    DailyPricePayload(
                        trade_date=date(2026, 8, 11),
                        open=value,
                        high=value,
                        low=value,
                        close=value,
                        volume=1,
                        change_rate=Decimal("0"),
                    )
                ]
            finally:
                with self._lock:
                    self.active -= 1

    source = Source()
    result = sync_prices(context, source, max_requests=3)

    assert result.target_count == 5
    assert result.fetched_count == 3
    assert result.skipped_count == 2
    assert source.max_active <= 2
