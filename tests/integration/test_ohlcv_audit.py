"""가격이 없는 거래일까지 포함하는 읽기 전용 감사."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import OhlcExclusion, PriceObservation
from app.models.daily_price import DailyPrice
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.validation.cleansing_policy import CleansingSelection
from app.services.validation.ohlcv_audit import audit_ohlcv


def test_audit_reports_missing_days_and_source_verified_prices(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000001", name="표본", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000001", name="표본", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        ListingHistoryRepository(session).ingest(ListingEventInput(
            instrument_id=instrument.id, source="fixture", source_contract_version="v1",
            source_record_key="listed", event_type="listed", effective_from=date(2010, 1, 1),
            market="KOSPI", evidence_state="observed", payload={},
        ), source_file_hash="a" * 64, observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        session.add(DailyPrice(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                               open=Decimal("90"), high=Decimal("91"), low=Decimal("89"), close=Decimal("90"),
                               volume=10, change_rate=Decimal("0"), source="naver"))
        session.add(PriceObservation(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                                     open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                                     volume=10, change_rate=Decimal("0"), provider="kiwoom", adjustment_type="1",
                                     payload_hash="b" * 64, observed_at=datetime(2020, 1, 3, tzinfo=timezone.utc)))
        session.flush()
        result = audit_ohlcv(session, selection=CleansingSelection(
            start=date(2020, 1, 2), end=date(2020, 1, 3),
            selection_as_of=date(2020, 1, 3),
            observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc),
        ), adjustment_policy="kiwoom:1", output_dir=tmp_path)

        assert result.expected == 2
        assert result.valid == 1
        assert result.missing == 1
        assert result.source_verified == 1
        assert "2020-01-03" in (tmp_path / "gaps.csv").read_text()
        assert "000001" in (tmp_path / "symbol_year_coverage.csv").read_text()
        assert "canonical_price_differs" in (tmp_path / "source_conflicts.csv").read_text()
        assert session.get(DailyPrice, 1).close == Decimal("90")
        assert not session.dirty

        session.add(OhlcExclusion(symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                                  reason_code="REVIEWED_INVALID", status="APPROVED"))
        session.flush()
        excluded = audit_ohlcv(session, selection=CleansingSelection(
            start=date(2020, 1, 2), end=date(2020, 1, 3),
            selection_as_of=date(2020, 1, 3),
            observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc),
        ), adjustment_policy="kiwoom:1", output_dir=tmp_path / "excluded")
        assert excluded.valid == 0
        assert excluded.invalid == 1
