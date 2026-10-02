from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.core.base import Base
from app.core.database import get_db_session
from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetMembership,
    BacktestDatasetPrice,
    BacktestDatasetRs,
    BacktestDatasetRsRun,
)
from app.models.backtest_run import BacktestStrategyVersion
from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.auth import BacktestOperatorAuthService, InvalidCsrfToken
from app.services.backtest.input_selection import BacktestInputUnavailable, select_backtest_inputs
from app.services.backtest.run_preparation import BacktestRunPreparationService
from app.api.v1.endpoints import backtest_auth


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _complete_inputs(session: Session) -> tuple[BacktestDataset, BacktestDatasetRsRun]:
    manifest = {"publication_scope": "complete_segments_only"}
    dataset = BacktestDataset(
        dataset_id="complete-latest", manifest_hash="a" * 64, final_manifest_hash=_hash(manifest),
        range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI", "KOSDAQ"], reconstruction_mode="historical_reconstructed",
        adjustment_policy="fixture:1", policy_version="v1", manifest=manifest, status="active",
    )
    session.add(dataset)
    session.flush()
    for market, instrument, code in (("KOSPI", 1, "000001"), ("KOSDAQ", 2, "000002")):
        for offset, trade_date in enumerate((date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))):
            dataset.memberships.append(BacktestDatasetMembership(
                instrument_id=instrument, trade_date=trade_date, market=market, security_type="stock",
                membership_evidence_state="observed", trading_status="trading", price_expectation="expected",
                event_revision_hashes=[], code=code, name=code, quality_status="complete",
            ))
            dataset.prices.append(BacktestDatasetPrice(
                instrument_id=instrument, source_symbol_id=instrument, code=code, name=code, market=market,
                trade_date=trade_date, open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
                close=Decimal(str(100 + offset)), volume=100, change_rate=Decimal("0"), provider="fixture",
            ))
    run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id, formula_version="rs-v1", policy_version="v1", input_hash="b" * 64,
        result_hash="c" * 64, status="completed", created_at=datetime(2024, 1, 10, tzinfo=timezone.utc), manifest={},
    )
    session.add(run)
    session.flush()
    for membership in dataset.memberships:
        session.add(BacktestDatasetRs(
            backtest_dataset_rs_run_id=run.id, backtest_dataset_id=dataset.id, instrument_id=membership.instrument_id,
            code=membership.code or "", market=membership.market, trade_date=membership.trade_date,
            status="available", required_observations=1, available_observations=1,
            rs_rating=90, rank_in_market=1, input_hash="d" * 64,
        ))
    for market in ("KOSPI", "KOSDAQ"):
        benchmark = Benchmark(benchmark_code=market, name=market, market=market)
        session.add(benchmark)
        session.flush()
        for offset, trade_date in enumerate((date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))):
            session.add(BenchmarkDailyPrice(
                benchmark_id=benchmark.id, trade_date=trade_date, open=Decimal("100"), high=Decimal("101"),
                low=Decimal("99"), close=Decimal(str(100 + offset)), volume=None, change_rate=Decimal("0"),
            ))
    session.commit()
    return dataset, run


def test_input_selection_pins_latest_complete_dataset_rs_and_benchmark_closes():
    session = _session()
    dataset, rs_run = _complete_inputs(session)

    selected = select_backtest_inputs(
        session, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
        rebalance_dates=[date(2024, 1, 3), date(2024, 1, 5)],
    )

    assert selected.dataset.id == dataset.id
    assert selected.dataset_manifest_hash == dataset.final_manifest_hash
    assert selected.rs_run.id == rs_run.id
    assert selected.rs_run.formula_version == "rs-v1"
    assert {item.market for item in selected.benchmark_snapshots} == {"KOSPI", "KOSDAQ"}
    assert all(len(item.snapshot_hash) == 64 for item in selected.benchmark_snapshots)


def test_input_selection_rejects_missing_benchmark_or_required_rs():
    session = _session()
    _complete_inputs(session)
    benchmark = session.query(Benchmark).filter_by(benchmark_code="KOSDAQ").one()
    session.query(BenchmarkDailyPrice).filter_by(benchmark_id=benchmark.id, trade_date=date(2024, 1, 4)).delete()
    session.commit()

    with pytest.raises(BacktestInputUnavailable) as unavailable:
        select_backtest_inputs(
            session, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
            rebalance_dates=[date(2024, 1, 3)],
        )
    assert any(reason.code == "benchmark_price_missing" for reason in unavailable.value.reasons)


def test_data_unavailable_attempt_keeps_an_auditable_run_without_invented_dataset_lineage():
    session = _session()
    repository = BacktestRepository(session)
    strategy = repository.create_strategy(name="입력 부족", config={})
    run = repository.record_data_unavailable_run(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], reasons=[{"code": "dataset_missing", "detail": "no verified dataset"}],
    )
    assert run.status == "data_unavailable"
    assert run.dataset_id is None
    assert "dataset_missing" in (run.error_detail or "")


def test_preparation_persists_missing_inputs_as_data_unavailable_run():
    session = _session()
    strategy = BacktestRepository(session).create_strategy(name="입력 부족", config={})
    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    assert run.status == "data_unavailable"
    assert "dataset_missing" in (run.error_detail or "")


def test_preparation_pins_the_selected_rs_formula_version_on_queued_run():
    session = _session()
    _, rs_run = _complete_inputs(session)
    strategy = BacktestRepository(session).create_strategy(name="고정 입력", config={})
    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    assert run.status == "queued"
    assert run.rs_formula_version == rs_run.formula_version


def test_queue_never_claims_a_second_run_while_one_is_running():
    session = _session()
    _complete_inputs(session)
    strategy = BacktestRepository(session).create_strategy(name="대기열", config={})
    service = BacktestRunPreparationService(session)
    first = service.prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    second = service.prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    repository = BacktestRepository(session)
    assert repository.claim_next_run().run_id == first.run_id
    assert repository.claim_next_run() is None
    assert repository.get_run(second.run_id).status == "queued"


def test_operator_auth_uses_hashed_sessions_rotated_csrf_and_lockout():
    session = _session()
    service = BacktestOperatorAuthService(session, password="operator-secret")
    preauth_token, csrf = service.issue_pre_auth(request_subject="127.0.0.1")
    with pytest.raises(InvalidCsrfToken):
        service.login(preauth_token=preauth_token, csrf_token="wrong", password="operator-secret", request_subject="127.0.0.1")
    for _ in range(4):
        with pytest.raises(PermissionError):
            service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.1")
    with pytest.raises(TimeoutError):
        service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.1")

    session2 = _session()
    service2 = BacktestOperatorAuthService(session2, password="operator-secret")
    preauth_token, csrf = service2.issue_pre_auth(request_subject="127.0.0.2")
    operator_token, operator_csrf = service2.login(
        preauth_token=preauth_token, csrf_token=csrf, password="operator-secret", request_subject="127.0.0.2"
    )
    assert operator_token != preauth_token
    assert operator_csrf != csrf
    assert service2.require_operator(operator_token, operator_csrf) is not None
    service2.logout(operator_token, operator_csrf)
    assert service2.find_operator(operator_token) is None


def test_backtest_auth_router_requires_preauth_csrf_then_rotates_the_cookie_session(monkeypatch):
    session = _session()
    app = FastAPI()
    app.include_router(backtest_auth.router, prefix="/api/v1/backtests")

    def database_override():
        yield session

    app.dependency_overrides[get_db_session] = database_override
    monkeypatch.setattr(
        backtest_auth, "get_settings",
        lambda: type("Settings", (), {
            "backtest_operator_password": "operator-secret", "backtest_session_hours": 8,
            "backtest_login_max_failures": 5, "backtest_login_lock_minutes": 15,
        })(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        csrf_response = client.get("/api/v1/backtests/auth/csrf")
        assert csrf_response.status_code == 200
        csrf_token = csrf_response.json()["csrf_token"]
        assert "HttpOnly" in csrf_response.headers["set-cookie"]
        assert "Secure" in csrf_response.headers["set-cookie"]
        bad_login = client.post("/api/v1/backtests/auth/login", json={"password": "operator-secret"})
        assert bad_login.status_code == 403
        login_response = client.post(
            "/api/v1/backtests/auth/login", json={"password": "operator-secret"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert login_response.status_code == 200
        operator_csrf = login_response.json()["csrf_token"]
        assert operator_csrf != csrf_token
        logout_response = client.post("/api/v1/backtests/auth/logout", headers={"X-CSRF-Token": operator_csrf})
        assert logout_response.status_code == 200
