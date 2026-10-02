"""상폐 lifecycle을 제외한 역사 OHLCV 감사 대상 검사."""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.validation.cleansing_policy import CleansingSelection, select_cleansing_universe


def _event(instrument_id: int, key: str, kind: str, day: date) -> ListingEventInput:
    return ListingEventInput(
        instrument_id=instrument_id, source="fixture", source_contract_version="v1",
        source_record_key=key, event_type=kind, effective_from=day,
        market="KOSPI", evidence_state="observed", payload={"kind": kind},
    )


def test_selection_excludes_only_the_delisted_lifecycle_and_keeps_unknown_separate():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        old = Instrument(krx_short_code="123456", name="옛 회사", market="KOSPI", security_type="stock", listing_status="delisted")
        new = Instrument(krx_short_code="123456", name="새 회사", market="KOSPI", security_type="stock", listing_status="listed")
        unknown = Instrument(krx_short_code="654321", name="미확인", market="KOSPI", security_type="stock", listing_status="listed")
        session.add_all([old, new, unknown])
        session.flush()
        repo = ListingHistoryRepository(session)
        seen = datetime(2019, 1, 2, tzinfo=timezone.utc)
        repo.ingest(_event(old.id, "old-list", "listed", date(2010, 1, 1)), source_file_hash="a" * 64, observed_at=seen)
        repo.ingest(_event(old.id, "old-del", "delisted", date(2018, 1, 1)), source_file_hash="b" * 64, observed_at=seen)
        repo.ingest(_event(new.id, "new-list", "listed", date(2019, 1, 1)), source_file_hash="c" * 64, observed_at=seen)
        selection = select_cleansing_universe(session, CleansingSelection(
            start=date(2020, 1, 2), end=date(2020, 1, 2),
            selection_as_of=date(2020, 1, 2),
            observation_cutoff=datetime(2020, 1, 3, tzinfo=timezone.utc),
        ))

        assert selection.excluded_delisted_ids == (old.id,)
        assert selection.unknown_instrument_ids == (unknown.id,)
        assert [entry.instrument_id for entry in selection.universe.entries] == [new.id]
        assert selection.universe.excluded_instrument_counts["delisted_by_selection_date"] == 1


def test_selection_uses_confirmed_instrument_delisting_when_event_is_missing():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        old = Instrument(
            krx_short_code="004510", name="옛 회사", market="KOSDAQ",
            security_type="stock", listed_at=date(1996, 7, 1),
            delisted_at=date(2004, 4, 28), listing_status="delisted",
        )
        new = Instrument(
            krx_short_code="004510", name="새 회사", market="KOSDAQ",
            security_type="stock", listed_at=date(2019, 1, 1), listing_status="listed",
        )
        session.add_all([old, new])
        session.flush()
        repo = ListingHistoryRepository(session)
        seen = datetime(2019, 1, 2, tzinfo=timezone.utc)
        repo.ingest(_event(old.id, "old-list", "listed", date(1996, 7, 1)),
                    source_file_hash="a" * 64, observed_at=seen)
        repo.ingest(_event(new.id, "new-list", "listed", date(2019, 1, 1)),
                    source_file_hash="b" * 64, observed_at=seen)
        selection = select_cleansing_universe(session, CleansingSelection(
            start=date(2020, 1, 2), end=date(2020, 1, 2),
            selection_as_of=date(2020, 1, 2),
            observation_cutoff=datetime(2020, 1, 3, tzinfo=timezone.utc),
        ))
        assert selection.excluded_delisted_ids == (old.id,)
        assert [entry.instrument_id for entry in selection.universe.entries] == [new.id]
