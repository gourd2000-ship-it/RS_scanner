"""격리 PostgreSQL에서 한 트랜잭션으로 OHLCV 데이터셋을 생성한다."""

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.data_quality import PriceObservation
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.clean_backtest_snapshot import create_clean_backtest_dataset
from app.services.validation.cleansing_policy import CleansingSelection


def test_clean_snapshot_on_postgres_is_reproducible_and_rolls_back():
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test",
    )
    engine = create_engine(database_url, isolation_level="REPEATABLE READ", pool_pre_ping=True)
    try:
        try:
            connection = engine.connect()
        except Exception as exc:
            pytest.skip(f"isolated PostgreSQL unavailable: {type(exc).__name__}")
        with connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, autoflush=False) as session:
                    instrument = Instrument(krx_short_code="CLTEST", name="검증", market="KOSPI",
                                            security_type="stock", listing_status="listed")
                    session.add(instrument)
                    session.flush()
                    symbol = Symbol(code="CLTEST", name="검증", market="KOSPI", instrument_id=instrument.id)
                    session.add(symbol)
                    session.flush()
                    ListingHistoryRepository(session).ingest(ListingEventInput(
                        instrument_id=instrument.id, source="fixture", source_contract_version="v1",
                        source_record_key="cltest-listed", event_type="listed", effective_from=date(2020, 1, 1),
                        market="KOSPI", evidence_state="observed", payload={},
                    ), source_file_hash="a" * 64, observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
                    session.add(PriceObservation(
                        symbol_id=symbol.id, trade_date=date(2020, 1, 2),
                        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                        volume=10, change_rate=Decimal("0"), provider="kiwoom", adjustment_type="1",
                        payload_hash="b" * 64, observed_at=datetime(2020, 1, 3, tzinfo=timezone.utc),
                    ))
                    session.flush()
                    selection = CleansingSelection(
                        start=date(2020, 1, 2), end=date(2020, 1, 3), selection_as_of=date(2020, 1, 3),
                        observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc),
                    )
                    first = create_clean_backtest_dataset(session, selection=selection, adjustment_policy="kiwoom:1")
                    second = create_clean_backtest_dataset(session, selection=selection, adjustment_policy="kiwoom:1")
                    assert second.id == first.id
                    assert first.manifest["coverage"] == {"missing": 1, "valid": 1}
                    assert first.prices[0].close == Decimal("100")
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
