"""OHLCV 감사 대상의 역사적 종목 identity와 제외 근거를 고정한다."""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument
from app.repositories.listing_history_repository import ListingHistoryRepository
from app.services.historical_universe import (
    HistoricalUniverseManifest,
    HistoricalUniverseRequest,
    build_historical_universe,
)


@dataclass(frozen=True)
class CleansingSelection:
    start: date
    end: date
    selection_as_of: date
    observation_cutoff: datetime
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    exclude_delisted: bool = True

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("start must not follow end")
        if self.selection_as_of < self.end:
            raise ValueError("selection_as_of must cover the requested end date")
        if self.observation_cutoff.tzinfo is None:
            raise ValueError("observation_cutoff must include a timezone")
        if self.observation_cutoff.astimezone(timezone.utc).date() < self.selection_as_of:
            raise ValueError("observation_cutoff must not predate selection_as_of")
        if not self.markets or not set(self.markets) <= {"KOSPI", "KOSDAQ"}:
            raise ValueError("markets must contain KOSPI or KOSDAQ")


@dataclass(frozen=True)
class CleansingUniverse:
    selection: CleansingSelection
    universe: HistoricalUniverseManifest
    excluded_delisted_ids: tuple[int, ...]
    unknown_instrument_ids: tuple[int, ...]


def select_cleansing_universe(session: Session, selection: CleansingSelection) -> CleansingUniverse:
    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    revisions = ListingHistoryRepository(session).list_current_for_instruments(
        [instrument.id for instrument in instruments], as_known_at=selection.observation_cutoff
    )
    events: dict[int, list] = {}
    for revision in revisions:
        events.setdefault(revision.instrument_id, []).append(revision)

    excluded: list[int] = []
    for instrument in instruments:
        if instrument.security_type != "stock" or not selection.exclude_delisted:
            continue
        transitions = sorted(
            (event for event in events.get(instrument.id, [])
             if event.event_type in {"listed", "delisted"}
             and event.effective_from <= selection.selection_as_of),
            key=lambda event: (event.effective_from, event.id),
        )
        observed_event_delisting = (
            bool(transitions)
            and transitions[-1].event_type == "delisted"
            and transitions[-1].evidence_state == "observed"
        )
        confirmed_instrument_delisting = (
            instrument.listing_status == "delisted"
            and instrument.delisted_at is not None
            and instrument.delisted_at <= selection.selection_as_of
            and not any(
                event.event_type == "listed" and event.effective_from > instrument.delisted_at
                for event in transitions
            )
        )
        if observed_event_delisting or confirmed_instrument_delisting:
            excluded.append(instrument.id)

    universe = build_historical_universe(
        session,
        HistoricalUniverseRequest(start=selection.start, end=selection.end, markets=selection.markets),
        as_known_at=selection.observation_cutoff,
        excluded_instrument_ids=frozenset(excluded),
    )
    return CleansingUniverse(
        selection=selection,
        universe=universe,
        excluded_delisted_ids=tuple(excluded),
        unknown_instrument_ids=universe.unknown_instrument_ids,
    )
