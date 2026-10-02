"""Idempotent persistence for source-backed listing-history evidence."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.listing_event import ListingEvent


_EVENT_TYPES = frozenset({"listed", "delisted", "market_transferred", "trading_halted", "trading_resumed", "code_changed"})
_EVIDENCE_STATES = frozenset({"observed", "inferred", "unknown"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ListingEventInput:
    instrument_id: int
    source: str
    source_contract_version: str
    source_record_key: str
    event_type: str
    effective_from: date
    evidence_state: str
    payload: dict[str, object]
    source_url: str | None = None
    effective_to: date | None = None
    published_at: datetime | None = None
    last_trading_date: date | None = None
    market: str | None = None
    market_to: str | None = None
    provider_code: str | None = None
    provider_code_to: str | None = None
    trading_status: str | None = None
    reason: str | None = None
    parser_version: str = "listing-history-json-v1"


@dataclass(frozen=True)
class ListingEventIngestResult:
    event: ListingEvent
    created: bool


class ListingHistoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest(
        self,
        event: ListingEventInput,
        *,
        source_file_hash: str,
        observed_at: datetime | None = None,
    ) -> ListingEventIngestResult:
        """Store an immutable revision, suppressing exact source-material replays."""
        _validate_event(event, source_file_hash)
        payload = _canonical_payload(event)
        content_hash = _hash(payload)
        duplicate = self.session.scalar(
            select(ListingEvent).where(
                ListingEvent.source == event.source,
                ListingEvent.source_record_key == event.source_record_key,
                ListingEvent.content_hash == content_hash,
            )
        )
        if duplicate is not None:
            return ListingEventIngestResult(event=duplicate, created=False)

        prior = self.session.scalar(
            select(ListingEvent)
            .where(
                ListingEvent.source == event.source,
                ListingEvent.source_record_key == event.source_record_key,
            )
            .order_by(ListingEvent.id.desc())
        )
        now = observed_at or datetime.now(timezone.utc)
        row = ListingEvent(
            instrument_id=event.instrument_id,
            source=event.source,
            source_contract_version=event.source_contract_version,
            source_record_key=event.source_record_key,
            source_url=event.source_url,
            source_file_hash=source_file_hash,
            parser_version=event.parser_version,
            content_hash=content_hash,
            event_type=event.event_type,
            effective_from=event.effective_from,
            effective_to=event.effective_to,
            published_at=event.published_at,
            observed_at=now,
            last_trading_date=event.last_trading_date,
            market=event.market,
            market_to=event.market_to,
            provider_code=event.provider_code,
            provider_code_to=event.provider_code_to,
            trading_status=event.trading_status,
            reason=event.reason,
            evidence_state=event.evidence_state,
            payload=payload,
            supersedes_id=prior.id if prior is not None else None,
            imported_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return ListingEventIngestResult(event=row, created=True)

    def list_revisions(self, *, source: str, source_record_key: str) -> list[ListingEvent]:
        return list(
            self.session.scalars(
                select(ListingEvent)
                .where(ListingEvent.source == source, ListingEvent.source_record_key == source_record_key)
                .order_by(ListingEvent.id)
            )
        )

    def list_for_instrument(self, instrument_id: int) -> list[ListingEvent]:
        return list(
            self.session.scalars(
                select(ListingEvent)
                .where(ListingEvent.instrument_id == instrument_id)
                .order_by(ListingEvent.effective_from, ListingEvent.id)
            )
        )

    def list_current_for_instruments(
        self, instrument_ids: list[int], *, as_known_at: datetime | None = None
    ) -> list[ListingEvent]:
        """Return the latest revision for each source record, retaining raw revisions elsewhere."""
        if not instrument_ids:
            return []
        statement = select(ListingEvent).where(ListingEvent.instrument_id.in_(instrument_ids))
        if as_known_at is not None:
            statement = statement.where(ListingEvent.imported_at <= as_known_at)
        rows = list(
            self.session.scalars(statement.order_by(ListingEvent.imported_at, ListingEvent.id))
        )
        current: dict[tuple[str, str], ListingEvent] = {}
        for row in rows:
            current[(row.source, row.source_record_key)] = row
        return sorted(current.values(), key=lambda row: (row.instrument_id, row.effective_from, row.id))


def _validate_event(event: ListingEventInput, source_file_hash: str) -> None:
    if event.event_type not in _EVENT_TYPES:
        raise ValueError(f"unsupported listing event type: {event.event_type}")
    if event.evidence_state not in _EVIDENCE_STATES:
        raise ValueError(f"unsupported evidence state: {event.evidence_state}")
    if not event.source.strip() or not event.source_record_key.strip() or not event.source_contract_version.strip():
        raise ValueError("source, source_record_key, and source_contract_version are required")
    if event.effective_to is not None and event.effective_to <= event.effective_from:
        raise ValueError("effective_to must be later than effective_from for a [effective_from, effective_to) interval")
    if not _SHA256.fullmatch(source_file_hash):
        raise ValueError("source_file_hash must be a lowercase SHA-256 digest")


def _canonical_payload(event: ListingEventInput) -> str:
    material = asdict(event)
    return json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize listing history value {type(value)!r}")
