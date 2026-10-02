"""BT03 immutable historical listing-event import behavior."""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository


def _repository() -> tuple[Session, ListingHistoryRepository, Instrument]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    instrument = Instrument(
        krx_short_code="230980",
        isin="KR7230980001",
        name="상폐 표본",
        market="KOSDAQ",
        security_type="stock",
        listing_status="delisted",
    )
    session.add(instrument)
    session.flush()
    return session, ListingHistoryRepository(session), instrument


def _delisting_input(instrument_id: int, *, reason: str = "상장폐지") -> ListingEventInput:
    return ListingEventInput(
        instrument_id=instrument_id,
        source="kind_export",
        source_contract_version="kind-delisting-export-v1",
        source_record_key="230980:2026-06-05",
        source_url="https://kind.krx.co.kr/investwarn/delcompany.do",
        event_type="delisted",
        effective_from=date(2026, 6, 5),
        last_trading_date=date(2026, 6, 4),
        market="KOSDAQ",
        reason=reason,
        evidence_state="observed",
        payload={"code": "230980", "delisting_date": "2026-06-05", "reason": reason},
    )


def test_reimporting_identical_listing_evidence_is_idempotent_and_keeps_unknown_publication_time():
    _session, repository, instrument = _repository()
    observed_at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    input_event = _delisting_input(instrument.id)

    first = repository.ingest(
        input_event,
        source_file_hash="a" * 64,
        observed_at=observed_at,
    )
    duplicate = repository.ingest(
        input_event,
        source_file_hash="a" * 64,
        observed_at=observed_at,
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.event.id == first.event.id
    assert first.event.effective_from == date(2026, 6, 5)
    assert first.event.last_trading_date == date(2026, 6, 4)
    assert first.event.published_at is None
    assert first.event.observed_at == observed_at
    assert first.event.source_file_hash == "a" * 64
    assert first.event.evidence_state == "observed"


def test_corrected_source_record_creates_a_new_revision_without_losing_prior_evidence():
    session, repository, instrument = _repository()
    original = repository.ingest(_delisting_input(instrument.id, reason="상장폐지"), source_file_hash="a" * 64)
    corrected = repository.ingest(_delisting_input(instrument.id, reason="감사의견 거절"), source_file_hash="b" * 64)

    revisions = repository.list_revisions(source="kind_export", source_record_key="230980:2026-06-05")

    assert corrected.created is True
    assert corrected.event.id != original.event.id
    assert corrected.event.supersedes_id == original.event.id
    assert [row.id for row in revisions] == [original.event.id, corrected.event.id]
    assert [row.reason for row in revisions] == ["상장폐지", "감사의견 거절"]
    assert session.get(type(original.event), original.event.id).source_file_hash == "a" * 64


def test_listing_event_rejects_invalid_effective_range_without_using_price_boundaries_as_evidence():
    _session, repository, instrument = _repository()
    invalid = ListingEventInput(
        instrument_id=instrument.id,
        source="kind_export",
        source_contract_version="kind-delisting-export-v1",
        source_record_key="230980:invalid",
        event_type="trading_halted",
        effective_from=date(2026, 6, 5),
        effective_to=date(2026, 6, 5),
        evidence_state="unknown",
        payload={"code": "230980"},
    )

    try:
        repository.ingest(invalid, source_file_hash="c" * 64)
    except ValueError as exc:
        assert "effective_to must be later" in str(exc)
    else:
        raise AssertionError("invalid half-open interval was accepted")
