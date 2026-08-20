"""Read-only reconciliation between the latest KRX and Naver universes."""

from dataclasses import dataclass
import re

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot


_CODE_PATTERN = re.compile(r"[0-9A-Za-z]{6}")


@dataclass(frozen=True)
class UniverseReconciliationReport:
    krx_snapshot_id: int | None
    naver_snapshot_id: int | None
    latest_krx_snapshot_id: int | None
    latest_krx_status: str | None
    counts: dict[str, int]
    mapping_rate: float
    samples: dict[str, list[str]]
    alerts: list[str]


def build_universe_reconciliation_report(
    session: Session,
    *,
    sample_limit: int = 20,
) -> UniverseReconciliationReport:
    """Compare completed snapshots without changing symbol or target state."""
    latest_krx = session.scalar(
        select(KrxUniverseSnapshot)
        .where(KrxUniverseSnapshot.scope == "stock_membership")
        .order_by(desc(KrxUniverseSnapshot.started_at), desc(KrxUniverseSnapshot.id))
        .limit(1)
    )
    completed_krx = session.scalar(
        select(KrxUniverseSnapshot)
        .where(
            KrxUniverseSnapshot.scope == "stock_membership",
            KrxUniverseSnapshot.status == "completed",
        )
        .order_by(desc(KrxUniverseSnapshot.as_of_date), desc(KrxUniverseSnapshot.id))
        .limit(1)
    )
    completed_naver = session.scalar(
        select(SymbolUniverseSnapshot)
        .where(SymbolUniverseSnapshot.status == "completed")
        .order_by(
            desc(SymbolUniverseSnapshot.finished_at),
            desc(SymbolUniverseSnapshot.started_at),
            desc(SymbolUniverseSnapshot.id),
        )
        .limit(1)
    )

    krx_members = (
        list(
            session.scalars(
                select(KrxUniverseMembership).where(
                    KrxUniverseMembership.snapshot_id == completed_krx.id
                )
            )
        )
        if completed_krx is not None
        else []
    )
    naver_symbols = (
        list(
            session.scalars(
                select(Symbol).where(Symbol.last_snapshot_id == completed_naver.id)
            )
        )
        if completed_naver is not None
        else []
    )

    krx_by_code = {member.code: member for member in krx_members}
    naver_by_code = {symbol.code: symbol for symbol in naver_symbols}
    krx_security_types = {member.security_type for member in krx_members}
    samples = {
        "ambiguous": [],
        "unmatched_krx": [],
        "unmatched_naver": [],
        "out_of_scope_naver": [],
        "legacy_candidate": [],
        "invalid_legacy": [],
    }
    exact = 0

    for code, member in krx_by_code.items():
        symbol = naver_by_code.get(code)
        if symbol is None:
            samples["unmatched_krx"].append(code)
        elif symbol.market == member.market and symbol.symbol_type == member.security_type:
            exact += 1
        else:
            samples["ambiguous"].append(code)

    for code, symbol in naver_by_code.items():
        if code in krx_by_code:
            continue
        if symbol.symbol_type not in krx_security_types:
            category = "out_of_scope_naver"
        elif not _CODE_PATTERN.fullmatch(code):
            category = "invalid_legacy"
        elif _is_strict_legacy_candidate(symbol, krx_members):
            category = "legacy_candidate"
        else:
            category = "unmatched_naver"
        samples[category].append(code)

    for codes in samples.values():
        codes.sort()

    counts = {
        "krx_total": len(krx_members),
        "naver_total": len(naver_symbols),
        "exact": exact,
        "ambiguous": len(samples["ambiguous"]),
        "unmatched_krx": len(samples["unmatched_krx"]),
        "unmatched_naver": len(samples["unmatched_naver"]),
        "out_of_scope_naver": len(samples["out_of_scope_naver"]),
        "legacy_candidate": len(samples["legacy_candidate"]),
        "invalid_legacy": len(samples["invalid_legacy"]),
    }
    alerts: list[str] = []
    if completed_krx is None:
        alerts.append("krx_completed_snapshot_missing")
    if completed_naver is None:
        alerts.append("naver_completed_snapshot_missing")
    if latest_krx is not None and latest_krx.status != "completed":
        alerts.append("krx_snapshot_not_completed")

    return UniverseReconciliationReport(
        krx_snapshot_id=completed_krx.id if completed_krx is not None else None,
        naver_snapshot_id=completed_naver.id if completed_naver is not None else None,
        latest_krx_snapshot_id=latest_krx.id if latest_krx is not None else None,
        latest_krx_status=latest_krx.status if latest_krx is not None else None,
        counts=counts,
        mapping_rate=exact / len(krx_members) if krx_members else 0.0,
        samples={key: values[:sample_limit] for key, values in samples.items()},
        alerts=sorted(alerts),
    )


def _is_strict_legacy_candidate(symbol: Symbol, krx_members: list[KrxUniverseMembership]) -> bool:
    """Return true only for evidence-backed strict-prefix legacy candidates."""
    normalized_symbol_name = _normalized_name(symbol.name)
    return any(
        member.code.startswith(symbol.code)
        and member.code != symbol.code
        and member.market == symbol.market
        and member.security_type == symbol.symbol_type
        and _normalized_name(member.name) == normalized_symbol_name
        for member in krx_members
    )


def _normalized_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).upper()
