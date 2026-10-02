"""Persist either a reproducible queued run or its precise input failure."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.backtest_run import BacktestRun
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.input_selection import BacktestInputUnavailable, select_backtest_inputs


class BacktestRunPreparationService:
    """Keeps input discovery out of HTTP endpoints and the simulation worker."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BacktestRepository(session)

    def prepare(
        self, *, strategy_version_id: int, range_start: date, range_end: date, markets: list[str],
        rebalance_dates: list[date], return_lookback_days: int = 0,
    ) -> BacktestRun:
        try:
            selected = select_backtest_inputs(
                self.session, range_start=range_start, range_end=range_end, markets=markets,
                rebalance_dates=rebalance_dates, return_lookback_days=return_lookback_days,
                market_closed_dates=get_settings().market_closed_dates,
            )
        except BacktestInputUnavailable as exc:
            reasons = [
                {"code": reason.code, "detail": reason.detail, "instrument_id": reason.instrument_id,
                 "trade_date": reason.trade_date, "field": reason.field}
                for reason in exc.reasons
            ]
            # No candidate dataset/RS is invented if discovery failed.
            return self.repository.record_data_unavailable_run(
                strategy_version_id=strategy_version_id, range_start=range_start, range_end=range_end,
                markets=markets, reasons=reasons,
            )
        return self.repository.enqueue_run(
            strategy_version_id=strategy_version_id, dataset_id=selected.dataset.dataset_id,
            dataset_manifest_hash=selected.dataset_manifest_hash, rs_run_id=selected.rs_run.id,
            rs_result_hash=selected.rs_run.result_hash, range_start=range_start, range_end=range_end,
            markets=markets, benchmark_snapshots=selected.benchmark_snapshots,
            candidate_exclusions=[
                {"instrument_id": instrument_id, "market": market, "trade_date": trade_date.isoformat(), "reason": "insufficient_return_lookback"}
                for instrument_id, market, trade_date in sorted(selected.lookback_excluded_candidates)
            ],
        )
