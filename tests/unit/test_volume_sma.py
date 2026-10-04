from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.services.indicators.contracts import EmaInputRow, EmaInputStatus, EmaSourcePolicy, IdentitySnapshot
from app.services.indicators.volume_sma import compute_volume_sma50


def _policy():
    return EmaSourcePolicy("kiwoom", "1", ("v1",), datetime(2026, 1, 1, tzinfo=UTC))


def _row(index: int, volume: int | None, *, valid: bool = True):
    day = date(2024, 1, 1) + timedelta(days=index)
    return EmaInputRow(
        trade_date=day, instrument_id=1, symbol_id=1, observation_id=index + 1,
        identity=IdentitySnapshot(index + 1, 1, "kiwoom", "000001", 1, "matched", None, None, "v1", datetime(2024, 1, 1, tzinfo=UTC)),
        provider="kiwoom", provider_symbol="000001", adjustment_type="1", parser_version="v1",
        close=Decimal("100"), volume=volume, observed_at=datetime(2024, 1, 1, tzinfo=UTC),
        payload_hash=f"{index:064x}", input_status=EmaInputStatus.ELIGIBLE if valid else EmaInputStatus.INVALID,
        source_policy=_policy(),
    )


def test_zero_volume_is_included_and_fiftieth_row_becomes_available():
    result = compute_volume_sma50(tuple(_row(index, 0 if index == 0 else 100) for index in range(50)))
    assert result.values[48].status.value == "warming_up"
    last = result.values[49]
    assert last.status.value == "available"
    assert last.value == Decimal("98")


def test_unavailable_row_resets_the_window_until_fifty_new_rows_exist():
    rows = tuple(_row(index, 100) for index in range(50)) + (_row(50, None, valid=False),) + tuple(_row(index, 200) for index in range(51, 101))
    result = compute_volume_sma50(rows)
    assert result.values[50].status.value == "data_unavailable"
    assert result.values[99].status.value == "warming_up"
    assert result.values[100].status.value == "available"
    assert result.values[100].value == Decimal("200")


def test_result_hash_is_deterministic():
    rows = tuple(_row(index, index) for index in range(50))
    assert compute_volume_sma50(rows).result_hash == compute_volume_sma50(rows).result_hash
