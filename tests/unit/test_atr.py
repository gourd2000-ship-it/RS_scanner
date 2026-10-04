from datetime import date, timedelta
from decimal import Decimal
from app.services.indicators.atr import AtrInput, compute_atr14

def row(i, high=Decimal('12'), low=Decimal('10'), close=Decimal('11'), reason=None): return AtrInput(date(2024,1,1)+timedelta(days=i), high, low, close, reason)
def test_atr_initializes_on_fourteenth_true_range_and_uses_wilder_smoothing():
    result=compute_atr14(tuple(row(i) for i in range(15)))
    assert result.values[12].status.value == 'warming_up'
    assert result.values[13].value == Decimal('2')
    assert result.values[14].value == Decimal('2')
def test_atr_gap_resets_warming_period():
    result=compute_atr14(tuple(row(i) for i in range(14))+(row(14, reason='invalid_ohlcv'),)+tuple(row(i) for i in range(15,29)))
    assert result.values[14].status.value == 'data_unavailable'
    assert result.values[-1].status.value == 'available'
