from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.core.agent_auth as agent_auth
from app.core.rate_limit import RateLimitMiddleware


def test_agent_auth_returns_401_for_missing_token_and_403_for_scope(monkeypatch):
    monkeypatch.setattr(
        agent_auth,
        "get_settings",
        lambda: SimpleNamespace(
            agent_api_enabled=True,
            agent_service_tokens="status-token=status:read;rs-token=rs:read",
            agent_allowed_ips="",
        ),
    )
    test_app = FastAPI()

    @test_app.get("/agent")
    def protected(_principal=Depends(agent_auth.require_agent_scope("status:read"))):
        return {"ok": True}

    client = TestClient(test_app)
    missing = client.get("/agent")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    missing_scope = client.get(
        "/agent",
        headers={"Authorization": "Bearer rs-token"},
    )
    assert missing_scope.status_code == 403

    valid = client.get(
        "/agent",
        headers={"Authorization": "Bearer status-token"},
    )
    assert valid.status_code == 200


def test_agent_rate_limit_returns_429_and_retry_after():
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware)

    @test_app.get("/api/v1/agent/v1/status")
    def status():
        return {"ok": True}

    client = TestClient(test_app)
    responses = [
        client.get("/api/v1/agent/v1/status", headers={"X-Forwarded-For": "192.0.2.10"})
        for _ in range(61)
    ]

    assert responses[59].status_code == 200
    assert responses[60].status_code == 429
    assert responses[60].headers["retry-after"] == "60"
