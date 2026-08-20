"""Build immutable, explainable price targets from canonical universe state."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument, ProviderSymbol, UniverseExclusion
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot


@dataclass(frozen=True)
class UniversePriceTarget:
    krx_snapshot_id: int
    instrument_id: int | None
    krx_code: str
    provider_symbol: str | None
    market: str
    security_type: str
    price_eligibility: str
    reason_code: str | None


@dataclass(frozen=True)
class UniverseTargetBuild:
    krx_snapshot_id: int | None
    targets: tuple[UniversePriceTarget, ...]

    @property
    def eligible_targets(self) -> tuple[UniversePriceTarget, ...]:
        return tuple(target for target in self.targets if target.price_eligibility == "eligible")


def build_price_targets(
    session: Session,
    *,
    provider: str,
    as_of_date: date,
    krx_snapshot_id: int | None = None,
) -> UniverseTargetBuild:
    """Use a completed KRX snapshot; never select a partial snapshot."""
    if krx_snapshot_id is None:
        snapshot = session.scalar(
            select(KrxUniverseSnapshot)
            .where(
                KrxUniverseSnapshot.scope == "stock_membership",
                KrxUniverseSnapshot.status == "completed",
            )
            .order_by(desc(KrxUniverseSnapshot.as_of_date), desc(KrxUniverseSnapshot.id))
            .limit(1)
        )
    else:
        snapshot = session.get(KrxUniverseSnapshot, krx_snapshot_id)
        if (
            snapshot is not None
            and (snapshot.scope != "stock_membership" or snapshot.status != "completed")
        ):
            snapshot = None
    if snapshot is None:
        return UniverseTargetBuild(krx_snapshot_id=None, targets=())

    members = list(
        session.scalars(
            select(KrxUniverseMembership)
            .where(KrxUniverseMembership.snapshot_id == snapshot.id)
            .order_by(KrxUniverseMembership.code)
        )
    )
    instruments = {
        row.krx_short_code: row
        for row in session.scalars(
            select(Instrument).where(
                Instrument.krx_short_code.in_([member.code for member in members])
            )
        )
    }
    instrument_ids = [row.id for row in instruments.values()]
    mappings = _current_mappings(
        session, provider=provider, instrument_ids=instrument_ids, as_of_date=as_of_date
    )
    exclusions = _current_exclusions(
        session, instrument_ids=instrument_ids, as_of_date=as_of_date
    )
    targets: list[UniversePriceTarget] = []
    for member in members:
        instrument = instruments.get(member.code)
        mapping = mappings.get(instrument.id) if instrument is not None else None
        exclusion = exclusions.get(instrument.id) if instrument is not None else None
        eligibility, reason = _price_eligibility(member, instrument, mapping, exclusion)
        targets.append(
            UniversePriceTarget(
                krx_snapshot_id=snapshot.id,
                instrument_id=instrument.id if instrument is not None else None,
                krx_code=member.code,
                provider_symbol=mapping.provider_symbol if mapping is not None else None,
                market=member.market,
                security_type=member.security_type,
                price_eligibility=eligibility,
                reason_code=reason,
            )
        )
    return UniverseTargetBuild(snapshot.id, tuple(targets))


def _current_mappings(
    session: Session,
    *,
    provider: str,
    instrument_ids: list[int],
    as_of_date: date,
) -> dict[int, ProviderSymbol]:
    if not instrument_ids:
        return {}
    rows = list(
        session.scalars(
            select(ProviderSymbol).where(
                ProviderSymbol.instrument_id.in_(instrument_ids),
                ProviderSymbol.provider == provider,
                ProviderSymbol.mapping_status == "matched",
                (ProviderSymbol.valid_from.is_(None)) | (ProviderSymbol.valid_from <= as_of_date),
                (ProviderSymbol.valid_to.is_(None)) | (ProviderSymbol.valid_to >= as_of_date),
            )
        )
    )
    rows.sort(key=lambda row: (row.instrument_id, row.valid_from or date.min, row.id), reverse=True)
    selected: dict[int, ProviderSymbol] = {}
    for row in rows:
        selected.setdefault(row.instrument_id, row)
    return selected


def _current_exclusions(
    session: Session,
    *,
    instrument_ids: list[int],
    as_of_date: date,
) -> dict[int, UniverseExclusion]:
    if not instrument_ids:
        return {}
    rows = list(
        session.scalars(
            select(UniverseExclusion).where(
                UniverseExclusion.instrument_id.in_(instrument_ids),
                UniverseExclusion.scope == "price",
                (UniverseExclusion.valid_from.is_(None)) | (UniverseExclusion.valid_from <= as_of_date),
                (UniverseExclusion.valid_to.is_(None)) | (UniverseExclusion.valid_to >= as_of_date),
            )
        )
    )
    rows.sort(key=lambda row: (row.instrument_id, row.valid_from or date.min, row.id), reverse=True)
    selected: dict[int, UniverseExclusion] = {}
    for row in rows:
        selected.setdefault(row.instrument_id, row)
    return selected


def _price_eligibility(member, instrument, mapping, exclusion) -> tuple[str, str | None]:
    if instrument is None:
        return "review_required", "instrument_unresolved"
    if instrument.listing_status != "listed":
        return "excluded", f"listing_status_{instrument.listing_status}"
    if exclusion is not None:
        return "excluded", exclusion.reason_code
    if member.trading_status in {"suspended", "halted"}:
        return "expected_no_trade", "trading_halt"
    if mapping is None:
        return "review_required", "provider_symbol_unavailable"
    return "eligible", None
