"""Explicit orchestration for the separately managed backtest queue worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest_run import BacktestDailyEquity, BacktestOrder, BacktestRun, BacktestTrade
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.execution import BacktestExecutionService
from app.services.backtest.queue import BacktestQueueWorker


@dataclass(frozen=True)
class BacktestWorkerOutcome:
    run_id: str | None
    status: str
    error_code: str | None = None


class BacktestExecutionWorker:
    """Claim and execute queued runs in one serialized transaction."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def run_once(self) -> BacktestWorkerOutcome:
        # Commit the claim separately so the operator API can observe running
        # while the potentially long simulation is in progress.
        with self.session_factory() as session:
            with session.begin():
                run = BacktestQueueWorker(session).claim_next()
                run_id = run.run_id if run is not None else None
        if run_id is None:
            return BacktestWorkerOutcome(run_id=None, status="idle")

        try:
            with self.session_factory() as session:
                with session.begin():
                    run = session.scalar(select(BacktestRun).where(BacktestRun.run_id == run_id))
                    if run is None or run.status != "running":
                        raise RuntimeError("claimed backtest run is no longer running")
                    # Output rows and completed status commit atomically. A
                    # calculation exception rolls back this savepoint, leaving
                    # the outer transaction available to persist `failed`.
                    try:
                        with session.begin_nested():
                            BacktestExecutionService(session).execute(run)
                    except Exception as exc:
                        BacktestRepository(session).transition_run(
                            run_id,
                            "failed",
                            error_code="simulation_failed",
                            error_detail=_safe_error_detail(exc),
                        )
                        return BacktestWorkerOutcome(
                            run_id=run_id,
                            status="failed",
                            error_code="simulation_failed",
                        )
            return BacktestWorkerOutcome(run_id=run_id, status="completed")
        except Exception as exc:
            # This also covers failures before the savepoint could be opened.
            # If the DB is unavailable, the reconciliation command can handle
            # the still-running claim after the worker process is confirmed dead.
            with self.session_factory() as session:
                with session.begin():
                    BacktestRepository(session).transition_run(
                        run_id,
                        "failed",
                        error_code="simulation_failed",
                        error_detail=_safe_error_detail(exc),
                    )
            return BacktestWorkerOutcome(
                run_id=run_id,
                status="failed",
                error_code="simulation_failed",
            )

    def fail_stale_run_after_worker_stop(self, run_id: str) -> BacktestWorkerOutcome:
        """Mark a verified orphaned claim failed without retrying or duplicating outputs."""
        with self.session_factory() as session:
            with session.begin():
                repository = BacktestRepository(session)
                run = repository.get_run(run_id)
                if run is None:
                    raise KeyError(f"backtest run not found: {run_id}")
                if run.status != "running":
                    raise ValueError("only a running backtest can be reconciled as interrupted")
                if run.metrics is not None or any(
                    session.scalar(select(model.id).where(model.backtest_run_id == run.id).limit(1)) is not None
                    for model in (BacktestDailyEquity, BacktestOrder, BacktestTrade)
                ):
                    raise ValueError("stale running run has persisted output; inspect it before reconciliation")
                repository.transition_run(
                    run_id,
                    "failed",
                    error_code="worker_interrupted",
                    error_detail="operator_reconciled_after_worker_stop",
                )
        return BacktestWorkerOutcome(run_id=run_id, status="failed", error_code="worker_interrupted")


def _safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, (ValueError, KeyError)):
        return f"{type(exc).__name__}: {str(exc)[:900]}"
    return f"worker execution failed ({type(exc).__name__})"
