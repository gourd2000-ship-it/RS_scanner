from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.agent_auth as agent_auth
import app.models  # noqa: F401
from app.api.v1.endpoints.codex import router as codex_router
from app.core.base import Base
from app.core.database import get_db_session
from app.models.crawl_analysis import CrawlAnalysisReport, CrawlAnalysisRequest
from app.models.crawl_job import CrawlJob
from app.models.crawl_quality_report import CrawlQualityReport


@pytest.fixture
def codex_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full", started_at=datetime.utcnow(), finished_at=datetime.utcnow(), status="completed")
    session.add(job)
    session.flush()
    quality = CrawlQualityReport(
        crawl_job_id=job.id,
        trade_date=date(2026, 8, 14),
        job_type="daily_full",
        job_status="completed",
        symbols_total=1,
        symbols_succeeded=1,
        symbols_failed=0,
        failure_event_count=0,
        success_rate=1.0,
        coverage_rate=1.0,
        error_distribution={}, repeated_failure_summary={}, anomaly_summary={}, sample_refs={}, source_snapshot={},
        report_hash="a" * 64,
    )
    session.add(quality)
    session.flush()
    request = CrawlAnalysisRequest(
        request_id="analysis-codex-001", idempotency_key="analysis-codex-001", requested_by="operator",
        request_kind="weekly", status="report_ready", period_from=date(2026, 8, 14), period_to=date(2026, 8, 14),
        completed_job_ids=[job.id], error_types=[], markets=[], sample_limit=3, reason="Codex test",
    )
    session.add(request)
    session.flush()
    report = CrawlAnalysisReport(
        request_id=request.id, created_by="sam", analysis_window={}, quality_report_refs=[quality.id], findings=[],
        kiwoom_evidence=[],
        recommendations=[{
            "proposal_id": "proposal-001", "finding_ids": [], "priority": "P0", "risk_level": "low",
            "change_scope": "add a classification test", "target_files": ["tests/unit/test_example.py"],
            "tests": ["pytest -q tests/unit/test_example.py"], "rollback": "revert commit",
        }],
        limitations=[], markdown_body="# report", report_json={"schema_version": 1}, report_hash="b" * 64,
    )
    session.add(report)
    session.commit()

    settings = SimpleNamespace(
        analysis_api_enabled=True,
        agent_service_tokens=(
            "operator-token=analysis:read,analysis:review,codex:request;"
            "codex-token=analysis:read,codex:result"
        ),
        agent_allowed_ips="",
    )
    monkeypatch.setattr(agent_auth, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(codex_router, prefix="/internal/v1/codex-change-requests")
    def override_get_db():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        yield client
    session.close()
    engine.dispose()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_codex_change_requires_user_approval_before_result(codex_client):
    created = codex_client.post(
        "/internal/v1/codex-change-requests",
        headers=auth("operator-token"),
        json={"change_request_id": "codex-001", "report_id": 1, "proposal_id": "proposal-001"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "proposed"

    blocked = codex_client.post(
        "/internal/v1/codex-change-requests/codex-001/result",
        headers=auth("codex-token"),
        json={"status": "verified", "test_results": {"passed": 1}},
    )
    assert blocked.status_code == 409

    approved = codex_client.post(
        "/internal/v1/codex-change-requests/codex-001/review",
        headers=auth("operator-token"),
        json={"action": "approved", "reviewed_by": "operator"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    verified = codex_client.post(
        "/internal/v1/codex-change-requests/codex-001/result",
        headers=auth("codex-token"),
        json={"status": "verified", "codex_run_id": "run-1", "test_results": {"passed": 1}},
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"

    implemented = codex_client.post(
        "/internal/v1/codex-change-requests/codex-001/review",
        headers=auth("operator-token"),
        json={"action": "implemented", "reviewed_by": "operator"},
    )
    assert implemented.status_code == 200
    assert implemented.json()["status"] == "implemented"
