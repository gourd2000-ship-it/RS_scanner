"""Shared immutable observation scope for optional daily indicators."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.data_quality import PriceObservation
from app.models.indicator import PriceObservationIdentitySnapshot
from app.services.batch.context import BatchContext
from app.services.indicators.contracts import EmaSourcePolicy


def expected_trade_dates(
    context: BatchContext,
    *,
    target_date: date,
    policy: EmaSourcePolicy,
) -> tuple[date, ...]:
    """Use observed policy dates as the daily-run exchange calendar evidence.

    Every selected instrument receives the same date set, so a missing source
    row remains an explicit unavailable input rather than disappearing from
    that instrument's calculation.
    """
    rows = context.session.scalars(
        select(PriceObservation.trade_date)
        .where(
            PriceObservation.provider == policy.provider,
            PriceObservation.adjustment_type == policy.adjustment_type,
            PriceObservation.parser_version.in_(policy.allowed_parser_versions),
            PriceObservation.observed_at <= policy.observation_cutoff,
            PriceObservation.trade_date <= target_date,
        )
        .distinct()
        .order_by(PriceObservation.trade_date)
    )
    return tuple(rows)


def eligible_instrument_ids(
    context: BatchContext,
    *,
    target_date: date,
    policy: EmaSourcePolicy,
) -> tuple[int, ...]:
    rows = context.session.scalars(
        select(PriceObservationIdentitySnapshot.instrument_id)
        .join(
            PriceObservation,
            PriceObservation.id == PriceObservationIdentitySnapshot.price_observation_id,
        )
        .where(
            PriceObservationIdentitySnapshot.instrument_id.is_not(None),
            PriceObservationIdentitySnapshot.mapping_status == "matched",
            PriceObservation.provider == policy.provider,
            PriceObservation.adjustment_type == policy.adjustment_type,
            PriceObservation.parser_version.in_(policy.allowed_parser_versions),
            PriceObservation.observed_at <= policy.observation_cutoff,
            PriceObservation.trade_date <= target_date,
        )
        .distinct()
        .order_by(PriceObservationIdentitySnapshot.instrument_id)
    )
    return tuple(rows)
