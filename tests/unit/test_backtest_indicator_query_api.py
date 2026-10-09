from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.endpoints.backtest_auth import require_backtest_operator
from app.api.v1.endpoints.backtest_indicators import router
from app.core.base import Base
from app.core.database import get_db_session
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputPolicy,
    IndicatorSeries,
    IndicatorValue,
)
from app.models.instrument import Instrument


@pytest.fixture
def indicator_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    instrument = _instrument(session, code="100001", name="지표 표본")
    volume = _persist_current_indicator(session, instrument_id=instrument.id, kind="volume_sma")
    atr = _persist_current_indicator(session, instrument_id=instrument.id, kind="atr")
    session.commit()

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/backtests")

    def override_get_db():
        yield session

    test_app.dependency_overrides[get_db_session] = override_get_db
    test_app.dependency_overrides[require_backtest_operator] = lambda: object()
    with TestClient(test_app) as client:
        client.session = session
        client.instrument_id = instrument.id
        client.volume_series_id = volume.id
        client.atr_series_id = atr.id
        yield client
    test_app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def _instrument(session: Session, *, code: str, name: str = "표본") -> Instrument:
    existing_count = session.query(Instrument).count()
    row = Instrument(
        krx_short_code=code,
        isin=f"KR{int(code):010d}{existing_count:04d}",
        name=name,
        market="KOSPI",
        security_type="stock",
        listing_status="listed",
    )
    session.add(row)
    session.flush()
    return row


def _persist_current_indicator(
    session: Session,
    *,
    instrument_id: int,
    kind: str,
    provider: str = "test-provider",
    completed_at: datetime = datetime(2024, 1, 5, 1, tzinfo=UTC),
) -> IndicatorSeries:
    policy_id = session.query(IndicatorInputPolicy).filter_by(provider=provider).with_entities(
        IndicatorInputPolicy.id
    ).scalar()
    if policy_id is None:
        policy = IndicatorInputPolicy(
            version="validated-observation-ohlcv-v1",
            provider=provider,
            adjustment_type="split-adjusted",
            allowed_parser_versions=["test-v1"],
            observation_cutoff=datetime(2024, 1, 5, tzinfo=UTC),
            selector_version="test-selector-v1",
            validation_version="test-validation-v1",
            correction_version="test-correction-v1",
            fingerprint=(provider.encode().hex() + "0" * 64)[:64],
        )
        session.add(policy)
        session.flush()
        policy_id = policy.id

    definitions = {
        "volume_sma": ("volume", "50", "volume-sma-v1", 50),
        "atr": ("high-low-close", "14", "wilder-atr-14-v1", 14),
    }
    input_field, periods, formula_version, period = definitions[kind]
    series = IndicatorSeries(
        instrument_id=instrument_id,
        indicator_kind=kind,
        input_field=input_field,
        periods=periods,
        input_policy_version="validated-observation-ohlcv-v1",
        formula_version=formula_version,
        source_provider=provider,
        adjustment_policy="split-adjusted",
        allowed_parser_versions=["test-v1"],
        observation_cutoff=datetime(2024, 1, 5, tzinfo=UTC),
        input_policy_id=policy_id,
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
        input_cutoff=datetime(2024, 1, 5, tzinfo=UTC),
        input_hash="a" * 64,
        result_hash="b" * 64,
        input_count=3,
        result_count=3,
        completed_at=completed_at,
    )
    session.add(run)
    session.flush()
    for trade_date, value_status, reason, value in (
        (date(2024, 1, 2), "warming_up", "warming_up", None),
        (date(2024, 1, 3), "available", None, Decimal("12345.6700")),
        (date(2024, 1, 4), "data_unavailable", "missing_selected_source", None),
    ):
        session.add(
            IndicatorValue(
                calculation_run_id=run.id,
                generation_id=generation.id,
                indicator_kind=kind,
                period=period,
                trade_date=trade_date,
                value=value,
                status=value_status,
                reason_code=reason,
                available_observations=50 if kind == "volume_sma" else 14,
                input_prefix_hash="c" * 64,
            )
        )
    session.flush()
    return series


def _params(**overrides):
    return {
        "code": "100001",
        "start": "2024-01-01",
        "end": "2024-01-31",
        **overrides,
    }


@pytest.mark.parametrize(
    ("path", "series_field", "kind", "period"),
    [
        ("volume-sma50", "volume_series_id", "volume_sma", 50),
        ("atr14", "atr_series_id", "atr", 14),
    ],
)
def test_indicator_query_serializes_decimal_status_and_policy_generation(
    indicator_client, path, series_field, kind, period
):
    response = indicator_client.get(
        f"/api/v1/backtests/indicators/{path}",
        params=_params(instrument_id=indicator_client.instrument_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["indicator_kind"] == kind
    assert body["instrument_id"] == indicator_client.instrument_id
    assert body["series_id"] == getattr(indicator_client, series_field)
    assert body["generation_id"] > 0
    assert body["period"] == period
    assert "periods" not in body
    policy_fingerprint = indicator_client.session.query(IndicatorInputPolicy).filter_by(
        provider="test-provider"
    ).one().fingerprint
    assert body["source_policy_fingerprint"] == policy_fingerprint
    assert "fingerprint" not in body["input_policy"]
    assert body["input_policy"]["version"] == "validated-observation-ohlcv-v1"
    assert body["input_policy"]["source_provider"] == "test-provider"
    assert body["input_policy"]["observation_cutoff"] == "2024-01-05T00:00:00Z"
    assert body["as_of"] == "2024-01-04"
    assert body["calculated_at"] == "2024-01-05T01:00:00Z"
    assert body["total_count"] == 3
    assert [item["trade_date"] for item in body["items"]] == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
    ]
    warming = body["items"][0]
    assert warming["value"] is None
    assert warming["status"] == "warming_up"
    assert warming["reason_code"] == "warming_up"
    available = body["items"][1]
    assert Decimal(available["value"]) == Decimal("12345.67")
    assert isinstance(available["value"], str)
    assert available["status"] == "available"
    unavailable = body["items"][2]
    assert unavailable["value"] is None
    assert unavailable["status"] == "data_unavailable"
    assert unavailable["reason_code"] == "missing_selected_source"


def test_indicator_query_paginates_in_trade_date_order(indicator_client):
    first = indicator_client.get(
        "/api/v1/backtests/indicators/volume-sma50",
        params=_params(instrument_id=indicator_client.instrument_id, page=1, size=2),
    )
    second = indicator_client.get(
        "/api/v1/backtests/indicators/volume-sma50",
        params=_params(instrument_id=indicator_client.instrument_id, page=2, size=2),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["total_count"] == second.json()["total_count"] == 3
    assert [row["trade_date"] for row in first.json()["items"]] == ["2024-01-02", "2024-01-03"]
    assert [row["trade_date"] for row in second.json()["items"]] == ["2024-01-04"]


def test_indicator_query_requires_operator_session(indicator_client):
    indicator_client.app.dependency_overrides.pop(require_backtest_operator)
    response = indicator_client.get(
        "/api/v1/backtests/indicators/atr14", params=_params(instrument_id=indicator_client.instrument_id)
    )
    assert response.status_code == 401


def test_indicator_query_reports_ambiguous_code_and_policy_ids(indicator_client):
    session = indicator_client.session
    instrument = _instrument(session, code="100001", name="과거 코드 재사용")
    session.commit()
    ambiguous_instrument = indicator_client.get(
        "/api/v1/backtests/indicators/atr14", params=_params()
    )
    assert ambiguous_instrument.status_code == 409
    assert ambiguous_instrument.json()["detail"]["instrument_ids"] == sorted(
        [indicator_client.instrument_id, instrument.id]
    )

    second_series = _persist_current_indicator(
        session,
        instrument_id=indicator_client.instrument_id,
        kind="atr",
        provider="second-provider",
        completed_at=datetime(2024, 1, 6, 1, tzinfo=UTC),
    )
    session.commit()
    ambiguous_policy = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id),
    )
    assert ambiguous_policy.status_code == 409
    detail = ambiguous_policy.json()["detail"]
    assert detail["series_ids"] == sorted([indicator_client.atr_series_id, second_series.id])
    assert len(detail["input_policy_ids"]) == 2

    selected = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id, series_id=second_series.id),
    )
    assert selected.status_code == 200
    assert selected.json()["series_id"] == second_series.id


def test_indicator_query_returns_404_for_unknown_or_uncomputed_series(indicator_client):
    uncomputed = _instrument(indicator_client.session, code="300003", name="계산 전 종목")
    indicator_client.session.commit()
    unknown = indicator_client.get(
        "/api/v1/backtests/indicators/atr14", params=_params(code="999999")
    )
    uncomputed = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(code="300003", instrument_id=uncomputed.id),
    )
    assert unknown.status_code == 404
    assert uncomputed.status_code == 404


def test_indicator_query_rejects_mismatched_ids_range_and_page(indicator_client):
    other_instrument = _instrument(indicator_client.session, code="200002", name="다른 종목")
    indicator_client.session.commit()
    mismatch = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=other_instrument.id),
    )
    series_mismatch = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id, series_id=indicator_client.volume_series_id),
    )
    unknown_series = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id, series_id=999999),
    )
    invalid_range = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id, start="2024-02-01", end="2024-01-01"),
    )
    invalid_page = indicator_client.get(
        "/api/v1/backtests/indicators/atr14",
        params=_params(instrument_id=indicator_client.instrument_id, page=0),
    )
    assert mismatch.status_code == 422
    assert series_mismatch.status_code == 422
    assert unknown_series.status_code == 422
    assert invalid_range.status_code == 422
    assert invalid_page.status_code == 422
