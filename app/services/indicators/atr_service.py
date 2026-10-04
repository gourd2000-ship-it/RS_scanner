"""Read-only ATR input assembly from immutable selected observations."""
from __future__ import annotations
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.data_quality import PriceObservation
from app.services.indicators.atr import AtrInput, AtrResult, compute_atr14
from app.services.indicators.contracts import EmaSourcePolicy
from app.services.indicators.input_selector import EmaInputSelector

class AtrService:
    def __init__(self, session: Session): self.session = session; self.selector = EmaInputSelector(session)
    def calculate(self, *, instrument_id: int, trade_dates: tuple[date, ...], policy: EmaSourcePolicy) -> AtrResult:
        rows = self.selector.select_rows(instrument_id=instrument_id, trade_dates=trade_dates, policy=policy)
        ids = [row.observation_id for row in rows if row.observation_id is not None]
        observations = {row.id: row for row in self.session.scalars(select(PriceObservation).where(PriceObservation.id.in_(ids)))}
        inputs = tuple(AtrInput(row.trade_date, observations[row.observation_id].high if row.observation_id in observations else None, observations[row.observation_id].low if row.observation_id in observations else None, row.close, row.effective_reason().value if row.effective_reason() else None) for row in rows)
        return compute_atr14(inputs)
