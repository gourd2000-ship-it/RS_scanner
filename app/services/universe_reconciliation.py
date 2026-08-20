"""Conservative KRX-to-Naver mapping candidate generation."""

from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.universe_reconciliation_repository import UniverseReconciliationRepository


_VALID_CODE = re.compile(r"[0-9A-Za-z]{6}")


@dataclass(frozen=True)
class KRXMemberCandidate:
    code: str
    isin: str | None
    name: str
    market: str
    security_type: str


@dataclass(frozen=True)
class NaverSymbolCandidate:
    code: str
    isin: str | None
    name: str
    market: str
    security_type: str


@dataclass(frozen=True)
class MappingResult:
    status: str
    match_method: str | None = None
    candidate_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingResultWithCode:
    krx_code: str
    status: str
    match_method: str | None = None
    candidate_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationResult:
    krx_results: tuple[MappingResultWithCode, ...]
    naver_results: dict[str, MappingResult]


def reconcile_universe_candidates(
    *,
    krx_members: list[KRXMemberCandidate],
    naver_symbols: list[NaverSymbolCandidate],
) -> ReconciliationResult:
    """Generate evidence-only matches; normalized names never auto-match."""
    naver_by_code = {row.code: row for row in naver_symbols}
    consumed_naver_codes: set[str] = set()
    krx_results: list[MappingResultWithCode] = []

    for member in krx_members:
        exact = naver_by_code.get(member.code)
        if exact is not None and _same_market_type(member, exact):
            consumed_naver_codes.add(exact.code)
            krx_results.append(MappingResultWithCode(member.code, "matched", "exact_code"))
            continue

        isin_matches = [
            symbol
            for symbol in naver_symbols
            if member.isin and symbol.isin == member.isin and _same_market_type(member, symbol)
        ]
        if len(isin_matches) == 1:
            consumed_naver_codes.add(isin_matches[0].code)
            krx_results.append(MappingResultWithCode(member.code, "matched", "isin"))
            continue

        name_matches = [
            symbol.code
            for symbol in naver_symbols
            if _same_market_type(member, symbol)
            and _normalized_name(member.name) == _normalized_name(symbol.name)
            # A strict prefix is a legacy-correction proposal, not a name-only
            # ambiguity.  It is reported separately below and never applied.
            and not member.code.startswith(symbol.code)
        ]
        if name_matches:
            krx_results.append(
                MappingResultWithCode(
                    member.code,
                    "ambiguous",
                    candidate_codes=tuple(sorted(name_matches)),
                )
            )
        else:
            krx_results.append(MappingResultWithCode(member.code, "unmatched"))

    unmatched_krx = {
        row.krx_code: member
        for row, member in zip(krx_results, krx_members, strict=True)
        if row.status == "unmatched"
    }
    naver_results: dict[str, MappingResult] = {}
    for symbol in naver_symbols:
        if symbol.code in consumed_naver_codes:
            naver_results[symbol.code] = MappingResult("matched")
        else:
            prefix_matches = tuple(
                sorted(
                    member.code
                    for member in unmatched_krx.values()
                    if member.code.startswith(symbol.code)
                    and _same_market_type(member, symbol)
                    and _normalized_name(member.name) == _normalized_name(symbol.name)
                )
            )
            if prefix_matches:
                naver_results[symbol.code] = MappingResult(
                    "legacy_candidate", candidate_codes=prefix_matches
                )
            elif not _VALID_CODE.fullmatch(symbol.code):
                naver_results[symbol.code] = MappingResult("invalid_legacy")
            else:
                naver_results[symbol.code] = MappingResult("unmatched")

    return ReconciliationResult(tuple(krx_results), naver_results)


def run_universe_reconciliation(
    session: Session,
    *,
    krx_snapshot_id: int,
    naver_snapshot_id: int,
):
    """Persist a pending-review reconciliation run for an explicit snapshot pair."""
    krx_snapshot = session.get(KrxUniverseSnapshot, krx_snapshot_id)
    naver_snapshot = session.get(SymbolUniverseSnapshot, naver_snapshot_id)
    if krx_snapshot is None or krx_snapshot.status != "completed":
        raise ValueError(f"completed KRX snapshot을 찾을 수 없습니다: {krx_snapshot_id}")
    if naver_snapshot is None or naver_snapshot.status != "completed":
        raise ValueError(f"completed Naver snapshot을 찾을 수 없습니다: {naver_snapshot_id}")

    result = reconcile_universe_candidates(
        krx_members=[
            KRXMemberCandidate(
                row.code, row.isin, row.name, row.market, row.security_type
            )
            for row in session.scalars(
                select(KrxUniverseMembership).where(
                    KrxUniverseMembership.snapshot_id == krx_snapshot_id
                )
            )
        ],
        naver_symbols=[
            NaverSymbolCandidate(
                row.code, None, row.name, row.market, row.symbol_type
            )
            for row in session.scalars(
                select(Symbol).where(Symbol.last_snapshot_id == naver_snapshot_id)
            )
        ],
    )
    counts = {
        "matched": sum(row.status == "matched" for row in result.krx_results),
        "exact": sum(
            row.status == "matched" and row.match_method == "exact_code"
            for row in result.krx_results
        ),
        "unmatched": sum(row.status == "unmatched" for row in result.krx_results),
        "ambiguous": sum(row.status == "ambiguous" for row in result.krx_results),
        "legacy_candidate": sum(
            row.status == "legacy_candidate" for row in result.naver_results.values()
        ),
        "invalid_legacy": sum(
            row.status == "invalid_legacy" for row in result.naver_results.values()
        ),
    }
    report = {
        "krx_snapshot_id": krx_snapshot_id,
        "naver_snapshot_id": naver_snapshot_id,
        "counts": counts,
        "mapping_rate": counts["matched"] / len(result.krx_results) if result.krx_results else 0.0,
        "krx_results": [
            {
                "code": row.krx_code,
                "status": row.status,
                "match_method": row.match_method,
                "candidate_codes": list(row.candidate_codes),
            }
            for row in result.krx_results
        ],
        "naver_results": {
            code: {
                "status": row.status,
                "candidate_codes": list(row.candidate_codes),
            }
            for code, row in sorted(result.naver_results.items())
        },
    }
    return UniverseReconciliationRepository(session).get_or_create_run(
        krx_snapshot_id=krx_snapshot_id,
        naver_snapshot_id=naver_snapshot_id,
        report=report,
    )


def _same_market_type(left: KRXMemberCandidate, right: NaverSymbolCandidate) -> bool:
    return left.market == right.market and left.security_type == right.security_type


def _normalized_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).upper()
