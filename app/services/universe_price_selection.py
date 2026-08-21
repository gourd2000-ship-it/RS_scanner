"""Select price targets while keeping KRX canaries market-scoped and reversible."""

from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.universe_reconciliation import UniverseReconciliationRun
from app.services.universe_authority import choose_universe_authority
from app.services.universe_target_builder import UniversePriceTarget, build_price_targets


@dataclass(frozen=True)
class UniversePriceSelection:
    target_codes: frozenset[str]
    lineage_by_code: dict[str, UniversePriceTarget]
    authority_by_market: dict[str, str]
    fallback_reason_by_market: dict[str, str | None]
    approved_reconciliation_run_id: int | None
    approved_krx_snapshot_id: int | None
    target_count_by_market: dict[str, int]

    def to_audit_metadata(self) -> dict[str, object]:
        """Return the immutable target-selection decision for batch evidence."""
        return {
            "approved_reconciliation_run_id": self.approved_reconciliation_run_id,
            "approved_krx_snapshot_id": self.approved_krx_snapshot_id,
            "authority_by_market": dict(self.authority_by_market),
            "fallback_reason_by_market": dict(self.fallback_reason_by_market),
            "target_count_by_market": dict(self.target_count_by_market),
        }


def select_price_targets(
    session: Session,
    *,
    provider: str,
    as_of_date,
    naver_snapshot_id: int | None,
    krx_snapshot_status: str | None = None,
    naver_targets: list,
    settings,
) -> UniversePriceSelection:
    """Return a mixed KRX/Naver target set with safe per-market fallback."""
    approved_run = _latest_approved_reconciliation(session)
    target_build = build_price_targets(
        session,
        provider=provider,
        as_of_date=as_of_date,
        krx_snapshot_id=approved_run.krx_snapshot_id if approved_run is not None else None,
    )
    evidence_run = approved_run or _reconciliation_run(
        session,
        krx_snapshot_id=target_build.krx_snapshot_id,
        naver_snapshot_id=naver_snapshot_id,
    )
    mapping_rate, reconciliation_approved = _mapping_evidence(evidence_run)
    naver_by_market: dict[str, list] = {}
    for target in naver_targets:
        naver_by_market.setdefault(target.market, []).append(target)

    eligible_by_market: dict[str, list[UniversePriceTarget]] = {}
    for target in target_build.eligible_targets:
        eligible_by_market.setdefault(target.market, []).append(target)

    target_codes: set[str] = set()
    lineage_by_code: dict[str, UniversePriceTarget] = {}
    authority_by_market: dict[str, str] = {}
    fallback_reason_by_market: dict[str, str | None] = {}
    target_count_by_market: dict[str, int] = {}
    for market, naver_market_targets in sorted(naver_by_market.items()):
        decision = choose_universe_authority(
            settings,
            market=market,
            krx_snapshot_status=(
                krx_snapshot_status
                if krx_snapshot_status is not None
                else ("completed" if target_build.krx_snapshot_id is not None else None)
            ),
            mapping_rate=mapping_rate,
        )
        naver_by_code = {target.code: target for target in naver_market_targets}
        eligible = eligible_by_market.get(market, [])
        if decision.authority == "krx" and not reconciliation_approved:
            decision_authority = "naver_last_completed"
            fallback_reason = "krx_reconciliation_not_approved"
        elif decision.authority == "krx" and not eligible:
            decision_authority = "naver_last_completed"
            fallback_reason = "krx_eligible_targets_missing"
        else:
            decision_authority = decision.authority
            fallback_reason = decision.fallback_reason

        if decision_authority == "krx":
            authoritative_types = {target.security_type for target in eligible}
            for target in eligible:
                symbol = naver_by_code.get(target.provider_symbol or "")
                if symbol is None or symbol.symbol_type != target.security_type:
                    continue
                target_codes.add(symbol.code)
                lineage_by_code[symbol.code] = target
            # ETF/ETN are still KRX shadow observations until their independent
            # membership contract is approved.  A stock-only KRX canary must not
            # silently remove those existing Naver price targets.
            target_codes.update(
                target.code
                for target in naver_market_targets
                if target.symbol_type not in authoritative_types
            )
        else:
            target_codes.update(target.code for target in naver_market_targets)
        authority_by_market[market] = decision_authority
        fallback_reason_by_market[market] = fallback_reason
        target_count_by_market[market] = sum(
            target.code in target_codes for target in naver_market_targets
        )

    return UniversePriceSelection(
        target_codes=frozenset(target_codes),
        lineage_by_code=lineage_by_code,
        authority_by_market=authority_by_market,
        fallback_reason_by_market=fallback_reason_by_market,
        approved_reconciliation_run_id=approved_run.id if approved_run is not None else None,
        approved_krx_snapshot_id=approved_run.krx_snapshot_id if approved_run is not None else None,
        target_count_by_market=target_count_by_market,
    )


def _latest_approved_reconciliation(session: Session) -> UniverseReconciliationRun | None:
    return session.scalar(
        select(UniverseReconciliationRun)
        .where(UniverseReconciliationRun.status == "approved")
        .order_by(desc(UniverseReconciliationRun.decided_at), desc(UniverseReconciliationRun.id))
        .limit(1)
    )


def _reconciliation_run(
    session: Session,
    *,
    krx_snapshot_id: int | None,
    naver_snapshot_id: int | None,
) -> UniverseReconciliationRun | None:
    if krx_snapshot_id is None or naver_snapshot_id is None:
        return None
    return session.scalar(
        select(UniverseReconciliationRun).where(
            UniverseReconciliationRun.krx_snapshot_id == krx_snapshot_id,
            UniverseReconciliationRun.naver_snapshot_id == naver_snapshot_id,
        )
    )


def _mapping_evidence(
    run: UniverseReconciliationRun | None,
) -> tuple[float | None, bool]:
    if run is None:
        return None, False
    value = (run.report or {}).get("mapping_rate")
    try:
        return float(value), run.status == "approved"
    except (TypeError, ValueError):
        return None, False
