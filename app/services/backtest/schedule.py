"""Shared trading-day schedule helpers for preparation and simulation."""

from __future__ import annotations

from datetime import date
from collections.abc import Iterable


def rebalance_dates_for_trading_days(trading_dates: Iterable[date], interval: int) -> tuple[date, ...]:
    """Return the simulator's buy-review dates from its actual ordered bars."""
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise ValueError("rebalance interval must be an integer >= 1")
    return tuple(sorted(set(trading_dates))[::interval])
