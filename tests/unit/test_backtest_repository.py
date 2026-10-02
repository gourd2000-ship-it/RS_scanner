"""백테스트 실행 저장소의 고정 입력과 대기열 규칙을 검증한다."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetRsRun
from app.models.backtest_run import BacktestRun
from app.repositories.backtest_repository import BacktestRepository, BenchmarkSnapshotInput


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _inputs(session: Session) -> tuple[BacktestDataset, BacktestDatasetRsRun]:
    dataset = BacktestDataset(
        dataset_id="dataset-complete-1",
        manifest_hash="a" * 64,
        final_manifest_hash="b" * 64,
        range_start=date(2020, 1, 2),
        range_end=date(2020, 12, 30),
        markets=["KOSPI", "KOSDAQ"],
        reconstruction_mode="historical_reconstructed",
        adjustment_policy="fixture:1",
        policy_version="v1",
        manifest={"publication_scope": "complete_segments_only"},
        status="active",
    )
    session.add(dataset)
    session.flush()
    rs_run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id,
        formula_version="rs-v1",
        policy_version="v1",
        input_hash="c" * 64,
        result_hash="d" * 64,
        manifest={},
    )
    session.add(rs_run)
    session.flush()
    return dataset, rs_run


def _snapshots() -> tuple[BenchmarkSnapshotInput, BenchmarkSnapshotInput]:
    return (
        BenchmarkSnapshotInput(
            market="KOSPI", benchmark_code="KOSPI", snapshot_hash="e" * 64,
            prices=((date(2020, 1, 2), Decimal("2000")),),
        ),
        BenchmarkSnapshotInput(
            market="KOSDAQ", benchmark_code="KOSDAQ", snapshot_hash="f" * 64,
            prices=((date(2020, 1, 2), Decimal("650")),),
        ),
    )


def test_strategy_versions_and_queued_run_pin_all_reproducibility_inputs():
    session = _session()
    repository = BacktestRepository(session)
    dataset, rs_run = _inputs(session)
    strategy = repository.create_strategy(name="RS 상위", config={"entry": {"all": []}})
    version = strategy.versions[0]

    run = repository.enqueue_run(
        strategy_version_id=version.id,
        dataset_id=dataset.dataset_id,
        dataset_manifest_hash=dataset.final_manifest_hash,
        rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash,
        range_start=date(2020, 1, 2),
        range_end=date(2020, 12, 30),
        markets=["KOSPI"],
        benchmark_snapshots=_snapshots(),
    )

    assert run.status == "queued"
    assert run.dataset_manifest_hash == "b" * 64
    assert run.rs_result_hash == "d" * 64
    assert {row.market: row.snapshot_hash for row in run.benchmark_snapshots} == {
        "KOSPI": "e" * 64,
        "KOSDAQ": "f" * 64,
    }
    assert run.benchmark_snapshots[0].prices[0].close in {Decimal("2000"), Decimal("650")}


def test_enqueue_rejects_non_complete_or_mismatched_frozen_dataset_inputs():
    session = _session()
    repository = BacktestRepository(session)
    dataset, rs_run = _inputs(session)
    version = repository.create_strategy(name="표본", config={}).versions[0]
    dataset.manifest = {"publication_scope": "audit_coverage"}

    with pytest.raises(ValueError, match="complete_segments_only"):
        repository.enqueue_run(
            strategy_version_id=version.id,
            dataset_id=dataset.dataset_id,
            dataset_manifest_hash=dataset.final_manifest_hash,
            rs_run_id=rs_run.id,
            rs_result_hash=rs_run.result_hash,
            range_start=date(2020, 1, 2), range_end=date(2020, 12, 30), markets=["KOSPI"],
            benchmark_snapshots=_snapshots(),
        )


def test_queue_claim_and_cancel_only_allow_documented_status_transitions():
    session = _session()
    repository = BacktestRepository(session)
    dataset, rs_run = _inputs(session)
    version = repository.create_strategy(name="표본", config={}).versions[0]
    first = repository.enqueue_run(
        strategy_version_id=version.id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=dataset.final_manifest_hash, rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash, range_start=date(2020, 1, 2),
        range_end=date(2020, 12, 30), markets=["KOSPI"], benchmark_snapshots=_snapshots(),
    )
    second = repository.enqueue_run(
        strategy_version_id=version.id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=dataset.final_manifest_hash, rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash, range_start=date(2020, 1, 2),
        range_end=date(2020, 12, 30), markets=["KOSPI"], benchmark_snapshots=_snapshots(),
    )

    assert repository.cancel_queued_run(second.run_id).status == "cancelled"
    assert repository.claim_next_run().run_id == first.run_id
    assert first.status == "running"
    with pytest.raises(ValueError, match="queued"):
        repository.cancel_queued_run(first.run_id)
    assert repository.transition_run(first.run_id, "completed").status == "completed"
    with pytest.raises(ValueError, match="terminal"):
        repository.transition_run(first.run_id, "failed")


def test_completed_runs_and_strategy_versions_cannot_be_changed_through_repository():
    session = _session()
    repository = BacktestRepository(session)
    dataset, rs_run = _inputs(session)
    strategy = repository.create_strategy(name="표본", config={"entry": {}})
    version = strategy.versions[0]
    run = repository.enqueue_run(
        strategy_version_id=version.id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=dataset.final_manifest_hash, rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash, range_start=date(2020, 1, 2),
        range_end=date(2020, 12, 30), markets=["KOSPI"], benchmark_snapshots=_snapshots(),
    )
    repository.transition_run(run.run_id, "data_unavailable", error_code="benchmark_missing")

    with pytest.raises(ValueError, match="immutable"):
        repository.add_strategy_version(strategy.id, config={"entry": {"all": ["changed"]}}, version=1)
    with pytest.raises(ValueError, match="terminal"):
        repository.transition_run(run.run_id, "running")
    assert session.get(BacktestRun, run.id).status == "data_unavailable"


def test_operator_session_and_login_lockout_store_only_hashes():
    session = _session()
    repository = BacktestRepository(session)
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    subject_hash = "1" * 64
    operator_session = repository.create_operator_session(
        session_token_hash="2" * 64,
        operator_subject_hash=subject_hash,
        expires_at=now + timedelta(hours=8),
    )
    assert operator_session.session_token_hash == "2" * 64
    assert "password" not in operator_session.__table__.columns
    assert repository.get_active_operator_session(session_token_hash="2" * 64, now=now) is not None
    repository.revoke_operator_session(session_token_hash="2" * 64, now=now)
    assert repository.get_active_operator_session(session_token_hash="2" * 64, now=now) is None
    assert repository.record_login_success(subject_hash=subject_hash, now=now).succeeded is True

    for _ in range(4):
        assert repository.record_login_failure(subject_hash=subject_hash, now=now) is None
    lockout = repository.record_login_failure(subject_hash=subject_hash, now=now)
    assert lockout is not None
    assert repository.is_login_locked(subject_hash=subject_hash, now=now) is True
