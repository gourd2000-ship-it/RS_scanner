"""Deterministic 50-trading-day simple moving average for volume."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256

from app.services.indicators.contracts import EmaInputRow, EmaStatus, canonical_json


VOLUME_SMA_PERIOD = 50
VOLUME_SMA_FORMULA_VERSION = "volume-sma-50-v1"


@dataclass(frozen=True)
class VolumeSmaValue:
    trade_date: date
    value: Decimal | None
    status: EmaStatus
    reason_code: str | None
    available_observations: int

    def material(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "value": self.value,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "available_observations": self.available_observations,
        }


@dataclass(frozen=True)
class VolumeSmaResult:
    values: tuple[VolumeSmaValue, ...]
    result_hash: str


def compute_volume_sma50(rows: tuple[EmaInputRow, ...]) -> VolumeSmaResult:
    """Calculate an arithmetic 50-day volume average without silent gaps.

    A zero volume is an eligible observed value.  Any unavailable input clears
    the rolling window: the next value cannot be exposed until 50 fresh,
    consecutive eligible observations are present.
    """
    ordered = tuple(sorted(rows, key=lambda row: row.trade_date))
    if len({row.trade_date for row in ordered}) != len(ordered):
        raise ValueError("Volume SMA rows must have unique trade dates")
    window: deque[int] = deque(maxlen=VOLUME_SMA_PERIOD)
    output: list[VolumeSmaValue] = []
    for row in ordered:
        reason = row.effective_reason()
        if reason is not None:
            window.clear()
            output.append(VolumeSmaValue(
                trade_date=row.trade_date,
                value=None,
                status=EmaStatus.DATA_UNAVAILABLE,
                reason_code=reason.value,
                available_observations=0,
            ))
            continue
        assert row.volume is not None
        window.append(row.volume)
        count = len(window)
        if count < VOLUME_SMA_PERIOD:
            output.append(VolumeSmaValue(
                trade_date=row.trade_date,
                value=None,
                status=EmaStatus.WARMING_UP,
                reason_code="warming_up",
                available_observations=count,
            ))
            continue
        output.append(VolumeSmaValue(
            trade_date=row.trade_date,
            value=sum(Decimal(value) for value in window) / Decimal(VOLUME_SMA_PERIOD),
            status=EmaStatus.AVAILABLE,
            reason_code=None,
            available_observations=count,
        ))
    values = tuple(output)
    return VolumeSmaResult(
        values=values,
        result_hash=sha256(canonical_json([value.material() for value in values]).encode("utf-8")).hexdigest(),
    )
