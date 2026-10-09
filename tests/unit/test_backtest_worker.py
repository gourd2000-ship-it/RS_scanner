from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.base import Base
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetPrice, BacktestDatasetRs, BacktestDatasetRsRun
from app.models.backtest_run import BacktestDailyEquity, BacktestRun
from app.repositories.backtest_repository import BacktestRepository, BenchmarkSnapshotInput
from app.services.backtest.execution import BacktestExecutionService
from app.services.backtest.worker import BacktestExecutionWorker


def _config() -> dict:
    return {
        "markets": ["KOSPI"], "rebalance_interval_days": 1, "max_holdings": 1,
        "max_position_weight": "1", "cash_reserve_ratio": "0", "buy_fee_rate": "0",
        "sell_fee_rate": "0", "buy_slippage_rate": "0", "sell_slippage_rate": "0",
        "buy_conditions": {"type": "rule", "field": "rs_rating", "operator": "gte", "value": 80},
        "sell_conditions": {"type": "rule", "field": "rs_rating", "operator": "lt", "value": 80},
        "stop_loss_rate": None, "take_profit_rate": None, "max_holding_days": None,
    }


def _queued_run(session, run_id: str) -> BacktestRun:
    manifest = {"publication_scope": "complete_segments_only", "fixture_run_id": run_id}
    manifest_hash = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    dataset = BacktestDataset(
        dataset_id=f"worker-fixture-dataset-{run_id}",
        manifest_hash=sha256(f"dataset:{run_id}".encode()).hexdigest(),
        final_manifest_hash=manifest_hash,
        range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
        reconstruction_mode="fixture", adjustment_policy="fixture:1", policy_version="v1",
        manifest=manifest, status="active",
    )
    session.add(dataset)
    session.flush()
    rs_run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id, formula_version="rs-v1", policy_version="v1",
        input_hash="b" * 64, result_hash="c" * 64, status="completed", manifest={},
    )
    session.add(rs_run)
    session.flush()
    dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(4)]
    for index, trade_date in enumerate(dates):
        price = Decimal(100 + index)
        session.add(BacktestDatasetPrice(
            backtest_dataset_id=dataset.id, instrument_id=1, source_symbol_id=1,
            code="000001", name="fixture", market="KOSPI", trade_date=trade_date,
            open=price, high=price, low=price, close=price, volume=100,
            change_rate=Decimal("0"), provider="fixture",
        ))
        session.add(BacktestDatasetRs(
            backtest_dataset_rs_run_id=rs_run.id, backtest_dataset_id=dataset.id,
            instrument_id=1, code="000001", market="KOSPI", trade_date=trade_date,
            status="available", required_observations=1, available_observations=1,
            rs_rating=90, rank_in_market=1, input_hash="d" * 64,
        ))
    repository = BacktestRepository(session)
    strategy = repository.create_strategy(name=f"worker {run_id}", config=_config())
    benchmark_snapshots = tuple(
        BenchmarkSnapshotInput(
            market=market, benchmark_code=market, snapshot_hash="e" * 64,
            prices=tuple((trade_date, Decimal("100")) for trade_date in dates),
        )
        for market in ("KOSPI", "KOSDAQ")
    )
    return repository.enqueue_run(
        strategy_version_id=strategy.versions[0].id,
        dataset_id=dataset.dataset_id,
        dataset_manifest_hash=manifest_hash,
        rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash,
        range_start=dates[0], range_end=dates[-1], markets=["KOSPI"],
        benchmark_snapshots=benchmark_snapshots, run_id=run_id,
    )


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_worker_completes_once_and_does_not_replay_terminal_run(session_factory):
    with session_factory.begin() as session:
        queued = _queued_run(session, "worker-complete")

    worker = BacktestExecutionWorker(session_factory)
    outcome = worker.run_once()
    assert outcome.run_id == queued.run_id
    assert outcome.status == "completed"
    assert worker.run_once().status == "idle"

    with session_factory() as session:
        stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == queued.run_id))
        assert stored is not None and stored.status == "completed"
        assert session.scalar(
            select(func.count(BacktestDailyEquity.id)).where(BacktestDailyEquity.backtest_run_id == stored.id)
        ) == 4


def test_worker_cancellation_and_existing_running_run_do_not_claim_another_item(session_factory):
    with session_factory.begin() as session:
        first = _queued_run(session, "worker-running")
        second = _queued_run(session, "worker-cancelled")
        BacktestRepository(session).cancel_queued_run(second.run_id)
        claimed = BacktestRepository(session).claim_next_run()
        assert claimed is not None and claimed.run_id == first.run_id

    outcome = BacktestExecutionWorker(session_factory).run_once()
    assert outcome.status == "idle"
    with session_factory() as session:
        assert session.scalar(select(BacktestRun.status).where(BacktestRun.run_id == first.run_id)) == "running"
        assert session.scalar(select(BacktestRun.status).where(BacktestRun.run_id == second.run_id)) == "cancelled"


def test_worker_failure_rolls_back_partial_results_and_is_not_retried(session_factory, monkeypatch):
    with session_factory.begin() as session:
        queued = _queued_run(session, "worker-failed")

    def fail_after_partial_result(self, run):
        self.repository.add_daily_equity(
            run.run_id, trade_date=run.range_start, cash=Decimal("1"),
            holdings_value=Decimal("0"), net_asset_value=Decimal("1"),
        )
        raise ValueError("fixture simulation failure")

    monkeypatch.setattr(BacktestExecutionService, "execute", fail_after_partial_result)
    worker = BacktestExecutionWorker(session_factory)
    outcome = worker.run_once()
    assert outcome.run_id == queued.run_id
    assert outcome.status == "failed"
    assert outcome.error_code == "simulation_failed"
    assert worker.run_once().status == "idle"

    with session_factory() as session:
        stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == queued.run_id))
        assert stored is not None and stored.status == "failed"
        assert stored.error_detail == "ValueError: fixture simulation failure"
        assert session.scalar(
            select(func.count(BacktestDailyEquity.id)).where(BacktestDailyEquity.backtest_run_id == stored.id)
        ) == 0


def test_worker_interruption_rolls_back_partial_results_and_requires_reconciliation(session_factory, monkeypatch):
    with session_factory.begin() as session:
        queued = _queued_run(session, "worker-interrupted")

    def interrupt_after_partial_result(self, run):
        self.repository.add_daily_equity(
            run.run_id, trade_date=run.range_start, cash=Decimal("1"),
            holdings_value=Decimal("0"), net_asset_value=Decimal("1"),
        )
        raise SystemExit("simulated process interruption")

    monkeypatch.setattr(BacktestExecutionService, "execute", interrupt_after_partial_result)
    with pytest.raises(SystemExit, match="simulated process interruption"):
        BacktestExecutionWorker(session_factory).run_once()

    with session_factory() as session:
        stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == queued.run_id))
        assert stored is not None and stored.status == "running"
        assert stored.started_at is not None
        assert session.scalar(
            select(func.count(BacktestDailyEquity.id)).where(BacktestDailyEquity.backtest_run_id == stored.id)
        ) == 0

    outcome = BacktestExecutionWorker(session_factory).fail_stale_run_after_worker_stop(queued.run_id)
    assert outcome.status == "failed"
    assert outcome.error_code == "worker_interrupted"
    assert BacktestExecutionWorker(session_factory).run_once().status == "idle"

    with session_factory() as session:
        stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == queued.run_id))
        assert stored is not None and stored.status == "failed"


def test_stale_run_reconciliation_refuses_persisted_output(session_factory):
    with session_factory.begin() as session:
        queued = _queued_run(session, "worker-stale-with-output")
        claimed = BacktestRepository(session).claim_next_run()
        assert claimed is not None and claimed.run_id == queued.run_id
    with session_factory.begin() as session:
        BacktestRepository(session).add_daily_equity(
            queued.run_id, trade_date=queued.range_start, cash=Decimal("1"),
            holdings_value=Decimal("0"), net_asset_value=Decimal("1"),
        )

    with pytest.raises(ValueError, match="persisted output"):
        BacktestExecutionWorker(session_factory).fail_stale_run_after_worker_stop(queued.run_id)

    with session_factory() as session:
        stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == queued.run_id))
        assert stored is not None and stored.status == "running"
