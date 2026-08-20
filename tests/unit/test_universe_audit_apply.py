from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.base import Base
import app.models  # noqa: F401
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.universe_audit_repository import UniverseAuditRepository
from app.services.universe_audit import AuditSymbol, build_universe_audit_report
from scripts.apply_universe_audit import apply_run, approve_decision


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _create_report(snapshot_id: int):
    return build_universe_audit_report(
        symbols=[
            AuditSymbol(
                code="0005A0",
                name="정상 ETF",
                market="KOSPI",
                symbol_type="etf",
                is_active=True,
                last_snapshot_id=snapshot_id,
            ),
            AuditSymbol(
                code="0005",
                name="정상 ETF",
                market="KOSPI",
                symbol_type="etf",
                is_active=True,
                last_snapshot_id=snapshot_id - 1,
            ),
        ],
        latest_completed_snapshot_id=snapshot_id,
    )


def _setup(session: Session):
    snapshot = SymbolUniverseSnapshot(
        provider="naver",
        status="completed",
        started_at=datetime(2026, 8, 20),
        finished_at=datetime(2026, 8, 20),
    )
    valid = Symbol(
        code="0005A0",
        name="정상 ETF",
        market="KOSPI",
        symbol_type="etf",
        is_active=True,
        last_snapshot_id=None,
    )
    legacy = Symbol(
        code="0005",
        name="정상 ETF",
        market="KOSPI",
        symbol_type="etf",
        is_active=True,
        last_snapshot_id=None,
    )
    session.add_all([snapshot, valid, legacy])
    session.flush()
    legacy.last_snapshot_id = snapshot.id - 1
    valid.last_snapshot_id = snapshot.id
    session.flush()
    return snapshot, legacy


def test_approved_legacy_deactivation_preserves_audit_trail(session):
    snapshot, legacy = _setup(session)
    repository = UniverseAuditRepository(session)
    run = repository.create_run(
        snapshot_id=snapshot.id,
        report=_create_report(snapshot.id),
        requested_by="operator",
    )

    decision = repository.list_decisions(run.id)[0]
    repository.approve_deactivation(
        decision_id=decision.id,
        approved_by="operator",
    )
    applied = repository.apply_approved_deactivations(
        run_id=run.id,
        applied_by="operator",
    )

    assert applied.applied_count == 1
    assert legacy.is_active is False
    assert legacy.legacy_state == "deactivated"
    assert legacy.legacy_audit_run_id == run.id
    assert "invalid_legacy" in legacy.legacy_reason
    assert repository.list_decisions(run.id)[0].status == "applied"


def test_unapproved_audit_run_cannot_change_active_symbol(session):
    snapshot, legacy = _setup(session)
    repository = UniverseAuditRepository(session)
    run = repository.create_run(
        snapshot_id=snapshot.id,
        report=_create_report(snapshot.id),
        requested_by="operator",
    )

    applied = repository.apply_approved_deactivations(
        run_id=run.id,
        applied_by="operator",
    )

    assert applied.applied_count == 0
    assert legacy.is_active is True
    assert repository.list_decisions(run.id)[0].status == "pending"


def test_approval_and_apply_cli_steps_are_separate(session):
    snapshot, legacy = _setup(session)
    repository = UniverseAuditRepository(session)
    run = repository.create_run(
        snapshot_id=snapshot.id,
        report=_create_report(snapshot.id),
        requested_by="operator",
    )
    decision = repository.list_decisions(run.id)[0]

    approve_decision(session, decision_id=decision.id, approved_by="reviewer")

    assert legacy.is_active is True
    outcome = apply_run(session, run_id=run.id, applied_by="operator")
    assert outcome.applied_count == 1
    assert legacy.is_active is False
