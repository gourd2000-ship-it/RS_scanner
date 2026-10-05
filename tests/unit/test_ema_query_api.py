from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.endpoints.backtest_auth import require_backtest_operator
from app.core.base import Base
from app.core.database import get_db_session
from app.main_api import app
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputPolicy,
    IndicatorSeries,
    IndicatorValue,
)
from app.models.instrument import Instrument
from app.repositories.indicator_repository import IndicatorRepository


@pytest.fixture
def ema_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    primary = Instrument(
        krx_short_code="100001",
        isin="KR7100000001",
        name="EMA 표본",
        market="KOSPI",
        security_type="stock",
        listing_status="listed",
    )
    ambiguous = Instrument(
        krx_short_code="100001",
        isin="KR7100000002",
        name="코드 재사용 표본",
        market="KOSPI",
        security_type="stock",
        listing_status="delisted",
    )
    session.add_all([primary, ambiguous])
    session.flush()
    _persist_current_ema(session, instrument_id=primary.id)
    session.commit()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[require_backtest_operator] = lambda: object()
    with TestClient(app) as client:
        client.ema_session = session
        client.primary_instrument_id = primary.id
        yield client
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def _persist_current_ema(
    session: Session,
    *,
    instrument_id: int,
    source_provider: str = "test-provider",
    completed_at: datetime = datetime(2024, 1, 4, 1, tzinfo=UTC),
    first_value: Decimal = Decimal("100.125"),
) -> None:
    series = IndicatorSeries(
        instrument_id=instrument_id,
        source_provider=source_provider,
        adjustment_policy="test-adjustment",
        allowed_parser_versions=["test-v1"],
        observation_cutoff=datetime(2024, 1, 4, tzinfo=UTC),
    )
    session.add(series)
    session.flush()
    generation = IndicatorGeneration(series_id=series.id, generation=1, status="current")
    session.add(generation)
    session.flush()
    run = IndicatorCalculationRun(
        series_id=series.id,
        generation_id=generation.id,
        run_kind="backfill",
        status="completed",
        input_cutoff=datetime(2024, 1, 4, tzinfo=UTC),
        input_hash="a" * 64,
        result_hash="b" * 64,
        input_count=2,
        result_count=8,
        completed_at=completed_at,
    )
    session.add(run)
    session.flush()
    for trade_date, status, reason, value in (
        (date(2024, 1, 2), "warming_up", "warming_up", first_value),
        (date(2024, 1, 3), "data_unavailable", "missing_selected_source", None),
    ):
        for period in (5, 20, 50, 200):
            session.add(
                IndicatorValue(
                    calculation_run_id=run.id,
                    generation_id=generation.id,
                    period=period,
                    trade_date=trade_date,
                    value=value,
                    status=status,
                    reason_code=reason,
                    available_observations=1,
                    input_prefix_hash=f"{period:064d}",
                )
            )


def _params(**overrides):
    return {
        "code": "100001",
        "start": "2024-01-01",
        "end": "2024-01-31",
        **overrides,
    }


def test_ema_query_requires_current_operator_session(ema_client):
    app.dependency_overrides.pop(require_backtest_operator)
    response = ema_client.get("/api/v1/backtests/indicators/ema", params=_params())
    assert response.status_code == 401


def test_ema_query_requires_instrument_id_for_ambiguous_code_and_serializes_evidence(ema_client):
    ambiguous = ema_client.get("/api/v1/backtests/indicators/ema", params=_params())
    assert ambiguous.status_code == 409

    response = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=ema_client.primary_instrument_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["instrument_id"] == ema_client.primary_instrument_id
    assert body["code"] == "100001"
    assert body["as_of"] == "2024-01-03"
    assert body["calculated_at"] == "2024-01-04T01:00:00Z"
    assert body["total_count"] == 2
    assert [item["trade_date"] for item in body["items"]] == ["2024-01-02", "2024-01-03"]
    first = body["items"][0]["values"]
    assert [value["period"] for value in first] == [5, 20, 50, 200]
    assert isinstance(first[0]["value"], str)
    assert Decimal(first[0]["value"]) == Decimal("100.125")
    assert first[0]["status"] == "warming_up"
    assert first[0]["reason_code"] == "warming_up"
    unavailable = body["items"][1]["values"][0]
    assert unavailable["value"] is None
    assert unavailable["status"] == "data_unavailable"
    assert unavailable["reason_code"] == "missing_selected_source"


def test_ema_query_paginates_by_trade_date_deterministically(ema_client):
    first = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=ema_client.primary_instrument_id, page=1, size=1),
    )
    second = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=ema_client.primary_instrument_id, page=2, size=1),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["total_count"] == second.json()["total_count"] == 2
    assert first.json()["items"][0]["trade_date"] == "2024-01-02"
    assert second.json()["items"][0]["trade_date"] == "2024-01-03"


def test_ema_query_selects_latest_completed_current_policy_series(ema_client):
    _persist_current_ema(
        ema_client.ema_session,
        instrument_id=ema_client.primary_instrument_id,
        source_provider="replacement-policy-provider",
        completed_at=datetime(2024, 1, 5, 1, tzinfo=UTC),
        first_value=Decimal("200.5"),
    )
    ema_client.ema_session.commit()

    response = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=ema_client.primary_instrument_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["calculated_at"] == "2024-01-05T01:00:00Z"
    assert body["total_count"] == 2
    assert Decimal(body["items"][0]["values"][0]["value"]) == Decimal("200.5")


def test_ema_query_rejects_unknown_instrument_and_invalid_range(ema_client):
    unknown = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=999999),
    )
    invalid_range = ema_client.get(
        "/api/v1/backtests/indicators/ema",
        params=_params(instrument_id=ema_client.primary_instrument_id, start="2024-02-01", end="2024-01-01"),
    )

    assert unknown.status_code == 404
    assert invalid_range.status_code == 422


def test_newer_volume_series_does_not_change_ema_metadata_or_pages(ema_client):
    session = ema_client.ema_session
    instrument_id = ema_client.primary_instrument_id
    cutoff = datetime(2024, 2, 1, tzinfo=UTC)
    policy = IndicatorInputPolicy(
        provider="test-provider", adjustment_type="test-adjustment",
        allowed_parser_versions=["test-v1"], observation_cutoff=cutoff,
        selector_version="selector-v1", validation_version="validation-v1",
        correction_version="correction-v1", fingerprint="c" * 64,
    )
    session.add(policy)
    session.flush()
    volume_series = IndicatorSeries(
        instrument_id=instrument_id, indicator_kind="volume_sma",
        input_field="volume", periods="50", formula_version="volume-sma-v1",
        input_policy_version="validated-observation-ohlcv-v1", input_policy_id=policy.id,
        source_provider=policy.provider, adjustment_policy=policy.adjustment_type,
        allowed_parser_versions=policy.allowed_parser_versions, observation_cutoff=cutoff,
    )
    session.add(volume_series)
    session.flush()
    generation = IndicatorGeneration(series_id=volume_series.id, generation=1, status="current")
    session.add(generation)
    session.flush()
    run = IndicatorCalculationRun(
        series_id=volume_series.id, generation_id=generation.id, run_kind="backfill",
        status="completed", input_cutoff=cutoff, input_hash="d" * 64,
        result_hash="e" * 64, input_count=1, result_count=1,
        completed_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    session.add(run)
    session.flush()
    session.add(IndicatorValue(
        calculation_run_id=run.id, generation_id=generation.id, indicator_kind="volume_sma",
        period=50, trade_date=date(2024, 1, 9), value=Decimal("12345"),
        status="available", reason_code=None, available_observations=50,
        input_prefix_hash="f" * 64,
    ))
    session.commit()

    response = ema_client.get(
        "/api/v1/backtests/indicators/ema", params=_params(instrument_id=instrument_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2024-01-03"
    assert body["calculated_at"] == "2024-01-04T01:00:00Z"
    assert body["total_count"] == 2
    assert [item["trade_date"] for item in body["items"]] == ["2024-01-02", "2024-01-03"]
    assert [value["period"] for value in body["items"][0]["values"]] == [5, 20, 50, 200]
    assert Decimal(body["items"][0]["values"][0]["value"]) == Decimal("100.125")

    # Direct repository callers cannot request Volume values through EMA paging.
    assert IndicatorRepository(session).current_ema_page(
        instrument_id=instrument_id, series_id=volume_series.id, generation_id=generation.id,
        start=date(2024, 1, 1), end=date(2024, 1, 31), page=1, size=10,
    ) == ((), 0)
