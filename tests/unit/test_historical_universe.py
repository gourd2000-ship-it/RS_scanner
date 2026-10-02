"""BT04 dated-universe manifests are independent from current Symbol state."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.historical_universe import HistoricalUniverseRequest, build_historical_universe


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _event(
    instrument_id: int,
    *,
    key: str,
    event_type: str,
    effective_from: date,
    market: str | None = None,
    market_to: str | None = None,
    effective_to: date | None = None,
    trading_status: str | None = None,
    evidence_state: str = "observed",
) -> ListingEventInput:
    return ListingEventInput(
        instrument_id=instrument_id,
        source="approved_export",
        source_contract_version="test-v1",
        source_record_key=key,
        event_type=event_type,
        effective_from=effective_from,
        effective_to=effective_to,
        market=market,
        market_to=market_to,
        trading_status=trading_status,
        evidence_state=evidence_state,
        payload={"key": key},
    )


def _weekdays(day: date) -> bool:
    return day.weekday() < 5


def test_manifest_keeps_a_delisted_security_through_its_last_trading_day_and_uses_historical_market():
    session = _session()
    instrument = Instrument(
        krx_short_code="230980", isin="KR7230980001", name="상폐 표본", market="KOSDAQ",
        security_type="stock", listing_status="delisted",
    )
    # Delisted legacy symbols must not be removed by current ``is_active``.
    legacy_symbol = Symbol(code="230980", name="상폐 표본", market="KOSDAQ", is_active=False)
    session.add_all([instrument, legacy_symbol])
    session.flush()
    repository = ListingHistoryRepository(session)
    repository.ingest(_event(instrument.id, key="listed", event_type="listed", effective_from=date(2010, 1, 1), market="KOSDAQ"), source_file_hash="a" * 64)
    repository.ingest(_event(instrument.id, key="transfer", event_type="market_transferred", effective_from=date(2015, 1, 2), market_to="KOSPI"), source_file_hash="b" * 64)
    repository.ingest(_event(instrument.id, key="delisted", event_type="delisted", effective_from=date(2015, 1, 6), market="KOSPI"), source_file_hash="c" * 64)

    manifest = build_historical_universe(
        session,
        HistoricalUniverseRequest(start=date(2015, 1, 1), end=date(2015, 1, 7), markets=("KOSPI",)),
        is_trading_day=_weekdays,
    )

    assert [(entry.trade_date, entry.instrument_id, entry.market) for entry in manifest.entries] == [
        (date(2015, 1, 2), instrument.id, "KOSPI"),
        (date(2015, 1, 5), instrument.id, "KOSPI"),
    ]
    assert manifest.expected_price_count == 2
    assert manifest.membership_completeness is None


def test_manifest_separates_halted_and_liquidation_trading_from_missing_price_expectations():
    session = _session()
    instrument = Instrument(
        krx_short_code="032980", isin="KR7032980009", name="정지 표본", market="KOSDAQ",
        security_type="stock", listing_status="listed",
    )
    session.add(instrument)
    session.flush()
    repository = ListingHistoryRepository(session)
    repository.ingest(_event(instrument.id, key="listed", event_type="listed", effective_from=date(2010, 1, 1), market="KOSDAQ"), source_file_hash="a" * 64)
    repository.ingest(_event(instrument.id, key="halt", event_type="trading_halted", effective_from=date(2015, 1, 2), effective_to=date(2015, 1, 5), trading_status="suspended"), source_file_hash="b" * 64)
    repository.ingest(_event(instrument.id, key="liquidation", event_type="trading_halted", effective_from=date(2015, 1, 5), trading_status="liquidation_trading"), source_file_hash="c" * 64)

    manifest = build_historical_universe(
        session,
        HistoricalUniverseRequest(start=date(2015, 1, 2), end=date(2015, 1, 6)),
        is_trading_day=_weekdays,
    )

    assert [(entry.trade_date, entry.trading_status, entry.price_expectation) for entry in manifest.entries] == [
        (date(2015, 1, 2), "suspended", "outside_trading_interval"),
        (date(2015, 1, 5), "liquidation_trading", "expected"),
        (date(2015, 1, 6), "liquidation_trading", "expected"),
    ]
    assert manifest.expected_price_count == 2


def test_strict_manifest_reports_unknown_and_non_stock_candidates_without_treating_them_as_complete_membership():
    session = _session()
    unknown = Instrument(
        krx_short_code="111111", isin="KR7111111111", name="근거 없음", market="KOSPI",
        security_type="stock", listing_status="listed",
    )
    etf = Instrument(
        krx_short_code="222222", isin="KR7222222222", name="ETF", market="KOSPI",
        security_type="etf", listing_status="listed",
    )
    session.add_all([unknown, etf])
    session.flush()
    ListingHistoryRepository(session).ingest(
        _event(etf.id, key="listed", event_type="listed", effective_from=date(2010, 1, 1), market="KOSPI"),
        source_file_hash="a" * 64,
    )

    manifest = build_historical_universe(
        session,
        HistoricalUniverseRequest(start=date(2015, 1, 2), end=date(2015, 1, 2)),
        is_trading_day=_weekdays,
    )

    assert manifest.entries == ()
    assert manifest.unknown_instrument_ids == (unknown.id,)
    assert manifest.excluded_instrument_counts == {"security_type_etf": 1}
    assert manifest.membership_completeness is None
