from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.agent_auth as agent_auth
import app.models  # noqa: F401
from app.api.v1.endpoints.analysis import router as analysis_router
from app.core.base import Base
from app.core.database import get_db_session
from app.models.crawl_job import CrawlJob
from app.models.crawl_quality_report import CrawlQualityReport
from app.models.crawl_target_result import CrawlTargetResult
from app.services.analysis.report_validator import report_content_hash


@pytest.fixture
def analysis_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime(2026, 8, 15, 9, 0, 0)
    for offset in range(7):
        job = CrawlJob(
            job_type="daily_full",
            started_at=now - timedelta(days=offset, hours=1),
            finished_at=now - timedelta(days=offset),
            status="completed_with_errors",
            symbols_total=10,
            symbols_succeeded=8,
            symbols_failed=2,
        )
        session.add(job)
        session.flush()
        session.add(
            CrawlQualityReport(
                crawl_job_id=job.id,
                trade_date=date(2026, 8, 14) - timedelta(days=offset),
                job_type="daily_full",
                job_status="completed_with_errors",
                symbols_total=10,
                symbols_succeeded=8,
                symbols_failed=2,
                failure_event_count=2,
                success_rate=0.8,
                coverage_rate=0.8,
                error_distribution={"invalid_ohlc": {"events": 2, "symbols": 2}},
                repeated_failure_summary={"window_job_ids": [], "items": []},
                anomaly_summary={},
                sample_refs={},
                source_snapshot={},
                report_hash=f"{offset:064x}",
            )
        )
    session.add(
        CrawlTargetResult(
            job_id=1,
            step_name="prices",
            target_key="005930",
            status="failed",
            provider="naver",
            rows_received=0,
            rows_persisted=0,
            error_class="ValidationError",
            error_message="OHLC fields must be positive",
        )
    )
    session.add(
        CrawlTargetResult(
            job_id=1,
            step_name="prices",
            target_key="000660",
            status="fetched",
            provider="naver",
            rows_received=1,
            rows_persisted=1,
        )
    )
    session.commit()

    settings = SimpleNamespace(
        analysis_api_enabled=True,
        agent_service_tokens=(
            "operator-token=analysis:request,analysis:read,analysis:review;"
            "sam-token=analysis:read,analysis:accept,analysis:submit"
        ),
        agent_allowed_ips="",
    )
    monkeypatch.setattr(agent_auth, "get_settings", lambda: settings)

    test_app = FastAPI()
    test_app.include_router(analysis_router, prefix="/internal/v1/crawl-analysis")

    def override_get_db():
        yield session

    test_app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(test_app) as client:
        yield client, session
    session.close()
    engine.dispose()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_weekly_request_accept_and_report_submission_round_trip(analysis_client):
    client, _session = analysis_client
    create = client.post(
        "/internal/v1/crawl-analysis/requests",
        headers=auth("operator-token"),
        json={
            "request_id": "analysis-20260815-weekly-001",
            "idempotency_key": "weekly-2026-08-08-2026-08-14",
            "request_kind": "weekly",
            "reason": "최근 반복 오류 분석",
        },
    )
    assert create.status_code == 201
    requested = create.json()
    assert requested["status"] == "requested"
    assert len(requested["completed_job_ids"]) == 7
    assert len(requested["quality_report_ids"]) == 7

    accepted = client.post(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-001/accept",
        headers=auth("sam-token"),
        json={"accepted_by": "sam"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    report_json = {
        "schema_version": 1,
        "request_id": "analysis-20260815-weekly-001",
        "findings": [
            {
                "finding_id": "finding-001",
                "error_type": "invalid_ohlc",
                "severity": "high",
                "observed_count": 2,
                "sample_refs": ["failure-1"],
                "evidence_refs": [],
                "root_cause_hypothesis": "validation classification is too coarse",
                "confidence": "medium",
            }
        ],
        "kiwoom_evidence": [],
        "recommendations": [
            {
                "proposal_id": "proposal-001",
                "finding_ids": ["finding-001"],
                "priority": "P0",
                "risk_level": "medium",
                "change_scope": "classify empty rows",
                "target_files": ["app/services/batch/sync_prices.py"],
                "tests": ["classification test"],
                "rollback": "feature flag off",
                "evidence_refs": [],
            }
        ],
        "limitations": [],
    }
    markdown = "# 분석 결론\n분류 개선이 필요합니다."
    preview = client.post(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-001/report-hash",
        headers=auth("sam-token"),
        json={
            "created_by": "sam",
            "markdown_body": markdown,
            "report_json": report_json,
        },
    )
    assert preview.status_code == 200
    assert preview.json()["report_hash"] == report_content_hash(markdown, report_json)

    submitted = client.post(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-001/report",
        headers=auth("sam-token"),
        json={
            "created_by": "sam",
            "markdown_body": markdown,
            "report_json": report_json,
            "report_hash": preview.json()["report_hash"],
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "report_ready"
    assert submitted.json()["report_id"]

    status = client.get(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-001",
        headers=auth("sam-token"),
    )
    assert status.status_code == 200
    assert status.json()["report"]["report_hash"] == submitted.json()["report_hash"]

    target_results = client.get(
        "/internal/v1/crawl-analysis/target-results?job_id=1",
        headers=auth("sam-token"),
    )
    assert target_results.status_code == 200
    assert target_results.json()["total_count"] == 2
    assert [item["target_key"] for item in target_results.json()["items"]] == ["000660", "005930"]

    sample_target_result = client.get(
        "/internal/v1/crawl-analysis/target-results?job_id=1&target_key=005930&step_name=prices&size=1",
        headers=auth("sam-token"),
    )
    assert sample_target_result.status_code == 200
    assert sample_target_result.json()["total_count"] == 1
    assert [item["target_key"] for item in sample_target_result.json()["items"]] == ["005930"]

    request_reports = client.get(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-001/quality-reports",
        headers=auth("sam-token"),
    )
    assert request_reports.status_code == 200
    assert len(request_reports.json()) == 7


def test_analysis_scope_and_state_machine_are_enforced(analysis_client):
    client, _session = analysis_client
    assert client.get("/internal/v1/crawl-analysis/quality-reports").status_code == 401
    assert client.post(
        "/internal/v1/crawl-analysis/requests",
        headers=auth("sam-token"),
        json={
            "request_id": "analysis-unauthorized",
            "idempotency_key": "analysis-unauthorized",
            "reason": "should not create",
        },
    ).status_code == 403

    create = client.post(
        "/internal/v1/crawl-analysis/requests",
        headers=auth("operator-token"),
        json={
            "request_id": "analysis-20260815-weekly-002",
            "idempotency_key": "weekly-duplicate-check",
            "reason": "state check",
        },
    )
    assert create.status_code == 201
    premature = client.post(
        "/internal/v1/crawl-analysis/requests/analysis-20260815-weekly-002/report",
        headers=auth("sam-token"),
        json={
            "markdown_body": "# no",
            "report_json": {"schema_version": 1, "request_id": "analysis-20260815-weekly-002", "findings": [], "limitations": ["not enough evidence"]},
            "report_hash": "0" * 64,
        },
    )
    assert premature.status_code == 409
    duplicate = client.post(
        "/internal/v1/crawl-analysis/requests",
        headers=auth("operator-token"),
        json={
            "request_id": "different-request-id",
            "idempotency_key": "weekly-duplicate-check",
            "reason": "state check",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["request_id"] == "analysis-20260815-weekly-002"


def test_weekly_request_excludes_non_daily_crawl_jobs(analysis_client):
    client, session = analysis_client
    non_daily_job = CrawlJob(
        job_type="sync_symbols",
        started_at=datetime(2026, 8, 16, 8, 0, 0),
        finished_at=datetime(2026, 8, 16, 9, 0, 0),
        status="completed",
    )
    session.add(non_daily_job)
    session.flush()
    session.add(
        CrawlQualityReport(
            crawl_job_id=non_daily_job.id,
            trade_date=date(2026, 8, 16),
            job_type="sync_symbols",
            job_status="completed",
            symbols_total=1,
            symbols_succeeded=1,
            symbols_failed=0,
            failure_event_count=0,
            success_rate=1.0,
            coverage_rate=1.0,
            error_distribution={},
            repeated_failure_summary={},
            anomaly_summary={},
            sample_refs={},
            source_snapshot={},
            report_hash="f" * 64,
        )
    )
    session.commit()

    response = client.post(
        "/internal/v1/crawl-analysis/requests",
        headers=auth("operator-token"),
        json={
            "request_id": "analysis-20260816-weekly-daily-only",
            "idempotency_key": "weekly-daily-only",
            "reason": "일일 배치만 포함해야 함",
        },
    )

    assert response.status_code == 201
    assert non_daily_job.id not in response.json()["completed_job_ids"]
