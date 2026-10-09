"""Explicitly run a bounded number of queued backtest simulations.

This script is not imported by the API or started by application startup.
Invoke it as the separately managed batch service when the worker is approved
and the required database migrations are already applied.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.services.backtest.worker import BacktestExecutionWorker, BacktestWorkerOutcome


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-runs",
        type=int,
        default=1,
        help="maximum runs to claim before exit (1 by default; stops sooner when the queue is empty)",
    )
    parser.add_argument(
        "--fail-stale-run",
        metavar="RUN_ID",
        help="mark a verified interrupted running run failed; requires --confirm-worker-stopped",
    )
    parser.add_argument(
        "--confirm-worker-stopped",
        action="store_true",
        help="attest that the worker process for --fail-stale-run is no longer active",
    )
    return parser


def run(max_runs: int, *, worker: BacktestExecutionWorker | None = None) -> list[BacktestWorkerOutcome]:
    if max_runs < 1:
        raise ValueError("--max-runs must be at least 1")
    execution_worker = worker or BacktestExecutionWorker(SessionLocal)
    outcomes: list[BacktestWorkerOutcome] = []
    for _ in range(max_runs):
        outcome = execution_worker.run_once()
        if outcome.status == "idle":
            break
        outcomes.append(outcome)
        logger.info("backtest worker run_id=%s status=%s", outcome.run_id, outcome.status)
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.fail_stale_run:
        if not args.confirm_worker_stopped:
            parser.error("--fail-stale-run requires --confirm-worker-stopped")
        if args.max_runs != 1:
            parser.error("--max-runs cannot be combined with --fail-stale-run")
        try:
            outcome = BacktestExecutionWorker(SessionLocal).fail_stale_run_after_worker_stop(args.fail_stale_run)
        except Exception as exc:
            logger.error("stale run reconciliation failed: %s", type(exc).__name__)
            return 1
        logger.info("backtest worker run_id=%s status=%s", outcome.run_id, outcome.status)
        return 0
    if args.confirm_worker_stopped:
        parser.error("--confirm-worker-stopped requires --fail-stale-run")
    try:
        outcomes = run(args.max_runs)
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:
        logger.error("backtest worker stopped before completing: %s", type(exc).__name__)
        return 1
    return 1 if any(outcome.status == "failed" for outcome in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
