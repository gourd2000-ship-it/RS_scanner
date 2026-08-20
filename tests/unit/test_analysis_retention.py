from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.base import Base
from app.models.codex_change_request import CodexChangeRequest
from app.models.crawl_analysis import CrawlAnalysisReport, CrawlAnalysisRequest
from app.services.analysis.retention import (
    expired_terminal_analysis_request_ids,
    prune_terminal_analysis_requests,
)


def _request(*, request_id: str, status: str, created_at: datetime) -> CrawlAnalysisRequest:
    return CrawlAnalysisRequest(
        request_id=request_id,
        idempotency_key=request_id,
        requested_by="operator",
        request_kind="weekly",
        status=status,
        period_from=date(2025, 8, 1),
        period_to=date(2025, 8, 7),
        completed_job_ids=[1],
        error_types=[],
        markets=[],
        sample_limit=3,
        reason="retention test",
        created_at=created_at,
        updated_at=created_at,
    )


def test_retention_only_prunes_terminal_requests_and_their_audit_rows():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    old_terminal = _request(
        request_id="analysis-old-terminal",
        status="implemented",
        created_at=datetime(2025, 8, 1),
    )
    old_active = _request(
        request_id="analysis-old-active",
        status="report_ready",
        created_at=datetime(2025, 8, 1),
    )
    recent_terminal = _request(
        request_id="analysis-recent-terminal",
        status="deferred",
        created_at=datetime(2026, 8, 1),
    )
    session.add_all([old_terminal, old_active, recent_terminal])
    session.flush()
    report = CrawlAnalysisReport(
        request_id=old_terminal.id,
        created_by="sam",
        analysis_window={},
        quality_report_refs=[],
        findings=[],
        kiwoom_evidence=[],
        recommendations=[],
        limitations=["retention test"],
        markdown_body="# report",
        report_json={"schema_version": 1},
        report_hash="d" * 64,
        created_at=datetime(2025, 8, 1),
    )
    session.add(report)
    session.flush()
    session.add(
        CodexChangeRequest(
            change_request_id="codex-old-terminal",
            report_id=report.id,
            proposal_id="proposal-001",
            status="implemented",
            requested_by="operator",
            target_files=["app/example.py"],
            change_scope="retention test",
            risk_level="low",
            verification_plan=["pytest"],
            test_results={},
            created_at=datetime(2025, 8, 1),
            updated_at=datetime(2025, 8, 1),
        )
    )
    session.commit()
    old_terminal_id = old_terminal.id
    old_active_id = old_active.id
    recent_terminal_id = recent_terminal.id
    report_id = report.id

    ids = expired_terminal_analysis_request_ids(session, before=datetime(2025, 8, 15))
    assert ids == [old_terminal_id]
    assert prune_terminal_analysis_requests(session, request_ids=ids) == 1
    session.commit()

    assert session.get(CrawlAnalysisRequest, old_terminal_id) is None
    assert session.get(CrawlAnalysisReport, report_id) is None
    assert session.query(CodexChangeRequest).count() == 0
    assert session.get(CrawlAnalysisRequest, old_active_id) is not None
    assert session.get(CrawlAnalysisRequest, recent_terminal_id) is not None
    session.close()
    engine.dispose()
