"""Optional daily ATR14 step over immutable observation evidence."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from app.core.config import ATR_DAILY_OBSERVATION_BOUNDARY, Settings, get_settings
from app.services.batch.context import BatchContext
from app.services.batch.observation_inputs import expected_trade_dates, eligible_instrument_ids
from app.services.indicators.contracts import EmaSourcePolicy, canonical_json
from app.services.indicators.atr_calculation_service import AtrCalculationService


logger = logging.getLogger(__name__)
ATR_STEP_NAME = "atr14"


@dataclass(frozen=True)
class AtrBatchOutcome:
    outcome: str
    processed: int = 0
    failed: int = 0
    reason: str | None = None

    @classmethod
    def completed(cls, *, processed: int) -> "AtrBatchOutcome":
        return cls(outcome="completed", processed=processed)

    @classmethod
    def skipped(cls, reason: str) -> "AtrBatchOutcome":
        return cls(outcome="skipped", failed=1, reason=reason)

    @classmethod
    def failure(cls, *, processed: int, failed: int, reason: str) -> "AtrBatchOutcome":
        return cls(outcome="failed", processed=processed, failed=max(failed, 1), reason=reason)

    @property
    def has_errors(self) -> bool:
        return self.outcome != "completed"

    def checkpoint_metadata(self, *, settings: Settings | None = None) -> str:
        metadata = {"outcome": self.outcome}
        if self.reason is not None:
            metadata["reason"] = self.reason
        if self.outcome == "completed" and settings is not None:
            policy_hash = _source_policy_hash(settings)
            if policy_hash is not None:
                metadata["source_policy_hash"] = policy_hash
        return json.dumps(metadata, sort_keys=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "processed": self.processed,
            "failed": self.failed,
            "reason": self.reason,
        }


def atr14_enabled(settings: Settings | None = None) -> bool:
    return bool(getattr(settings or get_settings(), "atr14_enabled", False))


def calculate_daily_atr14(
    context: BatchContext,
    *,
    target_date: date,
    settings: Settings | None = None,
) -> AtrBatchOutcome:
    """Keep service-owned failed attempts in the caller's transaction for retry.

    No observations, prices or identity mappings are mutated. The storage
    service owns series locking, reuse, incremental runs and rebuild promotion.
    """
    effective_settings = settings or get_settings()
    try:
        policy = _policy_from_settings(effective_settings)
    except ValueError:
        return AtrBatchOutcome.failure(processed=0, failed=1, reason="atr_source_policy_invalid")
    if policy is None:
        return AtrBatchOutcome.failure(processed=0, failed=1, reason="atr_source_policy_unconfigured")
    if context.session is None:
        return AtrBatchOutcome.skipped("atr_session_unavailable")

    try:
        # A PostgreSQL statement error aborts its transaction. Roll back only
        # the input reads so this daily session can still commit RS, EMA and
        # the optional ATR failure checkpoint.
        with context.session.begin_nested():
            trade_dates = expected_trade_dates(context, target_date=target_date, policy=policy)
            if not trade_dates:
                return AtrBatchOutcome.skipped("no_eligible_atr_observations")
            instrument_ids = eligible_instrument_ids(context, target_date=target_date, policy=policy)
            if not instrument_ids:
                return AtrBatchOutcome.skipped("no_eligible_identity_inputs")
        service = AtrCalculationService(context.session)
    except Exception as exc:  # noqa: BLE001 - optional indicators cannot cancel RS.
        logger.error("ATR14 input selection failed: %s", type(exc).__name__)
        return AtrBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)

    processed = 0
    failures: list[str] = []
    for instrument_id in instrument_ids:
        try:
            service.calculate(instrument_id=instrument_id, trade_dates=trade_dates, policy=policy)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - continue independent series.
            failures.append(type(exc).__name__)
            logger.error(
                "ATR14 calculation failed for instrument %s: %s",
                instrument_id, type(exc).__name__,
            )
    if failures:
        return AtrBatchOutcome.failure(processed=processed, failed=len(failures), reason=failures[0])
    return AtrBatchOutcome.completed(processed=processed)


def record_atr_checkpoint(
    context: BatchContext, outcome: AtrBatchOutcome, *, settings: Settings | None = None,
) -> None:
    """Keep failures retryable and freeze the completed source policy for resume."""
    repository = context.checkpoint_repository
    if repository is None or context.job_id is None:
        return
    if repository.get_checkpoint(context.job_id, ATR_STEP_NAME) is None:
        repository.create_checkpoint(context.job_id, ATR_STEP_NAME)
    repository.start_step(context.job_id, ATR_STEP_NAME)
    repository.complete_step(
        context.job_id, ATR_STEP_NAME,
        status="completed_with_errors" if outcome.has_errors else "completed",
        items_processed=outcome.processed, items_failed=outcome.failed,
        step_metadata=outcome.checkpoint_metadata(settings=settings),
    )


def completed_atr_outcome(
    context: BatchContext, *, settings: Settings | None = None,
) -> AtrBatchOutcome | None:
    """Reuse only this job's successful ATR step under the same policy."""
    repository = context.checkpoint_repository
    if repository is None or context.job_id is None:
        return None
    checkpoint = repository.get_checkpoint(context.job_id, ATR_STEP_NAME)
    if checkpoint is None or checkpoint.status != "completed":
        return None
    if settings is not None:
        policy_hash = _source_policy_hash(settings)
        try:
            metadata = json.loads(checkpoint.step_metadata or "{}")
        except (TypeError, ValueError):
            return None
        if (
            policy_hash is None
            or not isinstance(metadata, dict)
            or metadata.get("source_policy_hash") != policy_hash
        ):
            return None
    return AtrBatchOutcome.completed(processed=checkpoint.items_processed)


def _source_policy_hash(settings: Settings) -> str | None:
    try:
        policy = _policy_from_settings(settings)
    except ValueError:
        return None
    if policy is None:
        return None
    return sha256(canonical_json(policy.fingerprint_material()).encode("utf-8")).hexdigest()


def _policy_from_settings(settings: Settings) -> EmaSourcePolicy | None:
    provider = settings.atr14_source_provider.strip()
    adjustment = settings.atr14_adjustment_type.strip()
    raw_versions = settings.atr14_allowed_parser_versions.strip()
    if not provider or not adjustment or not raw_versions:
        return None
    versions = tuple(value.strip() for value in raw_versions.split(","))
    # Policy components are individual tokens, never multiple providers or
    # adjustment types. Reject malformed lists rather than dropping entries.
    for token in (provider, adjustment, *versions):
        if (
            not token or "," in token
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in token)
        ):
            raise ValueError("invalid ATR source policy token")
    return EmaSourcePolicy(
        provider=provider,
        adjustment_type=adjustment,
        allowed_parser_versions=tuple(sorted(set(versions))),
        observation_cutoff=ATR_DAILY_OBSERVATION_BOUNDARY,
    )
