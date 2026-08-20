from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.core.agent_auth as agent_auth
import app.models
from app.api.v1.endpoints import agent as agent_endpoint
from app.core.base import Base
from app.core.database import get_db_session
from app.main_api import app
from app.models.benchmark import Benchmark
from app.models.crawl_job import CrawlJob
from app.models.daily_price import DailyPrice
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.services.agent_data import AgentDataMeta


@pytest.fixture
def agent_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    symbol = Symbol(code="A", name="Alpha", market="KOSPI", is_active=True)
    session.add(symbol)
    session.flush()
    session.add(
        DailyPrice(
            symbol_id=symbol.id,
            trade_date=date(2026, 8, 10),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1,
            change_rate=Decimal("0"),
            source="kiwoom",
        )
    )
    benchmark = Benchmark(
        benchmark_code="KOSPI",
        name="KOSPI",
        market="KOSPI",
    )
    session.add(benchmark)
    session.flush()
    session.add(
        RsScore(
            symbol_id=symbol.id,
            benchmark_id=benchmark.id,
            trade_date=date(2026, 8, 10),
            market="KOSPI",
            return_3m=Decimal("0.1"),
            return_6m=Decimal("0.1"),
            return_9m=Decimal("0.1"),
            return_12m=Decimal("0.1"),
            relative_return_score=Decimal("0.1"),
            rs_percentile=Decimal("0.9"),
            rs_rating=90,
            rank_in_market=1,
        )
    )
    now = datetime.utcnow()
    session.add(
        CrawlJob(
            job_type="daily_full",
            started_at=now - timedelta(minutes=5),
            finished_at=now,
            status="completed",
            symbols_total=1,
            symbols_succeeded=1,
            symbols_failed=0,
        )
    )
    session.commit()

    monkeypatch.setattr(
        agent_auth,
        "get_settings",
        lambda: SimpleNamespace(
            agent_api_enabled=True,
            agent_service_tokens=(
                "status-token=status:read;"
                "rs-token=rs:read;"
                "stock-token=stock:read"
            ),
            agent_allowed_ips="",
        ),
    )

    def override_get_db():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


@pytest.fixture
def empty_agent_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(
        agent_auth,
        "get_settings",
        lambda: SimpleNamespace(
            agent_api_enabled=True,
            agent_service_tokens="rs-token=rs:read",
            agent_allowed_ips="",
        ),
    )

    def override_get_db():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_agent_status_has_envelope_headers_and_supports_etag(agent_client):
    first = agent_client.get(
        "/api/v1/agent/v1/status",
        headers={"Authorization": "Bearer status-token"},
    )
    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"data", "meta"}
    assert body["meta"]["data_status"] == "complete"
    assert body["meta"]["dataset_id"].startswith("rs-")
    assert first.headers["x-dataset-id"] == body["meta"]["dataset_id"]
    assert first.headers["x-data-status"] == "complete"
    assert first.headers["etag"]
    assert first.headers["x-request-id"]

    second = agent_client.get(
        "/api/v1/agent/v1/status",
        headers={
            "Authorization": "Bearer status-token",
            "If-None-Match": first.headers["etag"],
        },
    )
    assert second.status_code == 304
    assert second.headers["etag"] == first.headers["etag"]


@pytest.mark.parametrize("data_status", ["partial", "stale"])
def test_agent_status_exposes_degraded_states(agent_client, monkeypatch, data_status):
    now = datetime.utcnow()
    monkeypatch.setattr(
        agent_endpoint,
        "build_agent_meta",
        lambda _session: AgentDataMeta(
            dataset_id=f"rs-degraded-{data_status}",
            trade_date=date(2026, 8, 10),
            as_of=now,
            data_status=data_status,
            coverage=0.75,
        ),
    )

    response = agent_client.get(
        "/api/v1/agent/v1/status",
        headers={"Authorization": "Bearer status-token"},
    )

    assert response.status_code == 200
    assert response.json()["meta"]["data_status"] == data_status
    assert response.json()["meta"]["coverage"] == 0.75


def test_agent_scope_is_read_only_and_enforced(agent_client):
    forbidden = agent_client.get(
        "/api/v1/agent/v1/briefing",
        headers={"Authorization": "Bearer status-token"},
    )
    assert forbidden.status_code == 403

    briefing = agent_client.get(
        "/api/v1/agent/v1/briefing",
        headers={"Authorization": "Bearer rs-token"},
    )
    assert briefing.status_code == 200
    assert briefing.json()["data"]["trade_date"] == "2026-08-10"

    stock = agent_client.get(
        "/api/v1/agent/v1/stocks/A",
        headers={"Authorization": "Bearer stock-token"},
    )
    assert stock.status_code == 200
    assert stock.json()["data"]["code"] == "A"
    assert stock.json()["data"]["latest_price"]["source"] == "kiwoom"


def test_unavailable_agent_dataset_returns_503_with_retry_after(empty_agent_client):
    response = empty_agent_client.get(
        "/api/v1/agent/v1/briefing",
        headers={"Authorization": "Bearer rs-token"},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "300"


def test_agent_ip_allowlist_ignores_untrusted_forwarded_header():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [(b"x-forwarded-for", b"203.0.113.7")],
            "client": ("127.0.0.1", 8123),
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "path": "/internal/v1/crawl-analysis/requests",
            "query_string": b"",
        }
    )

    assert agent_auth._client_ip(request) == "127.0.0.1"
