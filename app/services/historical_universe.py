"""Build a dated, evidence-backed universe before any historical price exists."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market_calendar import krx_market_day_status
from app.models.instrument import Instrument
from app.models.listing_event import ListingEvent
from app.repositories.listing_history_repository import ListingHistoryRepository


TradingDayPredicate = Callable[[date], bool]


@dataclass(frozen=True)
class HistoricalUniverseRequest:
    start: date
    end: date
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    security_types: tuple[str, ...] = ("stock",)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("end must not be earlier than start")


@dataclass(frozen=True)
class HistoricalUniverseEntry:
    trade_date: date
    instrument_id: int
    market: str
    security_type: str
    membership_evidence_state: str
    trading_status: str
    price_expectation: str


@dataclass(frozen=True)
class HistoricalUniverseManifest:
    request: HistoricalUniverseRequest
    entries: tuple[HistoricalUniverseEntry, ...]
    expected_price_count: int
    membership_completeness: None
    unknown_instrument_ids: tuple[int, ...]
    excluded_instrument_counts: dict[str, int]


@dataclass
class _MembershipState:
    listed: bool = False
    market: str | None = None
    evidence_state: str = "unknown"
    trading_status: str = "trading"


def build_historical_universe(
    session: Session,
    request: HistoricalUniverseRequest,
    *,
    is_trading_day: TradingDayPredicate | None = None,
    as_known_at: datetime | None = None,
    excluded_instrument_ids: frozenset[int] = frozenset(),
) -> HistoricalUniverseManifest:
    """Build explicit price targets without consulting current ``Symbol.is_active``.

    The listing-event ledger is the membership authority.  An instrument lacking
    a listing record remains visible as unknown but is not silently promoted to
    a strict historical member.
    """
    is_trading_day = is_trading_day or _is_krx_trading_day
    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    events = ListingHistoryRepository(session).list_current_for_instruments(
        [instrument.id for instrument in instruments], as_known_at=as_known_at
    )
    events_by_instrument: dict[int, list[ListingEvent]] = {}
    for event in events:
        events_by_instrument.setdefault(event.instrument_id, []).append(event)

    entries: list[HistoricalUniverseEntry] = []
    unknown_ids: list[int] = []
    excluded: dict[str, int] = {}
    for instrument in instruments:
        if instrument.id in excluded_instrument_ids:
            _increment(excluded, "delisted_by_selection_date")
            continue
        instrument_events = events_by_instrument.get(instrument.id, [])
        if instrument.security_type not in request.security_types:
            _increment(excluded, f"security_type_{instrument.security_type}")
            continue
        if not any(event.event_type == "listed" for event in instrument_events):
            unknown_ids.append(instrument.id)
            continue
        entries.extend(
            _entries_for_instrument(
                instrument,
                instrument_events,
                request=request,
                is_trading_day=is_trading_day,
            )
        )

    entries.sort(key=lambda row: (row.trade_date, row.market, row.instrument_id))
    return HistoricalUniverseManifest(
        request=request,
        entries=tuple(entries),
        expected_price_count=sum(row.price_expectation == "expected" for row in entries),
        membership_completeness=None,
        unknown_instrument_ids=tuple(sorted(unknown_ids)),
        excluded_instrument_counts=excluded,
    )


def _entries_for_instrument(
    instrument: Instrument,
    events: list[ListingEvent],
    *,
    request: HistoricalUniverseRequest,
    is_trading_day: TradingDayPredicate,
) -> list[HistoricalUniverseEntry]:
    events_by_day: dict[date, list[ListingEvent]] = {}
    expirations: dict[date, list[ListingEvent]] = {}
    for event in events:
        events_by_day.setdefault(event.effective_from, []).append(event)
        if event.effective_to is not None:
            expirations.setdefault(event.effective_to, []).append(event)

    state = _MembershipState()
    entries: list[HistoricalUniverseEntry] = []
    for transition_day in sorted(set(events_by_day) | set(expirations)):
        if transition_day >= request.start:
            break
        _apply_transitions(state, transition_day, events_by_day, expirations)

    day = request.start
    while day <= request.end:
        _apply_transitions(state, day, events_by_day, expirations)
        if (
            state.listed
            and state.market in request.markets
            and is_trading_day(day)
        ):
            entries.append(
                HistoricalUniverseEntry(
                    trade_date=day,
                    instrument_id=instrument.id,
                    market=state.market,
                    security_type=instrument.security_type,
                    membership_evidence_state=state.evidence_state,
                    trading_status=state.trading_status,
                    price_expectation=(
                        "outside_trading_interval"
                        if state.trading_status in {"suspended", "halted"}
                        else "expected"
                    ),
                )
            )
        day += timedelta(days=1)
    return entries


def _apply_transitions(
    state: _MembershipState,
    day: date,
    events_by_day: dict[date, list[ListingEvent]],
    expirations: dict[date, list[ListingEvent]],
) -> None:
    for event in expirations.get(day, []):
        if event.event_type == "listed":
            state.listed = False
        elif event.event_type == "trading_halted":
            state.trading_status = "trading"
    for event in events_by_day.get(day, []):
        if event.event_type == "listed":
            state.listed = True
            state.market = event.market or state.market
            state.evidence_state = event.evidence_state
        elif event.event_type == "delisted":
            state.listed = False
        elif event.event_type == "market_transferred":
            state.market = event.market_to or event.market or state.market
            state.evidence_state = event.evidence_state
        elif event.event_type == "trading_halted":
            state.trading_status = event.trading_status or "suspended"
        elif event.event_type == "trading_resumed":
            state.trading_status = event.trading_status or "trading"


def _is_krx_trading_day(day: date) -> bool:
    return krx_market_day_status(day).is_open


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
