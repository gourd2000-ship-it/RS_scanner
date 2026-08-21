"""Record human KRX canary decisions from immutable batch evidence."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.batch_checkpoint import BatchCheckpoint
from app.models.krx_universe import KrxUniverseSnapshot
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.models.universe_canary_decision import UniverseCanaryDecision
from app.models.universe_reconciliation import UniverseReconciliationRun

_DECISIONS = {"continue", "expand", "rollback"}


def record_canary_decision(
    session: Session,
    *,
    crawl_job_id: int,
    market: str,
    operator_decision: str,
    approved_by: str,
    notes: str | None = None,
) -> UniverseCanaryDecision:
    """Persist a once-per-market/trading-day operator decision.

    Evidence values come only from the completed price checkpoint and the
    snapshots created by the specified job; callers cannot supply them.
    """
    normalized_market = market.strip().upper()
    normalized_decision = operator_decision.strip().lower()
    reviewer = approved_by.strip()
    if normalized_decision not in _DECISIONS:
        raise ValueError("operator_decision은 continue, expand, rollback 중 하나여야 합니다")
    if not reviewer:
        raise ValueError("approved_by는 비어 있을 수 없습니다")

    metadata = _price_selection_metadata(session, crawl_job_id)
    authority = _market_value(metadata, "authority_by_market", normalized_market)
    fallback_reason = _market_value(metadata, "fallback_reason_by_market", normalized_market)
    target_count = _market_value(metadata, "target_count_by_market", normalized_market)
    if not isinstance(authority, str) or not isinstance(target_count, int):
        raise ValueError(f"job {crawl_job_id}에 {normalized_market} 가격 target 결정이 없습니다")

    observed_snapshot = session.scalar(
        select(KrxUniverseSnapshot)
        .where(KrxUniverseSnapshot.crawl_job_id == crawl_job_id)
        .order_by(KrxUniverseSnapshot.id.desc())
        .limit(1)
    )
    if observed_snapshot is None or observed_snapshot.status != "completed":
        raise ValueError("completed KRX snapshot이 없는 job은 canary decision을 기록할 수 없습니다")

    naver_snapshot = session.scalar(
        select(SymbolUniverseSnapshot)
        .where(SymbolUniverseSnapshot.job_id == crawl_job_id)
        .order_by(SymbolUniverseSnapshot.id.desc())
        .limit(1)
    )
    if naver_snapshot is None or naver_snapshot.status != "completed":
        raise ValueError("completed Naver snapshot이 없는 job은 canary decision을 기록할 수 없습니다")

    observed_run = session.scalar(
        select(UniverseReconciliationRun).where(
            UniverseReconciliationRun.krx_snapshot_id == observed_snapshot.id,
            UniverseReconciliationRun.naver_snapshot_id == naver_snapshot.id,
        )
    )
    selected_run_id = metadata.get("approved_reconciliation_run_id")
    selected_snapshot_id = metadata.get("approved_krx_snapshot_id")
    selected_run = session.get(UniverseReconciliationRun, selected_run_id) if selected_run_id else None
    mapping_rate = _mapping_rate(observed_run)
    if authority == "krx":
        if observed_run is None or observed_run.status != "approved":
            raise ValueError("KRX canary decision에는 현재 reconciliation run의 운영자 승인이 필요합니다")
        if selected_run is None or selected_run.status != "approved":
            raise ValueError("KRX canary decision에는 승인된 immutable reconciliation run이 필요합니다")
        if selected_run.krx_snapshot_id != selected_snapshot_id:
            raise ValueError("immutable reconciliation snapshot 증거가 일치하지 않습니다")
        threshold = get_settings().universe_mapping_rate_threshold
        if mapping_rate is None or mapping_rate < threshold:
            raise ValueError(
                f"KRX canary decision에는 현재 매핑률 {threshold:.3f} 이상이 필요합니다"
            )
    if normalized_decision == "expand":
        prior_continue_count = session.scalar(
            select(func.count())
            .select_from(UniverseCanaryDecision)
            .where(
                UniverseCanaryDecision.market == normalized_market,
                UniverseCanaryDecision.authority == "krx",
                UniverseCanaryDecision.operator_decision == "continue",
            )
        ) or 0
        if prior_continue_count < 2:
            raise ValueError("expand 전에는 같은 시장에서 두 거래일의 continue decision이 필요합니다")

    existing = session.scalar(
        select(UniverseCanaryDecision).where(
            UniverseCanaryDecision.trade_date == observed_snapshot.as_of_date,
            UniverseCanaryDecision.market == normalized_market,
        )
    )
    if existing is not None:
        raise ValueError(
            f"{observed_snapshot.as_of_date} {normalized_market} canary decision은 이미 기록되었습니다"
        )

    decision = UniverseCanaryDecision(
        crawl_job_id=crawl_job_id,
        trade_date=observed_snapshot.as_of_date,
        market=normalized_market,
        krx_snapshot_id=observed_snapshot.id,
        reconciliation_run_id=observed_run.id if observed_run is not None else None,
        selected_reconciliation_run_id=selected_run.id if selected_run is not None else None,
        authority=authority,
        fallback_reason=fallback_reason if isinstance(fallback_reason, str) else None,
        mapping_rate=mapping_rate,
        target_count=target_count,
        operator_decision=normalized_decision,
        approved_by=reviewer,
        notes=notes.strip() if notes and notes.strip() else None,
    )
    session.add(decision)
    session.flush()
    return decision


def _price_selection_metadata(session: Session, crawl_job_id: int) -> dict:
    checkpoint = session.scalar(
        select(BatchCheckpoint).where(
            BatchCheckpoint.job_id == crawl_job_id,
            BatchCheckpoint.step_name == "prices",
        )
    )
    if checkpoint is None or not checkpoint.step_metadata:
        raise ValueError(f"job {crawl_job_id}에 가격 단계 metadata가 없습니다")
    try:
        metadata = json.loads(checkpoint.step_metadata)
    except json.JSONDecodeError as exc:
        raise ValueError(f"job {crawl_job_id} 가격 단계 metadata가 올바른 JSON이 아닙니다") from exc
    selection = metadata.get("universe_selection")
    if not isinstance(selection, dict):
        raise ValueError(f"job {crawl_job_id}에 universe selection metadata가 없습니다")
    return selection


def _market_value(metadata: dict, key: str, market: str):
    values = metadata.get(key)
    return values.get(market) if isinstance(values, dict) else None


def _mapping_rate(run: UniverseReconciliationRun | None) -> float | None:
    if run is None:
        return None
    value = (run.report or {}).get("mapping_rate")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
