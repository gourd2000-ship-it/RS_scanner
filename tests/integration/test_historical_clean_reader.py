"""승인된 보정·제외와 역사 공급자 관측을 함께 적용한다."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import OhlcCorrection, OhlcExclusion, PriceObservation
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.services.validation.historical_clean_reader import read_clean_price


def test_clean_reader_selects_adjusted_observation_and_applies_approved_correction():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000001", name="표본", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000001", name="표본", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        session.add(PriceObservation(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                                     open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                                     volume=10, change_rate=Decimal("0"), provider="kiwoom", adjustment_type="1",
                                     payload_hash="a" * 64, observed_at=datetime(2020, 1, 3, tzinfo=timezone.utc)))
        session.add(OhlcCorrection(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                                   field_name="close", corrected_value={"value": "100.5"},
                                   reason_code="SOURCE_CHECK", status="APPROVED"))
        session.flush()

        result = read_clean_price(session, instrument_id=instrument.id, trade_date=date(2020, 1, 2),
                                  provider="kiwoom", adjustment_type="1",
                                  observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc))
        assert result.status == "valid"
        assert result.values["close"] == Decimal("100.5")
        assert result.source_observation_id is not None
        assert result.correction_ids
        assert session.get(PriceObservation, result.source_observation_id).close == Decimal("100")

        session.add(OhlcExclusion(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                                  reason_code="REVIEWED_INVALID", status="APPROVED"))
        session.flush()
        excluded = read_clean_price(session, instrument_id=instrument.id, trade_date=date(2020, 1, 2),
                                    provider="kiwoom", adjustment_type="1",
                                    observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc))
        assert excluded.status == "invalid"
        assert excluded.values is None
        assert excluded.reason == "approved_exclusion"
