"""Worker-only orchestration from a pinned run to immutable result rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
    BacktestDatasetPrice,
    BacktestDatasetRs,
)
from app.models.backtest_run import BacktestRun
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.simulator import MarketBar, SimulationResult, simulate
from app.services.backtest.strategy import indicator_kinds_for_config


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
        indicator_values = self._indicator_values(run, dataset)
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
                volume_sma50=indicator_values.get((price.instrument_id, price.trade_date), {}).get("volume_sma50"),
                atr14=indicator_values.get((price.instrument_id, price.trade_date), {}).get("atr14"),
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

    def _indicator_values(self, run: BacktestRun, dataset: BacktestDataset) -> dict[tuple[int, date], dict[str, Decimal | None]]:
        required_kinds = indicator_kinds_for_config(run.strategy_version.config)
        pins = {
            "volume_sma": (run.volume_sma50_snapshot_id, run.volume_sma50_snapshot_hash),
            "atr": (run.atr14_snapshot_id, run.atr14_snapshot_hash),
        }
        if {kind for kind, (snapshot_id, _) in pins.items() if snapshot_id is not None} != set(required_kinds):
            raise ValueError("pinned indicator snapshots do not match the strategy conditions")

        field_by_kind = {"volume_sma": "volume_sma50", "atr": "atr14"}
        values: dict[tuple[int, date], dict[str, Decimal | None]] = {}
        for kind in sorted(required_kinds):
            snapshot_id, snapshot_hash = pins[kind]
            snapshot = self.session.get(BacktestDatasetIndicatorSnapshot, snapshot_id)
            if (
                snapshot is None
                or snapshot.status != "complete"
                or snapshot.backtest_dataset_id != dataset.id
                or snapshot.dataset_id != dataset.dataset_id
                or snapshot.dataset_manifest_hash != run.dataset_manifest_hash
                or snapshot.content_hash != snapshot_hash
                or snapshot.indicator_kind != kind
            ):
                raise ValueError(f"pinned {kind} indicator snapshot is unavailable or changed")
            rows = self.session.scalars(
                select(BacktestDatasetIndicatorSnapshotRow).where(
                    BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
                    BacktestDatasetIndicatorSnapshotRow.trade_date >= (dataset.preparation_start or run.range_start),
                    BacktestDatasetIndicatorSnapshotRow.trade_date <= run.range_end,
                )
            )
            field = field_by_kind[kind]
            for row in rows:
                key = (row.instrument_id, row.trade_date)
                if row.status == "available":
                    if row.value is None or not row.value.is_finite() or row.value < 0 or row.reason_code is not None:
                        raise ValueError(f"indicator_evidence_mismatch: {kind} row {row.id}")
                    value: Decimal | None = Decimal(row.value)
                elif row.status == "warming_up":
                    if row.value is not None or row.reason_code != "warming_up":
                        raise ValueError(f"indicator_evidence_mismatch: {kind} row {row.id}")
                    value = None
                elif row.status == "data_unavailable":
                    if row.value is not None or not row.reason_code or row.reason_code == "warming_up":
                        raise ValueError(f"indicator_evidence_mismatch: {kind} row {row.id}")
                    value = None
                else:
                    raise ValueError(f"indicator_evidence_mismatch: {kind} row {row.id}")
                values.setdefault(key, {})[field] = value
        return values

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
