from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.agent_auth as agent_auth
import app.models  # noqa: F401
from app.core.base import Base
from app.core.database import get_db_session
from app.main_api import app
from app.models.benchmark import Benchmark
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetMembership, BacktestDatasetPrice
from app.models.daily_price import DailyPrice
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.rs_score import RsScore
from app.models.symbol import Symbol


@pytest.fixture
def backtest_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    kospi = Symbol(code="000001", name="Kospi", market="KOSPI", is_active=True)
    kosdaq = Symbol(code="000002", name="Kosdaq", market="KOSDAQ", is_active=True)
    session.add_all([kospi, kosdaq])
    session.flush()
    benchmark = Benchmark(benchmark_code="KOSPI", name="KOSPI", market="KOSPI")
    session.add(benchmark)
    session.flush()

    prices = [
        (kospi, date(2020, 1, 2), "100"),
        (kosdaq, date(2020, 1, 2), "200"),
        (kospi, date(2020, 1, 3), "101"),
    ]
    for symbol, trade_date, close in prices:
        session.add(
            DailyPrice(
                symbol_id=symbol.id,
                trade_date=trade_date,
                open=Decimal(close),
                high=Decimal(close) + 1,
                low=Decimal(close) - 1,
                close=Decimal(close),
                volume=100,
                change_rate=Decimal("0"),
                source="test",
            )
        )
        session.add(
            RsScore(
                symbol_id=symbol.id,
                benchmark_id=benchmark.id,
                trade_date=trade_date,
                market=symbol.market,
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

    snapshot = KrxUniverseSnapshot(
        source="test",
        scope="stock_membership",
        as_of_date=date(2020, 1, 2),
        status="completed",
        members_seen=1,
        members_valid=1,
        started_at=datetime(2020, 1, 2),
        finished_at=datetime(2020, 1, 2, 1),
    )
    session.add(snapshot)
    session.flush()
    session.add(
        KrxUniverseMembership(
            snapshot_id=snapshot.id,
            code=kospi.code,
            name=kospi.name,
            market=kospi.market,
            security_type="stock",
            listing_status="listed_observed",
            trading_status="normal",
        )
    )
    session.commit()

    monkeypatch.setattr(
        agent_auth,
        "get_settings",
        lambda: SimpleNamespace(
            agent_api_enabled=True,
            agent_service_tokens="backtest-token=backtest:read;stock-token=stock:read",
            agent_allowed_ips="",
        ),
    )

    def override_get_db():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        client.backtest_session = session
        yield client
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_backtest_dataset_paginates_period_data_with_rs_and_historical_universe(backtest_client):
    params = {
        "start": "2020-01-01",
        "end": "2020-01-03",
        "markets": "KOSPI,KOSDAQ",
        "page_size": 2,
    }
    headers = {"Authorization": "Bearer backtest-token"}

    first = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset", params=params, headers=headers
    )

    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"]
    assert first.headers["etag"]
    assert first_body["dataset_id"]
    assert first_body["watermark"]
    assert first_body["coverage"]["rs"] == 1.0
    assert first_body["items"][0]["price"]["close"] == "100.0000"
    assert first_body["items"][0]["rs"]["rs_rating"] == 90
    assert first_body["items"][0]["universe"]["status"] == "listed_observed"
    assert first_body["items"][1]["universe"]["status"] == "unknown"

    second = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset",
        params={**params, "cursor": first_body["next_cursor"]},
        headers=headers,
    )

    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"] is None
    assert second.json()["dataset_id"] == first_body["dataset_id"]


def test_backtest_dataset_requires_its_dedicated_scope(backtest_client):
    response = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset?start=2020-01-01&end=2020-01-03",
        headers={"Authorization": "Bearer stock-token"},
    )

    assert response.status_code == 403


def test_backtest_dataset_rejects_malformed_cursor(backtest_client):
    response = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset",
        params={
            "start": "2020-01-01",
            "end": "2020-01-03",
            "cursor": "not-a-valid-cursor%",
        },
        headers={"Authorization": "Bearer backtest-token"},
    )

    assert response.status_code == 422


def test_materialized_dataset_returns_missing_price_reason_and_binds_cursor_to_manifest(backtest_client):
    session = backtest_client.backtest_session
    dataset = BacktestDataset(
        dataset_id="frozen-dataset", manifest_hash="f" * 64,
        range_start=date(2020, 1, 2), range_end=date(2020, 1, 3), markets=["KOSPI"],
        reconstruction_mode="historical_reconstructed", adjustment_policy="kiwoom:1", policy_version="v1", manifest={},
    )
    session.add(dataset)
    session.flush()
    dataset.memberships.extend([
        BacktestDatasetMembership(instrument_id=100, trade_date=date(2020, 1, 2), market="KOSPI", security_type="stock", membership_evidence_state="observed", trading_status="trading", price_expectation="expected", event_revision_hashes=[]),
        BacktestDatasetMembership(instrument_id=101, trade_date=date(2020, 1, 3), market="KOSPI", security_type="stock", membership_evidence_state="observed", trading_status="suspended", price_expectation="outside_trading_interval", event_revision_hashes=[]),
    ])
    dataset.prices.append(BacktestDatasetPrice(instrument_id=100, source_symbol_id=100, code="000100", name="표본", market="KOSPI", trade_date=date(2020, 1, 2), open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100"), volume=100, change_rate=Decimal("0"), provider="kiwoom"))
    session.commit()
    headers = {"Authorization": "Bearer backtest-token"}
    params = {"dataset_id": "frozen-dataset", "start": "2020-01-02", "end": "2020-01-03", "markets": "KOSPI", "page_size": 1}
    first = backtest_client.get("/api/v1/agent/v2/backtest/dataset", params=params, headers=headers)
    assert first.status_code == 200
    assert first.json()["items"][0]["price"]["close"] == "100.0000"
    second = backtest_client.get("/api/v1/agent/v2/backtest/dataset", params={**params, "cursor": first.json()["next_cursor"]}, headers=headers)
    assert second.json()["items"][0]["price"] is None
    assert second.json()["items"][0]["price_reason"] == "outside_trading_interval"
    assert second.json()["partial"] is True

    strict = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset", params={**params, "strict": "true"}, headers=headers
    )
    assert strict.status_code == 200
    assert strict.json()["items"] == []
    assert strict.json()["partial"] is False

    strict_cursor = backtest_client.get(
        "/api/v1/agent/v2/backtest/dataset",
        params={**params, "strict": "true", "cursor": first.json()["next_cursor"]},
        headers=headers,
    )
    assert strict_cursor.status_code == 422

    dataset.manifest_hash = "e" * 64
    session.commit()
    changed = backtest_client.get("/api/v1/agent/v2/backtest/dataset", params={**params, "cursor": first.json()["next_cursor"]}, headers=headers)
    assert changed.status_code == 409

    dataset.status = "active"
    dataset.retention_until = datetime(2020, 1, 1)
    session.commit()
    expired = backtest_client.get("/api/v1/agent/v2/backtest/dataset", params=params, headers=headers)
    assert expired.status_code == 410


def test_ohlcv_dataset_strict_mode_keeps_valid_rows_without_rs_and_stable_identity(backtest_client):
    session = backtest_client.backtest_session
    dataset = BacktestDataset(
        dataset_id="clean-ohlcv", manifest_hash="c" * 64,
        range_start=date(2020, 1, 2), range_end=date(2020, 1, 3), markets=["KOSPI"],
        reconstruction_mode="historical_reconstructed", adjustment_policy="kiwoom:1",
        policy_version="ohlcv-audit-v1", manifest={"version": "ohlcv-cleansed-v1", "coverage": {"expected": 2, "valid": 1, "missing": 1}},
    )
    session.add(dataset)
    session.flush()
    dataset.memberships.extend([
        BacktestDatasetMembership(instrument_id=100, trade_date=date(2020, 1, 2), market="KOSPI",
                                  security_type="stock", membership_evidence_state="observed", trading_status="trading",
                                  price_expectation="expected", event_revision_hashes=[],
                                  code="000100", name="표본", quality_status="valid"),
        BacktestDatasetMembership(instrument_id=100, trade_date=date(2020, 1, 3), market="KOSPI",
                                  security_type="stock", membership_evidence_state="observed", trading_status="trading",
                                  price_expectation="expected", event_revision_hashes=[],
                                  code="000100", name="표본", quality_status="missing", quality_reason="selected_source_missing"),
    ])
    dataset.prices.append(BacktestDatasetPrice(
        instrument_id=100, source_symbol_id=100, source_observation_id=1,
        code="000100", name="표본", market="KOSPI", trade_date=date(2020, 1, 2),
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
        volume=100, change_rate=Decimal("0"), provider="kiwoom", adjustment_type="1",
    ))
    session.commit()
    params = {"dataset_id": "clean-ohlcv", "start": "2020-01-02", "end": "2020-01-03", "markets": "KOSPI"}
    headers = {"Authorization": "Bearer backtest-token"}
    url = "/api/v1/agent/v2/backtest/dataset"
    all_rows = backtest_client.get(url, params=params, headers=headers)
    assert all_rows.status_code == 200
    assert [row["instrument_id"] for row in all_rows.json()["items"]] == [100, 100]
    assert [row["code"] for row in all_rows.json()["items"]] == ["000100", "000100"]
    assert [row["quality"] for row in all_rows.json()["items"]] == ["valid", "missing"]
    assert all_rows.json()["dataset_coverage"] == {"expected": 2, "valid": 1, "missing": 1}
    strict_rows = backtest_client.get(url, params={**params, "strict": "true"}, headers=headers)
    assert strict_rows.status_code == 200
    assert len(strict_rows.json()["items"]) == 1
    assert strict_rows.json()["items"][0]["rs"] is None
