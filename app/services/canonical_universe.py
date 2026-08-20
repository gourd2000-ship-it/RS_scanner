"""Materialize completed KRX observations into canonical identity records."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument, ProviderSymbol
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.services.universe_reconciliation import run_universe_reconciliation


@dataclass(frozen=True)
class CanonicalUniverseMaterialization:
    krx_snapshot_id: int
    naver_snapshot_id: int
    instrument_count: int
    exact_mapping_count: int
    reconciliation_run_id: int


def materialize_completed_universe(
    session: Session,
    *,
    krx_snapshot_id: int,
    naver_snapshot_id: int,
    provider: str,
) -> CanonicalUniverseMaterialization:
    """Persist KRX identities and only unambiguous Naver mappings.

    A matching display name is deliberately insufficient.  The legacy Symbol
    row remains untouched unless its code, market, and security type exactly
    agree with the completed KRX membership observation.
    """
    krx_snapshot = session.get(KrxUniverseSnapshot, krx_snapshot_id)
    naver_snapshot = session.get(SymbolUniverseSnapshot, naver_snapshot_id)
    if krx_snapshot is None or krx_snapshot.status != "completed":
        raise ValueError(f"completed KRX snapshot을 찾을 수 없습니다: {krx_snapshot_id}")
    if naver_snapshot is None or naver_snapshot.status != "completed":
        raise ValueError(f"completed Naver snapshot을 찾을 수 없습니다: {naver_snapshot_id}")

    members = list(
        session.scalars(
            select(KrxUniverseMembership)
            .where(KrxUniverseMembership.snapshot_id == krx_snapshot_id)
            .order_by(KrxUniverseMembership.code)
        )
    )
    instruments = _upsert_instruments(session, members)
    naver_by_code = {
        symbol.code: symbol
        for symbol in session.scalars(
            select(Symbol).where(Symbol.last_snapshot_id == naver_snapshot_id)
        )
    }
    exact_mapping_count = _materialize_exact_mappings(
        session,
        members=members,
        instruments=instruments,
        naver_by_code=naver_by_code,
        provider=provider,
        evidence_snapshot_id=krx_snapshot_id,
    )
    reconciliation_run = run_universe_reconciliation(
        session,
        krx_snapshot_id=krx_snapshot_id,
        naver_snapshot_id=naver_snapshot_id,
    )
    session.flush()
    return CanonicalUniverseMaterialization(
        krx_snapshot_id=krx_snapshot_id,
        naver_snapshot_id=naver_snapshot_id,
        instrument_count=len(instruments),
        exact_mapping_count=exact_mapping_count,
        reconciliation_run_id=reconciliation_run.id,
    )


def _upsert_instruments(
    session: Session,
    members: list[KrxUniverseMembership],
) -> dict[str, Instrument]:
    codes = [member.code for member in members]
    by_code = {
        instrument.krx_short_code: instrument
        for instrument in session.scalars(
            select(Instrument).where(Instrument.krx_short_code.in_(codes))
        )
    }
    for member in members:
        instrument = by_code.get(member.code)
        if instrument is None:
            instrument = Instrument(
                krx_short_code=member.code,
                isin=member.isin,
                name=member.name,
                market=member.market,
                security_type=member.security_type,
                listed_at=member.listed_at,
                listing_status=_canonical_listing_status(member.listing_status),
            )
            session.add(instrument)
            by_code[member.code] = instrument
            continue
        instrument.isin = member.isin or instrument.isin
        instrument.name = member.name
        instrument.market = member.market
        instrument.security_type = member.security_type
        instrument.listed_at = member.listed_at or instrument.listed_at
        instrument.listing_status = _canonical_listing_status(member.listing_status)
    session.flush()
    return by_code


def _materialize_exact_mappings(
    session: Session,
    *,
    members: list[KrxUniverseMembership],
    instruments: dict[str, Instrument],
    naver_by_code: dict[str, Symbol],
    provider: str,
    evidence_snapshot_id: int,
) -> int:
    instrument_ids = [instrument.id for instrument in instruments.values()]
    existing_pairs = {
        (row.instrument_id, row.provider_symbol)
        for row in session.scalars(
            select(ProviderSymbol).where(
                ProviderSymbol.instrument_id.in_(instrument_ids),
                ProviderSymbol.provider == provider,
                ProviderSymbol.mapping_status == "matched",
            )
        )
    }
    matched = 0
    for member in members:
        symbol = naver_by_code.get(member.code)
        if symbol is None or symbol.market != member.market or symbol.symbol_type != member.security_type:
            continue
        instrument = instruments[member.code]
        symbol.instrument_id = instrument.id
        pair = (instrument.id, symbol.code)
        if pair not in existing_pairs:
            session.add(
                ProviderSymbol(
                    instrument_id=instrument.id,
                    provider=provider,
                    provider_symbol=symbol.code,
                    mapping_status="matched",
                    evidence_snapshot_id=evidence_snapshot_id,
                )
            )
            existing_pairs.add(pair)
        matched += 1
    return matched


def _canonical_listing_status(observed_status: str) -> str:
    return "listed" if observed_status == "listed_observed" else observed_status
