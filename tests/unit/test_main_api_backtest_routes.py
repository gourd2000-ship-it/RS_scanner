from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_main_api_registers_protected_ma50_and_atr14_routes(monkeypatch):
    from app.core import database
    from app.core.database import get_db_session
    from app.api.v1.endpoints.backtest_auth import require_backtest_operator

    monkeypatch.setattr(database, "init_db", lambda: None)
    main_api = importlib.import_module("app.main_api")
    registered = {
        (route.path, method)
        for route in main_api.app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/v1/backtests/indicators/volume-sma50", "GET") in registered
    assert ("/api/v1/backtests/indicators/atr14", "GET") in registered

    with TestClient(main_api.app) as client:
        volume_response = client.get(
            "/api/v1/backtests/indicators/volume-sma50",
            params={"code": "005930", "start": "2026-01-01", "end": "2026-01-31"},
        )
        atr_response = client.get(
            "/api/v1/backtests/indicators/atr14",
            params={"code": "005930", "start": "2026-01-01", "end": "2026-01-31"},
        )

    assert volume_response.status_code == 401
    assert atr_response.status_code == 401
    assert get_db_session not in main_api.app.dependency_overrides
    assert require_backtest_operator not in main_api.app.dependency_overrides
