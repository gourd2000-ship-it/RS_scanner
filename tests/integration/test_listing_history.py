"""Integration-level BT03 replay checks using an isolated SQL database."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository


def test_replay_keeps_listing_and_delisting_boundaries_as_separate_evidence_rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="032980", isin="KR7032980009", name="다른 상폐 표본",
            market="KOSDAQ", security_type="stock", listing_status="delisted",
        )
        session.add(instrument)
        session.flush()
        repository = ListingHistoryRepository(session)
        listed = ListingEventInput(
            instrument_id=instrument.id, source="kind_export", source_contract_version="kind-listing-v1",
            source_record_key="032980:listing", event_type="listed", effective_from=date(2010, 1, 1),
            market="KOSDAQ", evidence_state="observed", payload={"code": "032980"},
        )
        delisted = ListingEventInput(
            instrument_id=instrument.id, source="kind_export", source_contract_version="kind-delisting-export-v1",
            source_record_key="032980:delisting", event_type="delisted", effective_from=date(2026, 7, 1),
            last_trading_date=date(2026, 6, 30), market="KOSDAQ", evidence_state="observed",
            payload={"code": "032980"},
        )

        repository.ingest(listed, source_file_hash="1" * 64)
        repository.ingest(delisted, source_file_hash="2" * 64)
        session.commit()
        replay = ListingHistoryRepository(session).list_for_instrument(instrument.id)

    assert [(row.event_type, row.effective_from, row.last_trading_date) for row in replay] == [
        ("listed", date(2010, 1, 1), None),
        ("delisted", date(2026, 7, 1), date(2026, 6, 30)),
    ]
