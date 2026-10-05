"""Shared OHLC facts leave the versioned legacy EMA fingerprint unchanged."""
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from app.services.indicators.contracts import input_row_fingerprint
from app.services.indicators.input_selector import EmaInputSelector
from tests.unit.test_indicator_calculation_service import session, _seed, _policy, _observation


def test_shared_high_low_are_copied_but_do_not_change_legacy_ema_hash(session):
    instrument, symbol, mapping = _seed(session)
    day = date(2024, 1, 2)
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=day, close='100', observed_at=datetime(2024, 1, 2, tzinfo=UTC))
    row = EmaInputSelector(session).select_rows(instrument_id=instrument.id, trade_dates=(day,), policy=_policy())[0]
    assert row.high == Decimal('101') and row.low == Decimal('99')
    legacy = replace(row, high=None, low=None)
    assert row.fingerprint_material() == legacy.fingerprint_material()
    assert input_row_fingerprint(row) == input_row_fingerprint(legacy)
