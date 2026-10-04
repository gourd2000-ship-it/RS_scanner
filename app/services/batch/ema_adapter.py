"""Daily-batch adapter for the immutable EMA calculation service.

The adapter deliberately owns no crawl job and never reads ``DailyPrice`` or
the current ``Symbol.instrument_id`` relationship.  It only starts after the
daily clean validation and hands immutable observation evidence to the EMA
service.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.core.config import EMA_DAILY_OBSERVATION_BOUNDARY, Settings, get_settings
from app.models.data_quality import PriceObservation
from app.models.indicator import PriceObservationIdentitySnapshot
from app.services.batch.context import BatchContext
from app.services.indicators.calculation_service import EmaCalculationService
from app.services.indicators.contracts import EmaSourcePolicy


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmaBatchOutcome:
    """A non-throwing result for the optional EMA batch step."""

    outcome: str
    processed: int = 0
    failed: int = 0
    reason: str | None = None

    @classmethod
    def completed(cls, *, processed: int) -> "EmaBatchOutcome":
        return cls(outcome="completed", processed=processed)

    @classmethod
    def skipped(cls, reason: str) -> "EmaBatchOutcome":
        return cls(outcome="skipped", failed=1, reason=reason)

    @classmethod
    def failure(cls, *, processed: int, failed: int, reason: str) -> "EmaBatchOutcome":
        return cls(outcome="failed", processed=processed, failed=max(failed, 1), reason=reason)

    @property
    def has_errors(self) -> bool:
        return self.outcome != "completed"

    def checkpoint_metadata(self) -> str:
        metadata = {"outcome": self.outcome}
        if self.reason is not None:
            metadata["reason"] = self.reason
        return json.dumps(metadata, sort_keys=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "processed": self.processed,
            "failed": self.failed,
            "reason": self.reason,
        }


def ema_enabled(settings: Settings | None = None) -> bool:
    return bool(getattr(settings or get_settings(), "ema_enabled", False))


def calculate_daily_ema(
    context: BatchContext,
    *,
    target_date: date,
    settings: Settings | None = None,
) -> EmaBatchOutcome:
    """Calculate all policy-proven series through ``target_date``.

    A source policy must be deliberately frozen in configuration.  A stable
    acceptance boundary lets later daily observations extend the same series;
    each completed run still copies its exact selected input evidence.
    """
    effective_settings = settings or get_settings()
    policy = _policy_from_settings(effective_settings)
    if policy is None:
        return EmaBatchOutcome.skipped("ema_source_policy_unconfigured")
    if context.session is None:
        return EmaBatchOutcome.skipped("ema_session_unavailable")

    trade_dates = _expected_trade_dates(context, target_date=target_date, policy=policy)
    if not trade_dates:
        return EmaBatchOutcome.skipped("no_eligible_ema_observations")
    instrument_ids = _eligible_instrument_ids(context, target_date=target_date, policy=policy)
    if not instrument_ids:
        return EmaBatchOutcome.skipped("no_eligible_identity_inputs")

    service = EmaCalculationService(context.session)
    processed = 0
    failures: list[str] = []
    for instrument_id in instrument_ids:
        try:
            service.calculate(
                instrument_id=instrument_id,
                trade_dates=trade_dates,
                policy=policy,
            )
            processed += 1
        except Exception as exc:  # noqa: BLE001 - EMA must not cancel RS publication.
            failures.append(type(exc).__name__)
            logger.exception("EMA calculation failed for instrument %s", instrument_id)

    if failures:
        return EmaBatchOutcome.failure(
            processed=processed,
            failed=len(failures),
            reason=failures[0],
        )
    return EmaBatchOutcome.completed(processed=processed)


def record_ema_checkpoint(context: BatchContext, outcome: EmaBatchOutcome) -> None:
    """Persist EMA state for the context's existing crawl job.

    A successful step is resumable.  Skip and failure remain
    ``completed_with_errors`` so a later retry can calculate EMA without
    rewriting the successful RS result.
    """
    repository = context.checkpoint_repository
    if repository is None or context.job_id is None:
        return
    checkpoint = repository.get_checkpoint(context.job_id, "ema")
    if checkpoint is None:
        repository.create_checkpoint(context.job_id, "ema")
    repository.start_step(context.job_id, "ema")
    repository.complete_step(
        context.job_id,
        "ema",
        status="completed" if not outcome.has_errors else "completed_with_errors",
        items_processed=outcome.processed,
        items_failed=outcome.failed,
        step_metadata=outcome.checkpoint_metadata(),
    )


def completed_ema_outcome(context: BatchContext) -> EmaBatchOutcome | None:
    """Return a persisted successful EMA result for same-job resumption."""
    repository = context.checkpoint_repository
    if repository is None or context.job_id is None:
        return None
    checkpoint = repository.get_checkpoint(context.job_id, "ema")
    if checkpoint is None or checkpoint.status != "completed":
        return None
    return EmaBatchOutcome.completed(processed=checkpoint.items_processed)


def _policy_from_settings(settings: Settings) -> EmaSourcePolicy | None:
    versions = tuple(
        value.strip()
        for value in settings.ema_allowed_parser_versions.split(",")
        if value.strip()
    )
    if not settings.ema_source_provider or not settings.ema_adjustment_type or not versions:
        return None
    return EmaSourcePolicy(
        provider=settings.ema_source_provider,
        adjustment_type=settings.ema_adjustment_type,
        allowed_parser_versions=versions,
        observation_cutoff=EMA_DAILY_OBSERVATION_BOUNDARY,
    )


def _expected_trade_dates(
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


def _eligible_instrument_ids(
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
