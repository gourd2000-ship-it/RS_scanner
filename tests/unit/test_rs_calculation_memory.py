from datetime import date, timedelta
from decimal import Decimal

from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch import calculate_rs as calculate_rs_module
from app.services.batch.context import build_memory_batch_context


def _price(trade_date: date, close: int) -> DailyPricePayload:
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


def test_rs_calculation_retains_only_the_required_target_date_window(monkeypatch):
    context = build_memory_batch_context()
    context.target_date = date(2026, 9, 30)
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="000001", name="Alpha", market="KOSPI")]
    )
    history_start = context.target_date - timedelta(days=399)
    history = [
        _price(history_start + timedelta(days=index), index + 100)
        for index in range(400)
    ]
    history.extend(
        _price(context.target_date + timedelta(days=index), 600 + index)
        for index in range(1, 4)
    )
    context.price_repository.save_symbol_prices("000001", history)
    captured_windows = []

    def capture_series(series_by_market, **_kwargs):
        captured_windows.extend(series.prices for series in series_by_market["KOSPI"])
        return []

    monkeypatch.setattr(calculate_rs_module, "detect_corporate_action", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(calculate_rs_module, "calculate_combined_rs", capture_series)

    calculate_rs_module.calculate_rs(context)

    assert len(captured_windows) == 1
    assert len(captured_windows[0]) == 254
    assert captured_windows[0][0].trade_date == context.target_date - timedelta(days=253)
    assert captured_windows[0][-1].trade_date == context.target_date
