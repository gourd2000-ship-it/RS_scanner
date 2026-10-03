"""Worker-only orchestration from a pinned run to immutable result rows."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetPrice, BacktestDatasetRs
from app.models.backtest_run import BacktestRun
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.simulator import MarketBar, SimulationResult, simulate


class BacktestExecutionService:
    """Execute only a run already claimed by ``BacktestQueueWorker``."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BacktestRepository(session)

    def execute(self, run: BacktestRun) -> SimulationResult:
        if run.status != "running":
            raise ValueError("only a claimed running backtest may be executed")
        dataset = self.session.get(BacktestDataset, run.backtest_dataset_id)
        if dataset is None:
            raise ValueError("pinned dataset is unavailable")
        rows = self.session.execute(
            select(BacktestDatasetPrice, BacktestDatasetRs)
            .outerjoin(BacktestDatasetRs, (
                (BacktestDatasetRs.backtest_dataset_rs_run_id == run.backtest_dataset_rs_run_id)
                & (BacktestDatasetRs.instrument_id == BacktestDatasetPrice.instrument_id)
                & (BacktestDatasetRs.trade_date == BacktestDatasetPrice.trade_date)
                & (BacktestDatasetRs.market == BacktestDatasetPrice.market)
            ))
            .where(
                BacktestDatasetPrice.backtest_dataset_id == run.backtest_dataset_id,
                BacktestDatasetPrice.trade_date >= (dataset.preparation_start or run.range_start),
                BacktestDatasetPrice.trade_date <= run.range_end,
                BacktestDatasetPrice.market.in_(run.markets),
            )
            .order_by(BacktestDatasetPrice.trade_date, BacktestDatasetPrice.code)
        ).all()
        bars = [
            MarketBar(
                trade_date=price.trade_date, instrument_id=price.instrument_id, code=price.code,
                market=price.market, open=Decimal(price.open), close=Decimal(price.close), volume=price.volume,
                rs_rating=rs.rs_rating if rs is not None and rs.status == "available" else None,
                rank_in_market=rs.rank_in_market if rs is not None and rs.status == "available" else None,
            )
            for price, rs in rows
        ]
        result = simulate(run.strategy_version.config, bars, start_date=run.range_start, end_date=run.range_end)
        for daily in result.daily_equity:
            self.repository.add_daily_equity(
                run.run_id, trade_date=daily.trade_date, cash=daily.cash,
                holdings_value=daily.holdings_value, net_asset_value=daily.net_asset_value, holdings=daily.holdings,
            )
        for order in result.orders:
            self.repository.add_order(
                run.run_id, sequence=order.sequence, instrument_id=order.instrument_id, code=order.code,
                side=order.side, signal_date=order.signal_date, execution_date=order.execution_date,
                quantity=order.quantity, execution_price=order.execution_price, fee=order.fee,
                slippage=order.slippage, reason_codes=order.reason_codes, status=order.status,
            )
        for trade in result.trades:
            self.repository.add_trade(
                run.run_id, instrument_id=trade.instrument_id, code=trade.code,
                entry_date=trade.entry_date, exit_date=trade.exit_date, quantity=trade.quantity,
                entry_value=trade.entry_value, exit_value=trade.exit_value, profit_loss=trade.profit_loss,
                return_rate=trade.return_rate, exit_reason_codes=trade.exit_reason_codes,
            )
        run.metrics = _json_metrics(result.metrics)
        self.session.flush()
        self.repository.transition_run(run.run_id, "completed")
        return result

    def execute_next(self) -> SimulationResult | None:
        run = self.repository.claim_next_run()
        if run is None:
            return None
        try:
            return self.execute(run)
        except Exception as exc:
            self.repository.transition_run(run.run_id, "failed", error_code="simulation_failed", error_detail=str(exc))
            raise


def _json_metrics(metrics: dict) -> dict:
    """Decimal values need a stable JSON representation for immutable results."""
    return {
        key: {"value": str(value["value"]) if value["value"] is not None else None, "null_reason": value["null_reason"]}
        for key, value in metrics.items()
    }
