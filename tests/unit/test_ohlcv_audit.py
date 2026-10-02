"""OHLCV의 유효성·출처를 구분하는 규칙."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.validation.ohlcv_audit import classify_price, classify_transition


def _price(**changes):
    row = dict(trade_date=date(2020, 1, 2), open=Decimal("100"), high=Decimal("101"),
               low=Decimal("99"), close=Decimal("100"), volume=100)
    row.update(changes)
    return SimpleNamespace(**row)


def test_classification_separates_structure_from_source_verification():
    assert classify_price(_price(), source_verified=False).status == "review_required"
    assert classify_price(_price(), source_verified=True).status == "valid"
    assert classify_price(_price(volume=Decimal("1.5")), source_verified=True).status == "invalid"
    assert "INVALID_VOLUME" in classify_price(_price(volume=Decimal("1.5")), source_verified=True).reasons
    assert classify_price(_price(volume=0), source_verified=True).status == "valid"
    assert classify_price(_price(low=Decimal("102")), source_verified=True).status == "invalid"


def test_large_unexplained_close_change_requires_review_but_confirmed_action_does_not():
    assert classify_transition(Decimal("100"), Decimal("151"), corporate_action=False) == "EXTREME_RETURN_REVIEW"
    assert classify_transition(Decimal("100"), Decimal("151"), corporate_action=True) is None
    assert classify_transition(Decimal("100"), Decimal("151"), corporate_action=False,
                               consecutive=False) is None
