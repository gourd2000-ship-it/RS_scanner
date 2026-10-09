"""Deterministic close-signal / next-open domestic equity simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.services.backtest.strategy import (
    INDICATOR_FIELDS,
    ConditionContext,
    INITIAL_CAPITAL,
    condition_fields_by_side,
    evaluate_condition,
    validate_config,
)
from app.services.backtest.schedule import rebalance_dates_for_trading_days


ZERO = Decimal("0")


@dataclass(frozen=True)
class MarketBar:
    trade_date: date
    instrument_id: int
    code: str
    market: str
    open: Decimal
    close: Decimal
    volume: int
    rs_rating: int | None
    rank_in_market: int | None
    volume_sma50: Decimal | None = None
    atr14: Decimal | None = None


@dataclass
class SimOrder:
    sequence: int
    instrument_id: int
    code: str
    side: str
    signal_date: date
    execution_date: date
    quantity: int
    execution_price: Decimal
    fee: Decimal
    slippage: Decimal
    reason_codes: list[str]
    status: str = "filled"


@dataclass
class SimTrade:
    instrument_id: int
    code: str
    entry_date: date
    exit_date: date
    quantity: int
    entry_value: Decimal
    exit_value: Decimal
    profit_loss: Decimal
    return_rate: Decimal
    exit_reason_codes: list[str]


@dataclass
class DailySnapshot:
    trade_date: date
    cash: Decimal
    holdings_value: Decimal
    net_asset_value: Decimal
    holdings: dict[str, dict[str, Any]]


@dataclass
class SimulationResult:
    daily_equity: list[DailySnapshot]
    orders: list[SimOrder]
    trades: list[SimTrade]
    metrics: dict[str, Any]


@dataclass
class _Position:
    instrument_id: int
    code: str
    quantity: int
    entry_date: date
    entry_value: Decimal
    average_price: Decimal
    entry_day_index: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _metric(value: Decimal | None, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "null_reason": reason}


def _metrics(snapshots: list[DailySnapshot], trades: list[SimTrade]) -> dict[str, Any]:
    final = snapshots[-1].net_asset_value if snapshots else INITIAL_CAPITAL
    cumulative = final / INITIAL_CAPITAL - 1
    calendar_days = max((snapshots[-1].trade_date - snapshots[0].trade_date).days, 1) if snapshots else 1
    cagr = (final / INITIAL_CAPITAL) ** (Decimal(365) / Decimal(calendar_days)) - 1
    peak = INITIAL_CAPITAL
    mdd = ZERO
    for row in snapshots:
        peak = max(peak, row.net_asset_value)
        mdd = max(mdd, (peak - row.net_asset_value) / peak)
    wins = [trade.profit_loss for trade in trades if trade.profit_loss > ZERO]
    losses = [trade.profit_loss for trade in trades if trade.profit_loss < ZERO]
    decisive = len(wins) + len(losses)
    gross_profit, gross_loss = sum(wins, ZERO), abs(sum(losses, ZERO))
    return {
        "initial_capital": _metric(INITIAL_CAPITAL), "final_asset_value": _metric(final),
        "cumulative_return": _metric(cumulative), "cagr": _metric(cagr), "mdd": _metric(mdd),
        "win_rate": _metric(Decimal(len(wins)) / Decimal(decisive) if decisive else None, None if decisive else "no_decisive_trades"),
        "gross_profit": _metric(gross_profit), "gross_loss": _metric(gross_loss),
        "profit_loss_ratio": _metric(gross_profit / gross_loss if gross_loss else None, None if gross_loss else "no_losing_trades"),
        "average_win": _metric(gross_profit / len(wins) if wins else None, None if wins else "no_winning_trades"),
        "average_loss": _metric(gross_loss / len(losses) if losses else None, None if losses else "no_losing_trades"),
        "average_profit_loss_ratio": _metric(
            (gross_profit / len(wins)) / (gross_loss / len(losses)) if wins and losses else None,
            None if wins and losses else ("no_winning_trades" if not wins else "no_losing_trades"),
        ),
        "completed_trade_count": _metric(Decimal(len(trades))),
    }


def simulate(
    config: dict[str, Any], bars: list[MarketBar], *, start_date: date | None = None, end_date: date | None = None,
) -> SimulationResult:
    """Run an in-memory deterministic simulation over pinned dataset rows."""
    config = validate_config(config)
    bars = sorted((bar for bar in bars if bar.market in config["markets"]), key=lambda b: (b.trade_date, b.code))
    by_date: dict[date, list[MarketBar]] = {}
    by_key: dict[tuple[int, date], MarketBar] = {}
    for bar in bars:
        by_date.setdefault(bar.trade_date, []).append(bar)
        by_key[(bar.instrument_id, bar.trade_date)] = bar
    dates = sorted(day for day in by_date if (start_date is None or day >= start_date) and (end_date is None or day <= end_date))
    if not dates:
        return SimulationResult([], [], [], _metrics([], []))
    buy_review_dates = set(rebalance_dates_for_trading_days(dates, config["rebalance_interval_days"]))
    _validate_indicator_inputs(config, by_date, dates, buy_review_dates)
    history: dict[int, list[MarketBar]] = {}
    cash, positions = INITIAL_CAPITAL, {}
    orders: list[SimOrder] = []
    trades: list[SimTrade] = []
    snapshots: list[DailySnapshot] = []
    pending: dict[date, list[tuple[str, _Position | MarketBar, list[str], date]]] = {}
    sequence = 0
    # Warm history is only used for N-day return conditions; it cannot create
    # signals or orders before the pinned run range.
    for warm_day in sorted(day for day in by_date if start_date is not None and day < start_date):
        for warm_bar in by_date[warm_day]:
            history.setdefault(warm_bar.instrument_id, []).append(warm_bar)
    for day_index, today in enumerate(dates):
        today_bars = {bar.instrument_id: bar for bar in by_date[today]}
        # Sells are processed before buys on the same opening price.
        scheduled = pending.pop(today, [])
        for side in ("sell", "buy"):
            buy_batch_nav = buy_batch_target = buy_batch_budget = None
            if side == "buy":
                holdings_at_open = sum((today_bars[p.instrument_id].open * p.quantity for p in positions.values() if p.instrument_id in today_bars), ZERO)
                buy_batch_nav = cash + holdings_at_open
                buy_batch_target = min(buy_batch_nav / Decimal(config["max_holdings"]), buy_batch_nav * Decimal(str(config["max_position_weight"])))
                buy_batch_budget = max(ZERO, cash - buy_batch_nav * Decimal(str(config["cash_reserve_ratio"])))
            for action, subject, reasons, signal_date in [item for item in scheduled if item[0] == side]:
                if side == "sell":
                    position = subject  # type: ignore[assignment]
                    assert isinstance(position, _Position)
                    bar = today_bars.get(position.instrument_id)
                    if bar is None:
                        sequence += 1
                        orders.append(SimOrder(sequence, position.instrument_id, position.code, "sell", signal_date, today, 0, ZERO, ZERO, ZERO, reasons, "unfilled"))
                        continue
                    price = bar.open * (Decimal(1) - Decimal(str(config["sell_slippage_rate"])))
                    gross = price * position.quantity
                    fee = _money(gross * Decimal(str(config["sell_fee_rate"])))
                    proceeds = _money(gross - fee)
                    cash += proceeds
                    sequence += 1
                    orders.append(SimOrder(sequence, position.instrument_id, position.code, "sell", signal_date, today, position.quantity, price, fee, price - bar.open, reasons))
                    profit = proceeds - position.entry_value
                    trades.append(SimTrade(position.instrument_id, position.code, position.entry_date, today, position.quantity, position.entry_value, proceeds, profit, profit / position.entry_value if position.entry_value else ZERO, reasons))
                    positions.pop(position.instrument_id, None)
                else:
                    bar = subject  # type: ignore[assignment]
                    assert isinstance(bar, MarketBar)
                    current = today_bars.get(bar.instrument_id)
                    if current is None:
                        sequence += 1
                        orders.append(SimOrder(sequence, bar.instrument_id, bar.code, "buy", signal_date, today, 0, ZERO, ZERO, ZERO, reasons, "unfilled"))
                        continue
                    if bar.instrument_id in positions:
                        continue
                    # One post-sell, pre-buy NAV and reserve budget applies to
                    # every selection in this opening batch.
                    assert buy_batch_target is not None and buy_batch_budget is not None
                    price = current.open * (Decimal(1) + Decimal(str(config["buy_slippage_rate"])))
                    unit_cost = price * (Decimal(1) + Decimal(str(config["buy_fee_rate"])))
                    quantity = int((min(buy_batch_target, buy_batch_budget) / unit_cost).to_integral_value(rounding=ROUND_DOWN))
                    if quantity <= 0:
                        continue
                    gross = price * quantity
                    fee = _money(gross * Decimal(str(config["buy_fee_rate"])))
                    cost = _money(gross + fee)
                    cash -= cost
                    buy_batch_budget = max(ZERO, buy_batch_budget - cost)
                    sequence += 1
                    orders.append(SimOrder(sequence, bar.instrument_id, bar.code, "buy", signal_date, today, quantity, price, fee, price - current.open, reasons))
                    positions[bar.instrument_id] = _Position(bar.instrument_id, bar.code, quantity, today, cost, cost / quantity, day_index)
        # Mark portfolio at close, then evaluate today's close signals.
        holdings_value = sum((today_bars[p.instrument_id].close * p.quantity for p in positions.values() if p.instrument_id in today_bars), ZERO)
        nav = _money(cash + holdings_value)
        snapshot_holdings = {p.code: {"instrument_id": p.instrument_id, "quantity": p.quantity, "average_price": str(p.average_price)} for p in positions.values()}
        snapshots.append(DailySnapshot(today, _money(cash), _money(holdings_value), nav, snapshot_holdings))
        is_end = day_index == len(dates) - 1
        next_date = dates[day_index + 1] if not is_end else None
        if is_end:
            for position in list(positions.values()):
                bar = today_bars[position.instrument_id]
                price = bar.close * (Decimal(1) - Decimal(str(config["sell_slippage_rate"])))
                gross = price * position.quantity
                fee = _money(gross * Decimal(str(config["sell_fee_rate"])))
                proceeds = _money(gross - fee)
                cash += proceeds
                sequence += 1
                orders.append(SimOrder(sequence, position.instrument_id, position.code, "sell", today, today, position.quantity, price, fee, price - bar.close, ["forced_close"]))
                profit = proceeds - position.entry_value
                trades.append(SimTrade(position.instrument_id, position.code, position.entry_date, today, position.quantity, position.entry_value, proceeds, profit, profit / position.entry_value if position.entry_value else ZERO, ["forced_close"]))
                positions.pop(position.instrument_id, None)
            snapshots[-1] = DailySnapshot(today, _money(cash), ZERO, _money(cash), {})
            break
        for position in list(positions.values()):
            bar = today_bars.get(position.instrument_id)
            if bar is None:
                continue
            reasons: list[str] = []
            context = _context(bar, history.get(bar.instrument_id, []) + [bar])
            if evaluate_condition(config["sell_conditions"], context):
                reasons.append("sell_condition")
            close_return = bar.close / position.average_price - 1
            if config.get("stop_loss_rate") is not None and close_return <= Decimal(str(config["stop_loss_rate"])):
                reasons.append("stop_loss")
            if config.get("take_profit_rate") is not None and close_return >= Decimal(str(config["take_profit_rate"])):
                reasons.append("take_profit")
            if config.get("max_holding_days") is not None and day_index - position.entry_day_index + 1 >= config["max_holding_days"]:
                reasons.append("max_holding_days")
            if reasons:
                pending.setdefault(next_date, []).append(("sell", position, reasons, today))
        if today in buy_review_dates:
            pending_exit_ids = {
                candidate.instrument_id for action, candidate, _, _ in pending.get(next_date, [])
                if action == "sell" and isinstance(candidate, _Position)
            }
            candidates = []
            for bar in by_date[today]:
                if bar.instrument_id in positions and bar.instrument_id not in pending_exit_ids:
                    continue
                context = _context(bar, history.get(bar.instrument_id, []) + [bar])
                if evaluate_condition(config["buy_conditions"], context):
                    candidates.append(bar)
            vacancies = max(0, config["max_holdings"] - (len(positions) - len(pending_exit_ids)))
            for bar in sorted(candidates, key=lambda b: (-(b.rs_rating if b.rs_rating is not None else -1), b.code))[:vacancies]:
                pending.setdefault(next_date, []).append(("buy", bar, ["buy_condition"], today))
        for bar in by_date[today]:
            history.setdefault(bar.instrument_id, []).append(bar)
    return SimulationResult(snapshots, orders, trades, _metrics(snapshots, trades))


def _context(bar: MarketBar, history: list[MarketBar]) -> ConditionContext:
    returns = {n: bar.close / history[-n - 1].close - 1 for n in range(1, len(history)) if history[-n - 1].close != ZERO}
    return ConditionContext(
        Decimal(bar.rs_rating) if bar.rs_rating is not None else None,
        Decimal(bar.rank_in_market) if bar.rank_in_market is not None else None,
        bar.close, Decimal(bar.volume), returns,
        Decimal(str(bar.volume_sma50)) if bar.volume_sma50 is not None else None,
        Decimal(str(bar.atr14)) if bar.atr14 is not None else None,
    )


def _validate_indicator_inputs(
    config: dict[str, Any], by_date: dict[date, list[MarketBar]], dates: list[date],
    buy_review_dates: set[date],
) -> None:
    side_fields = condition_fields_by_side(config)
    buy_fields = set(side_fields["buy"]) & INDICATOR_FIELDS
    sell_fields = set(side_fields["sell"]) & INDICATOR_FIELDS
    if not buy_fields and not sell_fields:
        return
    for trade_date in dates:
        required_fields = set(sell_fields)
        if trade_date in buy_review_dates:
            required_fields.update(buy_fields)
        if not required_fields:
            continue
        for bar in by_date[trade_date]:
            for field in sorted(required_fields):
                raw_value = getattr(bar, field)
                if raw_value is None:
                    raise ValueError(
                        f"indicator_value_missing: {field} for instrument {bar.instrument_id} on {trade_date}"
                    )
                value = Decimal(str(raw_value))
                if not value.is_finite() or value < ZERO:
                    raise ValueError(
                        f"indicator_evidence_mismatch: {field} for instrument {bar.instrument_id} on {trade_date}"
                    )
