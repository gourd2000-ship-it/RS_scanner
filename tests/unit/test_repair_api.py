from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.agent_auth as agent_auth
from app.api.v1.endpoints.repair import router as repair_router
from app.core.base import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob
from app.core.database import get_db_session
from app.api.v1.endpoints import repair as repair_endpoint
from app.services.repair_queue import RepairQueueService


@pytest.fixture
def repair_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full")
    session.add(job)
    session.flush()
    RepairQueueService(session).enqueue_from_target(
        job_id=job.id,
        crawl_target_result_id=None,
        symbol="005930",
        trade_date=date(2026, 8, 14),
        history_from=date(2026, 8, 1),
        error_type="empty_response",
    )
    session.commit()

    settings = SimpleNamespace(
        repair_api_enabled=True,
        legacy_repair_api_enabled=True,
        repair_max_rows=6000,
        repair_claim_lease_seconds=300,
        agent_service_tokens=(
            "repair-token=repair:claim,repair:submit,repair:fail;"
            "submit-only=repair:submit"
        ),
        agent_allowed_ips="",
    )
    monkeypatch.setattr(agent_auth, "get_settings", lambda: settings)
    monkeypatch.setattr(repair_endpoint, "get_settings", lambda: settings)

    test_app = FastAPI()
    test_app.include_router(repair_router, prefix="/internal/v1/repair")

    def override_get_db():
        yield session

    test_app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(test_app) as client:
        yield client, session
    session.close()
    engine.dispose()


def auth(token="repair-token"):
    return {"Authorization": f"Bearer {token}"}


def test_claim_complete_and_status_round_trip(repair_client):
    client, session = repair_client
    claim = client.post(
        "/internal/v1/repair/requests/claim",
        headers=auth(),
        json={"claimed_by": "sam"},
    )
    assert claim.status_code == 200
    task = claim.json()
    assert task["symbol"] == "005930"
    assert task["from"] == "2026-08-01"
    assert task["to"] == "2026-08-14"

    complete = client.post(
        f"/internal/v1/repair/requests/{task['request_id']}/complete",
        headers=auth(),
        json={
            "claim_token": task["claim_token"],
            "claim_version": task["claim_version"],
            "operation": "daily_chart",
            "symbol": "005930",
            "from": "2026-08-01",
            "to": "2026-08-14",
            "adjusted_price": True,
            "executor": "sam",
            "tool": "kiwoomcli",
            "mode": "demo",
            "latest_date": "2026-08-13",
            "row_count": 1,
            "data_complete": True,
            "rows": [
                {
                    "symbol": "005930",
                    "trade_date": "2026-08-13",
                    "source": "kiwoom",
                    "adjusted_price": True,
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "105",
                    "volume": 1000,
                    "change_rate": "1.2",
                }
            ],
        },
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"

    status = client.get(
        f"/internal/v1/repair/requests/{task['request_id']}",
        headers=auth(),
    )
    assert status.status_code == 200
    assert status.json()["result_count"] == 1
    assert status.json()["application_status"] == "not_applied"


def test_repair_scope_is_separate_and_empty_claim_is_204(repair_client):
    client, _session = repair_client
    forbidden = client.post(
        "/internal/v1/repair/requests/claim",
        headers={"Authorization": "Bearer submit-only"},
        json={"claimed_by": "sam"},
    )
    assert forbidden.status_code == 403

    first = client.post(
        "/internal/v1/repair/requests/claim",
        headers=auth(),
        json={"claimed_by": "sam"},
    )
    assert first.status_code == 200
    second = client.post(
        "/internal/v1/repair/requests/claim",
        headers=auth(),
        json={"claimed_by": "sam"},
    )
    assert second.status_code == 204


def test_incomplete_result_returns_422_and_does_not_complete(repair_client):
    client, _session = repair_client
    claim = client.post(
        "/internal/v1/repair/requests/claim",
        headers=auth(),
        json={"claimed_by": "sam"},
    ).json()
    response = client.post(
        f"/internal/v1/repair/requests/{claim['request_id']}/complete",
        headers=auth(),
        json={
            "claim_token": claim["claim_token"],
            "claim_version": claim["claim_version"],
            "operation": "daily_chart",
            "symbol": "005930",
            "from": "2026-08-01",
            "to": "2026-08-14",
            "adjusted_price": True,
            "mode": "demo",
            "latest_date": "2026-08-13",
            "row_count": 1,
            "data_complete": False,
            "rows": [
                {
                    "symbol": "005930",
                    "trade_date": "2026-08-13",
                    "source": "kiwoom",
                    "adjusted_price": True,
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "105",
                    "volume": 1000,
                }
            ],
        },
    )
    assert response.status_code == 422
