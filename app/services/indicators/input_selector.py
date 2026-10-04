"""Select immutable, policy-bound EMA input rows from observation evidence.

This module deliberately never reads ``DailyPrice`` or ``Symbol.instrument_id``.
An observation belongs to a historical instrument only through the identity
snapshot captured for that observation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_quality import OhlcCorrection, OhlcExclusion, PriceObservation, ValidationCase
from app.models.indicator import PriceObservationIdentitySnapshot
from app.services.indicators.contracts import (
    CloseCorrectionEvidence,
    EmaInputRow,
    EmaInputStatus,
    EmaSourcePolicy,
    IdentitySnapshot,
    InputReasonCode,
    ValidationCaseEvidence,
    select_last_approved_close_correction,
)
from app.services.validation.ohlcv_audit import classify_price


class EmaInputSelector:
    """Read one immutable EMA row per expected trading date.

    The caller supplies expected dates from the trading calendar.  A date with
    no policy candidate remains visible as ``missing_selected_source`` rather
    than disappearing through an inner join.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def select_rows(
        self,
        *,
        instrument_id: int,
        trade_dates: Iterable[date],
        policy: EmaSourcePolicy,
    ) -> tuple[EmaInputRow, ...]:
        dates = tuple(sorted(set(trade_dates)))
        if not dates:
            return ()
        observations = list(self.session.execute(
            select(PriceObservation, PriceObservationIdentitySnapshot)
            .join(
                PriceObservationIdentitySnapshot,
                PriceObservationIdentitySnapshot.price_observation_id == PriceObservation.id,
            )
            .where(
                PriceObservationIdentitySnapshot.instrument_id == instrument_id,
                PriceObservation.trade_date.in_(dates),
            )
            .order_by(PriceObservation.trade_date, PriceObservation.observed_at, PriceObservation.id)
        ))
        by_date: dict[date, list[tuple[PriceObservation, PriceObservationIdentitySnapshot]]] = defaultdict(list)
        for observation, identity in observations:
            if self._matches_source_policy(observation, policy):
                by_date[observation.trade_date].append((observation, identity))
        return tuple(
            self._select_date(
                instrument_id=instrument_id,
                trade_date=trade_date,
                candidates=by_date.get(trade_date, ()),
                policy=policy,
            )
            for trade_date in dates
        )

    @staticmethod
    def _matches_source_policy(observation: PriceObservation, policy: EmaSourcePolicy) -> bool:
        observed_at = _utc(observation.observed_at)
        return (
            observation.provider == policy.provider
            and observation.adjustment_type == policy.adjustment_type
            and observation.parser_version in policy.allowed_parser_versions
            and observed_at is not None
            and observed_at <= policy.observation_cutoff
        )

    def _select_date(
        self,
        *,
        instrument_id: int,
        trade_date: date,
        candidates: Iterable[tuple[PriceObservation, PriceObservationIdentitySnapshot]],
        policy: EmaSourcePolicy,
    ) -> EmaInputRow:
        candidate_rows = tuple(candidates)
        if not candidate_rows:
            return EmaInputRow(
                trade_date=trade_date, instrument_id=instrument_id, symbol_id=None,
                observation_id=None, identity=None, provider=policy.provider,
                provider_symbol="", adjustment_type=policy.adjustment_type,
                parser_version=None, close=None, volume=None, observed_at=None,
                payload_hash=None, input_status=EmaInputStatus.MISSING,
                reason_code=InputReasonCode.MISSING_SELECTED_SOURCE, source_policy=policy,
            )

        # observed_at then immutable observation ID is the contract tie-break.
        selected, identity_row = max(candidate_rows, key=lambda item: (item[0].observed_at, item[0].id))
        identity = _identity_evidence(identity_row)
        cases = self._validation_cases(selected)
        correction_ids, corrected_close, correction_reason = self._close_correction(selected)
        reason, status = self._decision(
            selected=selected,
            candidates=candidate_rows,
            cases=cases,
            correction_reason=correction_reason,
            corrected_close=corrected_close,
        )
        return EmaInputRow(
            trade_date=trade_date,
            instrument_id=instrument_id,
            symbol_id=selected.symbol_id,
            observation_id=selected.id,
            identity=identity,
            provider=selected.provider,
            provider_symbol=identity.provider_symbol or "",
            adjustment_type=selected.adjustment_type,
            parser_version=selected.parser_version,
            close=corrected_close if corrected_close is not None else selected.close,
            volume=selected.volume,
            observed_at=_utc(selected.observed_at),
            payload_hash=selected.payload_hash,
            correction_ids=correction_ids,
            validation_cases=cases,
            input_status=status,
            reason_code=reason,
            source_policy=policy,
        )

    def _validation_cases(self, selected: PriceObservation) -> tuple[ValidationCaseEvidence, ...]:
        rows = self.session.scalars(
            select(ValidationCase)
            .where(
                ValidationCase.subject_type == "daily_price",
                ValidationCase.symbol_id == selected.symbol_id,
                ValidationCase.trade_date == selected.trade_date,
            )
            .order_by(ValidationCase.id)
        )
        return tuple(
            ValidationCaseEvidence(case_id=row.id, case_status=row.case_status, decision=row.decision)
            for row in rows
        )

    def _close_correction(
        self, selected: PriceObservation
    ) -> tuple[tuple[int, ...], Decimal | None, InputReasonCode | None]:
        corrections = tuple(self.session.scalars(
            select(OhlcCorrection)
            .where(
                OhlcCorrection.symbol_id == selected.symbol_id,
                OhlcCorrection.trade_date == selected.trade_date,
                OhlcCorrection.field_name == "close",
                OhlcCorrection.status == "APPROVED",
            )
            .order_by(OhlcCorrection.id)
        ))
        evidence = tuple(
            CloseCorrectionEvidence(
                correction_id=row.id,
                value=_decimal_correction(row.corrected_value),
                status=row.status,
            )
            for row in corrections
        )
        value, reason, correction_ids = select_last_approved_close_correction(evidence)
        return correction_ids, value, reason

    def _decision(
        self,
        *,
        selected: PriceObservation,
        candidates: tuple[tuple[PriceObservation, PriceObservationIdentitySnapshot], ...],
        cases: tuple[ValidationCaseEvidence, ...],
        correction_reason: InputReasonCode | None,
        corrected_close: Decimal | None,
    ) -> tuple[InputReasonCode | None, EmaInputStatus]:
        # A conflicting source is intentionally not resolved by the latest
        # observation tie-break.  The tie-break identifies the copied evidence
        # while the row remains unavailable pending review.
        ohlcv_values = {
            (item.open, item.high, item.low, item.close, item.volume)
            for item, _ in candidates
        }
        if len(ohlcv_values) > 1:
            return InputReasonCode.CONFLICTING_OBSERVATIONS, EmaInputStatus.REVIEW_REQUIRED
        approved_exclusion = self.session.scalar(
            select(OhlcExclusion.id).where(
                OhlcExclusion.symbol_id == selected.symbol_id,
                OhlcExclusion.trade_date == selected.trade_date,
                OhlcExclusion.status == "APPROVED",
            ).limit(1)
        )
        if approved_exclusion is not None:
            return InputReasonCode.APPROVED_EXCLUSION, EmaInputStatus.INVALID
        if any(
            case.decision == "EXCLUDE" and case.case_status in {"auto_resolved", "approved"}
            for case in cases
        ):
            return InputReasonCode.APPROVED_VALIDATION_EXCLUSION, EmaInputStatus.INVALID
        if any(case.case_status == "open" for case in cases):
            return InputReasonCode.OPEN_VALIDATION_CASE, EmaInputStatus.REVIEW_REQUIRED
        if correction_reason is not None:
            return correction_reason, EmaInputStatus.INVALID
        assessment = classify_price(
            SimpleNamespace(
                trade_date=selected.trade_date, open=selected.open, high=selected.high,
                low=selected.low, close=corrected_close if corrected_close is not None else selected.close,
                volume=selected.volume,
            ),
            source_verified=True,
        )
        if assessment.status != "valid":
            return InputReasonCode.INVALID_OHLCV, EmaInputStatus.INVALID
        return None, EmaInputStatus.ELIGIBLE


def _identity_evidence(row: PriceObservationIdentitySnapshot) -> IdentitySnapshot:
    return IdentitySnapshot(
        snapshot_id=row.id, instrument_id=row.instrument_id, provider=row.provider,
        provider_symbol=row.provider_symbol, provider_mapping_id=row.provider_symbol_mapping_id,
        mapping_status=row.mapping_status, valid_from=row.mapping_valid_from,
        valid_to=row.mapping_valid_to, resolver_version=row.resolver_version,
        resolved_at=_utc(row.resolved_at),
    )


def _decimal_correction(raw: object | None) -> Decimal | None:
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def _utc(value: datetime | None) -> datetime | None:
    """Legacy source timestamps are stored as UTC without a DB tz marker."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
