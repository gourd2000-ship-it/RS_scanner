"""Read-only Volume MA50 orchestration over immutable OHLCV evidence."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.services.indicators.contracts import EmaSourcePolicy
from app.services.indicators.input_selector import EmaInputSelector
from app.services.indicators.volume_sma import VolumeSmaResult, compute_volume_sma50


class VolumeSmaService:
    def __init__(self, session: Session) -> None:
        self.selector = EmaInputSelector(session)

    def calculate(
        self,
        *,
        instrument_id: int,
        trade_dates: tuple[date, ...],
        policy: EmaSourcePolicy,
    ) -> VolumeSmaResult:
        rows = self.selector.select_rows(
            instrument_id=instrument_id,
            trade_dates=trade_dates,
            policy=policy,
        )
        return compute_volume_sma50(rows)
