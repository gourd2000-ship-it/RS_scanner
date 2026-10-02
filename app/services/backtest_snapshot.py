"""Materialize immutable price and membership copies for historical replay."""

from collections.abc import Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.orm import Session

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetMembership, BacktestDatasetPrice
from app.models.daily_price import DailyPrice
from app.models.data_quality import PriceObservation
from app.models.listing_event import ListingEvent
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingHistoryRepository
from app.services.historical_universe import HistoricalUniverseRequest, build_historical_universe


_MODES = frozenset({"historical_reconstructed", "as_known_at"})


@dataclass(frozen=True)
class BacktestDatasetRequest:
    start: date
    end: date
    markets: tuple[str, ...]
    adjustment_policy: str
    policy_version: str
    preparation_start: date | None = None
    reconstruction_mode: str = "historical_reconstructed"
    as_known_at: datetime | None = None
    retention_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("end must not be earlier than start")
        if not self.markets:
            raise ValueError("at least one market is required")
        if self.preparation_start is not None and self.preparation_start > self.start:
            raise ValueError("preparation_start must not be after start")
        if self.reconstruction_mode not in _MODES:
            raise ValueError("unsupported reconstruction_mode")
        if self.reconstruction_mode == "as_known_at" and self.as_known_at is None:
            raise ValueError("as_known_at mode requires as_known_at")
        if self.reconstruction_mode != "as_known_at" and self.as_known_at is not None:
            raise ValueError("as_known_at is only valid for as_known_at mode")


def create_backtest_dataset(session: Session, request: BacktestDatasetRequest) -> BacktestDataset:
    """Freeze values and evidence; later canonical upserts cannot alter this dataset."""
    universe = build_historical_universe(
        session,
        HistoricalUniverseRequest(start=request.start, end=request.end, markets=request.markets),
        as_known_at=request.as_known_at,
    )
    instrument_ids = sorted({entry.instrument_id for entry in universe.entries})
    revisions = ListingHistoryRepository(session).list_current_for_instruments(
        instrument_ids, as_known_at=request.as_known_at
    )
    revision_hashes = _revision_hashes(revisions)
    price_row_count, price_snapshot_hash = _price_summary(
        _iter_price_rows(session, request, instrument_ids)
    )
    manifest = _manifest(
        request,
        universe=universe,
        revisions=revisions,
        price_row_count=price_row_count,
        price_snapshot_hash=price_snapshot_hash,
    )
    manifest_hash = _hash(manifest)
    existing = session.scalar(select(BacktestDataset).where(BacktestDataset.manifest_hash == manifest_hash))
    if existing is not None:
        return existing

    dataset = BacktestDataset(
        dataset_id=f"backtest-{manifest_hash[:24]}", manifest_hash=manifest_hash,
        range_start=request.start, range_end=request.end, markets=list(request.markets),
        reconstruction_mode=request.reconstruction_mode, as_known_at=request.as_known_at,
        adjustment_policy=request.adjustment_policy, policy_version=request.policy_version,
        preparation_start=request.preparation_start, manifest=manifest,
        retention_until=request.retention_until,
    )
    session.add(dataset)
    session.flush()
    _insert_dataset_memberships(session, dataset=dataset, entries=universe.entries, revision_hashes=revision_hashes)
    _insert_dataset_prices(session, dataset=dataset, rows=_iter_price_rows(session, request, instrument_ids))
    _finalize_manifest(session, dataset=dataset, manifest=manifest)
    return dataset


def get_backtest_dataset(session: Session, dataset_id: str, *, now: datetime | None = None) -> BacktestDataset | None:
    """Return an active dataset; expiry changes availability, never its copied rows."""
    dataset = session.scalar(select(BacktestDataset).where(BacktestDataset.dataset_id == dataset_id))
    if dataset is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dataset.retention_until is not None and dataset.retention_until <= now and dataset.status != "expired":
        dataset.status = "expired"
        dataset.expired_at = now
        session.flush()
    return dataset if dataset.status == "active" else None


def _price_rows(session: Session, request: BacktestDatasetRequest, instrument_ids: list[int]) -> list[dict]:
    if not instrument_ids:
        return []
    start = request.preparation_start or request.start
    if request.reconstruction_mode == "as_known_at":
        observations = list(session.execute(
            select(PriceObservation, Symbol)
            .join(Symbol, Symbol.id == PriceObservation.symbol_id)
            .where(
                Symbol.instrument_id.in_(instrument_ids),
                PriceObservation.trade_date >= start,
                PriceObservation.trade_date <= request.end,
                PriceObservation.observed_at <= request.as_known_at,
            )
            .order_by(PriceObservation.observed_at, PriceObservation.id)
        ).all())
        latest: dict[tuple[int, date], tuple[PriceObservation, Symbol]] = {}
        for observation, symbol in observations:
            latest[(symbol.id, observation.trade_date)] = (observation, symbol)
        return [_observation_row(observation, symbol) for observation, symbol in latest.values()]
    rows = list(session.execute(
        select(DailyPrice, Symbol)
        .join(Symbol, Symbol.id == DailyPrice.symbol_id)
        .where(
            Symbol.instrument_id.in_(instrument_ids),
            DailyPrice.trade_date >= start,
            DailyPrice.trade_date <= request.end,
        )
        .order_by(DailyPrice.trade_date, Symbol.code, DailyPrice.id)
    ).all())
    return [_canonical_row(price, symbol) for price, symbol in rows]


def _iter_price_rows(
    session: Session, request: BacktestDatasetRequest, instrument_ids: list[int]
) -> Iterator[dict]:
    """Yield immutable price material in bounded batches for large datasets."""
    if request.reconstruction_mode == "as_known_at":
        yield from _price_rows(session, request, instrument_ids)
        return
    if not instrument_ids:
        return
    start = request.preparation_start or request.start
    statement = (
        select(DailyPrice, Symbol)
        .join(Symbol, Symbol.id == DailyPrice.symbol_id)
        .where(
            Symbol.instrument_id.in_(instrument_ids),
            DailyPrice.trade_date >= start,
            DailyPrice.trade_date <= request.end,
        )
        .order_by(DailyPrice.trade_date, Symbol.code, DailyPrice.id)
    )
    for price, symbol in session.execute(statement).yield_per(10_000):
        yield _canonical_row(price, symbol)


def _canonical_row(price: DailyPrice, symbol: Symbol) -> dict:
    return {
        "instrument_id": symbol.instrument_id, "source_symbol_id": symbol.id, "source_observation_id": None,
        "code": symbol.code, "name": symbol.name, "market": symbol.market, "trade_date": price.trade_date,
        "open": price.open, "high": price.high, "low": price.low, "close": price.close,
        "volume": price.volume, "change_rate": price.change_rate, "provider": price.source,
        "adjustment_type": None, "source_payload_hash": None,
    }


def _observation_row(observation: PriceObservation, symbol: Symbol) -> dict:
    return {
        "instrument_id": symbol.instrument_id, "source_symbol_id": symbol.id, "source_observation_id": observation.id,
        "code": symbol.code, "name": symbol.name, "market": symbol.market, "trade_date": observation.trade_date,
        "open": observation.open, "high": observation.high, "low": observation.low, "close": observation.close,
        "volume": observation.volume, "change_rate": observation.change_rate, "provider": observation.provider,
        "adjustment_type": observation.adjustment_type, "source_payload_hash": observation.payload_hash,
    }


def _price_summary(rows: Iterable[dict]) -> tuple[int, str]:
    """Return a deterministic lineage digest without retaining every row."""
    digest = sha256()
    digest.update(b"[")
    count = 0
    for row in rows:
        if count:
            digest.update(b",")
        digest.update(json.dumps(_price_lineage_row(row), sort_keys=True, separators=(",", ":")).encode())
        count += 1
    digest.update(b"]")
    return count, digest.hexdigest()


def _insert_dataset_prices(session: Session, *, dataset: BacktestDataset, rows: Iterable[dict]) -> None:
    batch: list[dict] = []
    for row in rows:
        batch.append({"backtest_dataset_id": dataset.id, **row})
        if len(batch) == 10_000:
            session.execute(insert(BacktestDatasetPrice), batch)
            batch.clear()
    if batch:
        session.execute(insert(BacktestDatasetPrice), batch)


def _insert_dataset_memberships(session: Session, *, dataset: BacktestDataset, entries, revision_hashes: dict[int, list[str]]) -> None:
    batch: list[dict] = []
    for entry in entries:
        batch.append({
            "backtest_dataset_id": dataset.id,
            "instrument_id": entry.instrument_id,
            "trade_date": entry.trade_date,
            "market": entry.market,
            "security_type": entry.security_type,
            "membership_evidence_state": entry.membership_evidence_state,
            "trading_status": entry.trading_status,
            "price_expectation": entry.price_expectation,
            "event_revision_hashes": revision_hashes.get(entry.instrument_id, []),
        })
        if len(batch) == 10_000:
            session.execute(insert(BacktestDatasetMembership), batch)
            batch.clear()
    if batch:
        session.execute(insert(BacktestDatasetMembership), batch)


def _finalize_manifest(session: Session, *, dataset: BacktestDataset, manifest: dict) -> None:
    # The membership/price join is several million rows in production.  Avoid
    # PostgreSQL parallel hash workers exhausting the container's small
    # /dev/shm allocation; the indexed serial plan is deterministic as well.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
    observed_expected = session.scalar(
        select(func.count())
        .select_from(BacktestDatasetMembership)
        .join(
            BacktestDatasetPrice,
            and_(
                BacktestDatasetPrice.backtest_dataset_id == BacktestDatasetMembership.backtest_dataset_id,
                BacktestDatasetPrice.instrument_id == BacktestDatasetMembership.instrument_id,
                BacktestDatasetPrice.trade_date == BacktestDatasetMembership.trade_date,
            ),
        )
        .where(
            BacktestDatasetMembership.backtest_dataset_id == dataset.id,
            BacktestDatasetMembership.price_expectation == "expected",
        )
    )
    final_manifest = deepcopy(manifest)
    final_manifest["coverage"]["observed_expected_price_count"] = observed_expected
    if dataset.reconstruction_mode == "as_known_at":
        final_manifest["replay_capability"]["as_known_at"] = (
            "available"
            if observed_expected == final_manifest["coverage"]["expected_price_count"]
            else "partial"
        )
    dataset.manifest = final_manifest
    dataset.final_manifest_hash = _hash(final_manifest)
    session.flush()


def _manifest(
    request: BacktestDatasetRequest,
    *,
    universe,
    revisions: list[ListingEvent],
    price_row_count: int,
    price_snapshot_hash: str,
) -> dict:
    membership_revisions = [
        {
            "instrument_id": row.instrument_id, "source": row.source, "source_record_key": row.source_record_key,
            "content_hash": row.content_hash, "imported_at": row.imported_at.isoformat(),
        }
        for row in revisions
    ]
    return {
        "version": "backtest-dataset-v1",
        "range": {"start": request.start.isoformat(), "end": request.end.isoformat()},
        "markets": list(request.markets), "adjustment_policy": request.adjustment_policy,
        "policy_version": request.policy_version,
        "preparation_start": request.preparation_start.isoformat() if request.preparation_start else None,
        "reconstruction_mode": request.reconstruction_mode,
        "as_known_at": request.as_known_at.isoformat() if request.as_known_at else None,
        "membership_revisions": membership_revisions,
        "coverage": {
            "membership_completeness": universe.membership_completeness,
            "expected_price_count": universe.expected_price_count,
            "price_row_count": price_row_count,
            "observed_expected_price_count": None,
        },
        "watermark": {
            "price_snapshot_hash": price_snapshot_hash,
            "membership_revision_hash": _hash(membership_revisions),
        },
        "replay_capability": {
            "historical_reconstructed": "available",
            "as_known_at": "partial" if request.reconstruction_mode == "as_known_at" else "not_requested",
        },
        "retention": {
            "retention_until": request.retention_until.isoformat() if request.retention_until else None,
            "expiry_behavior": "dataset becomes unavailable without mutating copied rows",
        },
    }


def _price_lineage_row(row: dict) -> dict:
    return {
        "instrument_id": row["instrument_id"], "source_symbol_id": row["source_symbol_id"],
        "trade_date": row["trade_date"].isoformat(), "provider": row["provider"],
        "adjustment_type": row["adjustment_type"], "source_payload_hash": row["source_payload_hash"],
        "values": [str(row[field]) for field in ("open", "high", "low", "close", "volume", "change_rate")],
    }


def _revision_hashes(revisions: list[ListingEvent]) -> dict[int, list[str]]:
    values: dict[int, list[str]] = {}
    for revision in revisions:
        values.setdefault(revision.instrument_id, []).append(revision.content_hash)
    return values


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value)!r}")
