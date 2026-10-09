"""Validated immutable strategy configuration and condition evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


INITIAL_CAPITAL = Decimal("10000000")
INDICATOR_FIELDS = frozenset({"volume_sma50", "atr14"})
FIELDS = frozenset({"rs_rating", "rank_in_market", "close", "volume", "return_n_days", *INDICATOR_FIELDS})
OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq"})
MARKETS = frozenset({"KOSPI", "KOSDAQ"})


class StrategyValidationError(ValueError):
    pass


def _number(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise StrategyValidationError(f"{label} must be numeric")
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise StrategyValidationError(f"{label} must be numeric") from exc
    if not parsed.is_finite():
        raise StrategyValidationError(f"{label} must be finite")
    return parsed


def validate_condition(node: Any) -> None:
    if not isinstance(node, dict):
        raise StrategyValidationError("condition must be an object")
    kind = node.get("type")
    if kind == "group":
        if node.get("operator") not in {"AND", "OR"}:
            raise StrategyValidationError("condition group operator must be AND or OR")
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise StrategyValidationError("condition group must have at least one child")
        for child in children:
            validate_condition(child)
        return
    if kind == "rule":
        if node.get("field") not in FIELDS:
            raise StrategyValidationError("unsupported condition field")
        if node.get("operator") not in OPERATORS:
            raise StrategyValidationError("unsupported condition operator")
        condition_value = _number(node.get("value"), "condition value")
        if node["field"] in INDICATOR_FIELDS and condition_value < 0:
            raise StrategyValidationError("indicator condition value must be non-negative")
        n_days = node.get("n_days")
        if node["field"] == "return_n_days":
            if isinstance(n_days, dict):
                n_days = n_days.get("lookback_trading_days")
                node["n_days"] = n_days
            if not isinstance(n_days, int) or isinstance(n_days, bool) or n_days < 1:
                raise StrategyValidationError("return_n_days requires n_days >= 1")
        elif n_days is not None:
            raise StrategyValidationError("n_days is only valid for return_n_days")
        return
    raise StrategyValidationError("condition type must be group or rule")


def return_lookback_days(config: dict[str, Any]) -> int:
    maximum = 0
    def visit(node: Any) -> None:
        nonlocal maximum
        if not isinstance(node, dict):
            return
        if node.get("type") == "rule" and node.get("field") == "return_n_days":
            maximum = max(maximum, int(node["n_days"]))
        for child in node.get("children", []):
            visit(child)
    visit(config.get("buy_conditions"))
    visit(config.get("sell_conditions"))
    return maximum


def condition_fields(node: Any) -> frozenset[str]:
    """Return the rule fields contained in a validated or stored condition tree."""
    found: set[str] = set()

    def visit(current: Any) -> None:
        if not isinstance(current, dict):
            return
        if current.get("type") == "rule" and isinstance(current.get("field"), str):
            found.add(current["field"])
        for child in current.get("children", []):
            visit(child)

    visit(node)
    return frozenset(found)


def condition_fields_by_side(config: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Return buy/sell condition fields while accepting the persisted API aliases."""
    return {
        "buy": condition_fields(config.get("buy_conditions", config.get("entry_conditions"))),
        "sell": condition_fields(config.get("sell_conditions", config.get("exit_conditions"))),
    }


def indicator_kinds_for_config(config: dict[str, Any]) -> frozenset[str]:
    fields = set().union(*condition_fields_by_side(config).values())
    return frozenset(
        kind for field, kind in (("volume_sma50", "volume_sma"), ("atr14", "atr"))
        if field in fields
    )


def validate_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise StrategyValidationError("strategy config must be an object")
    config = dict(config)
    market = config.pop("market", None)
    if market is not None and "markets" not in config:
        if market == "BOTH":
            config["markets"] = ["KOSPI", "KOSDAQ"]
        elif market in MARKETS:
            config["markets"] = [market]
        else:
            raise StrategyValidationError("market must be KOSPI, KOSDAQ, or BOTH")
    for external, internal in {
        "rebalance_interval_trading_days": "rebalance_interval_days",
        "max_holding_trading_days": "max_holding_days",
        "entry_conditions": "buy_conditions",
        "exit_conditions": "sell_conditions",
    }.items():
        if external in config and internal not in config:
            config[internal] = config.pop(external)
    required = {
        "markets", "rebalance_interval_days", "max_holdings", "max_position_weight",
        "cash_reserve_ratio", "buy_conditions", "sell_conditions", "buy_fee_rate",
        "sell_fee_rate", "buy_slippage_rate", "sell_slippage_rate",
    }
    missing = required - set(config)
    if missing:
        raise StrategyValidationError(f"missing strategy config: {', '.join(sorted(missing))}")
    markets = config["markets"]
    if not isinstance(markets, list) or not markets or not set(markets) <= MARKETS or len(set(markets)) != len(markets):
        raise StrategyValidationError("markets must contain KOSPI and/or KOSDAQ once")
    for key in ("rebalance_interval_days", "max_holdings"):
        if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 1:
            raise StrategyValidationError(f"{key} must be an integer >= 1")
    weight = _number(config["max_position_weight"], "max_position_weight")
    reserve = _number(config["cash_reserve_ratio"], "cash_reserve_ratio")
    if weight <= 0 or weight > 1 or reserve < 0 or reserve >= 1:
        raise StrategyValidationError("position weight or cash reserve ratio is outside its allowed range")
    for key in ("buy_fee_rate", "sell_fee_rate", "buy_slippage_rate", "sell_slippage_rate"):
        rate = _number(config[key], key)
        if rate < 0 or rate >= 1:
            raise StrategyValidationError(f"{key} must be between 0 and 1")
    for key in ("stop_loss_rate", "take_profit_rate"):
        value = config.get(key)
        if value is not None:
            rate = _number(value, key)
            if (key == "stop_loss_rate" and rate >= 0) or (key == "take_profit_rate" and rate <= 0):
                raise StrategyValidationError(f"{key} has an invalid sign")
    hold = config.get("max_holding_days")
    if hold is not None and (not isinstance(hold, int) or isinstance(hold, bool) or hold < 1):
        raise StrategyValidationError("max_holding_days must be an integer >= 1")
    validate_condition(config["buy_conditions"])
    validate_condition(config["sell_conditions"])
    config["market"] = "BOTH" if set(config["markets"]) == MARKETS else config["markets"][0]
    config["rebalance_interval_trading_days"] = config["rebalance_interval_days"]
    config["max_holding_trading_days"] = config.get("max_holding_days")
    return config


@dataclass(frozen=True)
class ConditionContext:
    rs_rating: Decimal | None
    rank_in_market: Decimal | None
    close: Decimal
    volume: Decimal
    return_n_days: dict[int, Decimal]
    volume_sma50: Decimal | None = None
    atr14: Decimal | None = None


def evaluate_condition(node: dict[str, Any], context: ConditionContext) -> bool:
    if node["type"] == "group":
        results = [evaluate_condition(child, context) for child in node["children"]]
        return all(results) if node["operator"] == "AND" else any(results)
    field = node["field"]
    if field == "return_n_days":
        actual = context.return_n_days.get(node["n_days"])
    else:
        actual = getattr(context, field)
    if actual is None:
        return False
    expected = _number(node["value"], "condition value")
    return {
        "gt": actual > expected, "gte": actual >= expected, "lt": actual < expected,
        "lte": actual <= expected, "eq": actual == expected,
    }[node["operator"]]
