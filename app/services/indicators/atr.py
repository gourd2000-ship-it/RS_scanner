"""Deterministic Wilder ATR(14) calculation over validated daily bars."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256

from app.services.indicators.contracts import EmaStatus, canonical_json

ATR_PERIOD = 14

@dataclass(frozen=True)
class AtrValue:
    trade_date: date
    value: Decimal | None
    status: EmaStatus
    reason_code: str | None
    available_observations: int
    def material(self):
        return {"trade_date": self.trade_date, "value": self.value, "status": self.status.value, "reason_code": self.reason_code, "available_observations": self.available_observations}

@dataclass(frozen=True)
class AtrResult:
    values: tuple[AtrValue, ...]
    result_hash: str

@dataclass(frozen=True)
class AtrInput:
    trade_date: date
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    reason_code: str | None = None

def compute_atr14(rows: tuple[AtrInput, ...]) -> AtrResult:
    ordered = tuple(sorted(rows, key=lambda row: row.trade_date))
    if len({row.trade_date for row in ordered}) != len(ordered):
        raise ValueError("ATR rows must have unique trade dates")
    output: list[AtrValue] = []
    true_ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    atr: Decimal | None = None
    for row in ordered:
        reason = row.reason_code
        if reason is not None or row.close is None or row.high is None or row.low is None:
            true_ranges.clear(); previous_close = None; atr = None
            output.append(AtrValue(row.trade_date, None, EmaStatus.DATA_UNAVAILABLE, reason or "invalid_ohlcv", 0)); continue
        high, low = row.high, row.low
        tr = high - low if previous_close is None else max(high - low, abs(high - previous_close), abs(low - previous_close))
        previous_close = row.close
        if atr is None:
            true_ranges.append(tr)
            if len(true_ranges) < ATR_PERIOD:
                output.append(AtrValue(row.trade_date, None, EmaStatus.WARMING_UP, "warming_up", len(true_ranges))); continue
            atr = sum(true_ranges) / Decimal(ATR_PERIOD)
        else:
            atr = (atr * Decimal(ATR_PERIOD - 1) + tr) / Decimal(ATR_PERIOD)
        output.append(AtrValue(row.trade_date, atr, EmaStatus.AVAILABLE, None, ATR_PERIOD))
    values = tuple(output)
    return AtrResult(values, sha256(canonical_json([item.material() for item in values]).encode()).hexdigest())
