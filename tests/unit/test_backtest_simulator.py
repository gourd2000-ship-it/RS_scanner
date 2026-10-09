from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetPrice, BacktestDatasetRs, BacktestDatasetRsRun
from app.repositories.backtest_repository import BacktestRepository, BenchmarkSnapshotInput
from app.services.backtest.execution import BacktestExecutionService
from app.api.v1.endpoints.backtest_execution import _version, get_run as get_run_detail
from app.services.backtest.simulator import MarketBar, simulate
from app.services.backtest.strategy import StrategyValidationError, validate_config


def _config(**changes):
    value = {
        "markets": ["KOSPI"], "rebalance_interval_days": 1, "max_holdings": 1,
        "max_position_weight": "1", "cash_reserve_ratio": "0", "buy_fee_rate": "0.001",
        "sell_fee_rate": "0.001", "buy_slippage_rate": "0.01", "sell_slippage_rate": "0.01",
        "buy_conditions": {"type": "group", "operator": "AND", "children": [{"type": "rule", "field": "rs_rating", "operator": "gte", "value": 80}]},
        "sell_conditions": {"type": "group", "operator": "AND", "children": [{"type": "rule", "field": "rs_rating", "operator": "lt", "value": 80}]},
        "stop_loss_rate": "-0.1", "take_profit_rate": "0.2", "max_holding_days": None,
    }
    value.update(changes)
    return value


def _bars():
    first = date(2024, 1, 2)
    data = []
    for index, (opening, closing, rating) in enumerate(((100, 100, 90), (100, 100, 90), (110, 110, 70), (115, 115, 70))):
        data.append(MarketBar(first + timedelta(days=index), 1, "000001", "KOSPI", Decimal(opening), Decimal(closing), 1000, rating, 1))
    return data


def test_simulator_uses_close_signal_then_next_open_and_forces_end_close():
    result = simulate(_config(), _bars())
    assert result.orders[0].side == "buy"
    assert result.orders[0].signal_date == date(2024, 1, 2)
    assert result.orders[0].execution_date == date(2024, 1, 3)
    assert result.orders[0].execution_price == Decimal("101.00")
    assert result.orders[1].side == "sell"
    assert result.orders[1].signal_date == date(2024, 1, 4)
    assert result.orders[1].execution_date == date(2024, 1, 5)
    assert result.trades[0].exit_reason_codes == ["sell_condition"]
    assert result.metrics["win_rate"]["value"] == Decimal("1")


def test_simulator_combines_exit_reasons_and_keeps_cash_when_cap_prevents_buy():
    result = simulate(_config(stop_loss_rate="-0.1", take_profit_rate="0.01"), _bars())
    assert set(result.trades[0].exit_reason_codes) == {"sell_condition", "take_profit"}
    capped = simulate(_config(max_position_weight="0.000001"), _bars())
    assert capped.orders == []
    assert capped.daily_equity[-1].cash == Decimal("10000000.00")


def test_forced_end_close_is_a_completed_trade_and_metric_null_reasons_are_explicit():
    config = _config(sell_conditions={"type": "group", "operator": "AND", "children": [{"type": "rule", "field": "rs_rating", "operator": "gt", "value": 1000}]}, take_profit_rate=None)
    result = simulate(config, _bars())
    assert result.trades[-1].exit_reason_codes == ["forced_close"]
    assert result.metrics["profit_loss_ratio"]["null_reason"] in {None, "no_losing_trades"}


def test_invalid_condition_or_rate_is_rejected_before_persistence():
    with pytest.raises(StrategyValidationError):
        validate_config(_config(buy_conditions={"type": "group", "operator": "AND", "children": []}))
    with pytest.raises(StrategyValidationError):
        validate_config(_config(buy_fee_rate="1"))
    with pytest.raises(StrategyValidationError):
        validate_config(_config(buy_conditions={"type": "rule", "field": "unknown", "operator": "gt", "value": 1}))
    with pytest.raises(StrategyValidationError, match="finite"):
        validate_config(_config(buy_fee_rate="NaN"))
    with pytest.raises(StrategyValidationError, match="finite"):
        validate_config(_config(max_position_weight="Infinity"))
    with pytest.raises(StrategyValidationError, match="non-negative"):
        validate_config(_config(buy_conditions={"type": "rule", "field": "volume_sma50", "operator": "gte", "value": -1}))
    with pytest.raises(StrategyValidationError, match="non-negative"):
        validate_config(_config(sell_conditions={"type": "rule", "field": "atr14", "operator": "eq", "value": "-0.01"}))


def test_browser_configuration_aliases_are_canonicalized_and_return_lookback_is_accepted():
    config = _config()
    for key in ("markets", "rebalance_interval_days", "max_holding_days", "buy_conditions", "sell_conditions"):
        config.pop(key, None)
    config.update({
        "market": "BOTH", "rebalance_interval_trading_days": 3, "max_holding_trading_days": 7,
        "entry_conditions": {"type": "rule", "field": "return_n_days", "operator": "gt", "value": 0, "n_days": {"lookback_trading_days": 5}},
        "exit_conditions": {"type": "rule", "field": "rs_rating", "operator": "lt", "value": 20},
    })
    canonical = validate_config(config)
    assert canonical["markets"] == ["KOSPI", "KOSDAQ"]
    assert canonical["rebalance_interval_days"] == 3
    assert canonical["buy_conditions"]["n_days"] == 5


def test_rebalance_replaces_pending_full_exit_and_freezes_equal_weight_batch_budget():
    first = date(2024, 1, 2)
    bars = [
        MarketBar(first, 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 90, 1),
        MarketBar(first, 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 0, 2),
        MarketBar(first + timedelta(days=1), 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 70, 2),
        MarketBar(first + timedelta(days=1), 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 90, 1),
        MarketBar(first + timedelta(days=2), 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 70, 2),
        MarketBar(first + timedelta(days=2), 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 90, 1),
    ]
    result = simulate(_config(), bars)
    day_three = [order for order in result.orders if order.execution_date == first + timedelta(days=2)]
    assert [order.side for order in day_three[:2]] == ["sell", "buy"]
    assert day_three[1].code == "000002"

    equal_bars = [
        MarketBar(first, 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 90, 1),
        MarketBar(first, 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 90, 2),
        MarketBar(first + timedelta(days=1), 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 90, 1),
        MarketBar(first + timedelta(days=1), 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 90, 2),
        MarketBar(first + timedelta(days=2), 1, "000001", "KOSPI", Decimal("100"), Decimal("100"), 1, 90, 1),
        MarketBar(first + timedelta(days=2), 2, "000002", "KOSPI", Decimal("200"), Decimal("200"), 1, 90, 2),
    ]
    equal = simulate(_config(max_holdings=2, max_position_weight="1", sell_conditions={"type": "rule", "field": "rs_rating", "operator": "gt", "value": 1000}, take_profit_rate=None), equal_bars)
    buys = [order for order in equal.orders if order.side == "buy"]
    assert len(buys) == 2
    assert abs((buys[0].quantity * buys[0].execution_price) - (buys[1].quantity * buys[1].execution_price)) <= Decimal("200")
    assert equal.metrics["mdd"]["value"] >= 0
    assert "average_profit_loss_ratio" in equal.metrics


def test_simulator_compares_indicator_conditions_as_decimal_and_requires_values_on_signal_days():
    bars = [
        MarketBar(
            bar.trade_date, bar.instrument_id, bar.code, bar.market, bar.open, bar.close,
            bar.volume, bar.rs_rating, bar.rank_in_market,
            volume_sma50=Decimal("1000.125"), atr14=Decimal("2.50"),
        )
        for bar in _bars()
    ]
    config = _config(
        buy_conditions={"type": "rule", "field": "volume_sma50", "operator": "eq", "value": "1000.125"},
        sell_conditions={"type": "rule", "field": "rs_rating", "operator": "gt", "value": "1000"},
    )
    result = simulate(config, bars)
    assert result.orders[0].side == "buy"
    assert result.trades[0].exit_reason_codes == ["forced_close"]

    missing = [
        MarketBar(
            bar.trade_date, bar.instrument_id, bar.code, bar.market, bar.open, bar.close,
            bar.volume, bar.rs_rating, bar.rank_in_market,
        )
        for bar in _bars()
    ]
    with pytest.raises(ValueError, match="indicator_value_missing: volume_sma50"):
        simulate(config, missing)


def test_claimed_run_persists_daily_holdings_metrics_orders_and_trades():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    manifest = {"publication_scope": "complete_segments_only"}
    manifest_hash = sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    dataset = BacktestDataset(dataset_id="dataset", manifest_hash="a" * 64, final_manifest_hash=manifest_hash,
        range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
        reconstruction_mode="fixture", adjustment_policy="fixture", policy_version="v1", manifest=manifest, status="active")
    session.add(dataset)
    session.flush()
    rs_run = BacktestDatasetRsRun(backtest_dataset_id=dataset.id, formula_version="v1", policy_version="v1", input_hash="b" * 64, result_hash="c" * 64, status="completed", manifest={})
    session.add(rs_run)
    session.flush()
    for bar in _bars():
        session.add(BacktestDatasetPrice(backtest_dataset_id=dataset.id, instrument_id=bar.instrument_id, source_symbol_id=1,
            code=bar.code, name=bar.code, market=bar.market, trade_date=bar.trade_date, open=bar.open, high=bar.open,
            low=bar.open, close=bar.close, volume=bar.volume, change_rate=Decimal("0"), provider="fixture"))
        session.add(BacktestDatasetRs(backtest_dataset_rs_run_id=rs_run.id, backtest_dataset_id=dataset.id,
            instrument_id=bar.instrument_id, code=bar.code, market=bar.market, trade_date=bar.trade_date,
            status="available", required_observations=1, available_observations=1, rs_rating=bar.rs_rating,
            rank_in_market=bar.rank_in_market, input_hash="d" * 64))
    repository = BacktestRepository(session)
    strategy = repository.create_strategy(name="fixture", config=_config())
    snapshots = tuple(BenchmarkSnapshotInput(market, market, "0" * 64, tuple((bar.trade_date, Decimal("100")) for bar in _bars())) for market in ("KOSPI", "KOSDAQ"))
    queued = repository.enqueue_run(strategy_version_id=strategy.versions[0].id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=manifest_hash, rs_run_id=rs_run.id, rs_result_hash=rs_run.result_hash,
        range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"], benchmark_snapshots=snapshots)
    claimed = repository.claim_next_run()
    assert claimed is not None and claimed.run_id == queued.run_id
    result = BacktestExecutionService(session).execute(claimed)
    session.commit()
    stored = repository.get_run(queued.run_id)
    assert stored is not None and stored.status == "completed"
    assert len(stored.daily_equity) == len(_bars())
    assert stored.daily_equity[1].holdings["000001"]["quantity"] > 0
    assert stored.metrics["win_rate"]["null_reason"] is None
    assert len(stored.orders) == len(result.orders)
    assert len(stored.trades) == len(result.trades)
    detail = get_run_detail(queued.run_id, orders_page=1, orders_size=1, trades_page=1, trades_size=1, _operator=object(), session=session)
    assert detail.orders["total_count"] == len(result.orders)
    assert len(detail.orders["items"]) == 1
    assert detail.trades["total_count"] == len(result.trades)
    assert len(detail.trades["items"]) == 1


def test_version_response_exposes_strategy_identity_and_configuration_hash():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = BacktestRepository(session)
    strategy = repository.create_strategy(name="version fixture", config=_config())
    initial_updated_at = strategy.updated_at
    version = repository.add_strategy_version(strategy.id, config=_config(max_holdings=2))
    assert strategy.updated_at >= initial_updated_at
    response = _version(version)
    assert response.strategy_id == strategy.strategy_id
    assert response.configuration_hash == version.config_hash
