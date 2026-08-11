from datetime import date
from decimal import Decimal
import hashlib

import pytest

from app.crawler.sources.eod import EodBatch, EodBatchValidationError, validate_eod_batch
from app.schemas.market_data import DailyPricePayload
from app.services.validation.market_data import validate_prices
from app.core.exceptions import ValidationError


def row(day: date, close: int = 100) -> DailyPricePayload:
    value = Decimal(close)
    return DailyPricePayload(
        trade_date=day,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=10,
        change_rate=Decimal("0"),
    )


def test_eod_checksum_and_contract_metadata_are_verified():
    payload = b"fixture-payload"
    batch = EodBatch(
        provider="fixture",
        market="KOSPI",
        trade_date=date(2026, 8, 11),
        rows_by_code={"A": [row(date(2026, 8, 11))]},
        checksum=hashlib.sha256(payload).hexdigest(),
        raw_payload=payload,
        expected_row_count=1,
    )

    validate_eod_batch(
        batch,
        eligible_codes={"A"},
        expected_trade_date=date(2026, 8, 11),
        expected_market="KOSPI",
    )


def test_eod_checksum_mismatch_prevents_persistence_contract():
    batch = EodBatch(
        provider="fixture",
        trade_date=date(2026, 8, 11),
        rows_by_code={"A": [row(date(2026, 8, 11))]},
        checksum="bad",
        raw_payload=b"fixture-payload",
    )

    with pytest.raises(EodBatchValidationError, match="checksum mismatch"):
        validate_eod_batch(
            batch,
            eligible_codes={"A"},
            expected_trade_date=date(2026, 8, 11),
        )


def test_price_validation_rejects_duplicate_or_inconsistent_rows():
    day = date(2026, 8, 11)
    with pytest.raises(ValidationError, match="duplicate"):
        validate_prices([row(day), row(day)])

    invalid = row(day)
    invalid = invalid.model_copy(update={"high": Decimal("101"), "low": Decimal("101")})
    with pytest.raises(ValidationError, match="OHLC"):
        validate_prices([invalid])
