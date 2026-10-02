"""승인된 보정·제외를 반영해 지정 공급자의 역사 가격을 선택한다."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_quality import OhlcCorrection, OhlcExclusion, PriceObservation, ValidationCase
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.services.validation.ohlcv_audit import classify_price


_FIELDS = ("open", "high", "low", "close", "volume", "change_rate")


@dataclass(frozen=True)
class CleanPriceDecision:
    status: str
    reason: str | None
    values: dict | None
    source_symbol_id: int | None
    source_observation_id: int | None
    source_payload_hash: str | None
    correction_ids: tuple[int, ...]


def read_clean_price(
    session: Session,
    *,
    instrument_id: int,
    trade_date: date,
    provider: str,
    adjustment_type: str,
    observation_cutoff: datetime,
) -> CleanPriceDecision:
    """한 기대 거래일을 판정한다. 원본 observation과 canonical 가격은 변경하지 않는다."""
    observations = list(session.scalars(
        select(PriceObservation)
        .join(Symbol, Symbol.id == PriceObservation.symbol_id)
        .where(Symbol.instrument_id == instrument_id,
               PriceObservation.trade_date == trade_date,
               PriceObservation.provider == provider,
               PriceObservation.adjustment_type == adjustment_type,
               PriceObservation.observed_at <= observation_cutoff)
        .order_by(PriceObservation.observed_at, PriceObservation.id)
    ))
    if not observations:
        return CleanPriceDecision("missing", "selected_source_missing", None, None, None, None, ())
    selected = observations[-1]
    exclusion = session.scalar(select(OhlcExclusion).where(
        OhlcExclusion.symbol_id == selected.symbol_id,
        OhlcExclusion.trade_date == trade_date,
        OhlcExclusion.status == "APPROVED",
    ))
    approved_case = session.scalar(select(ValidationCase).where(
        ValidationCase.subject_type == "daily_price",
        ValidationCase.symbol_id == selected.symbol_id,
        ValidationCase.trade_date == trade_date,
        ValidationCase.decision == "EXCLUDE",
        ValidationCase.case_status.in_(("auto_resolved", "approved")),
    ))
    corrections = list(session.scalars(select(OhlcCorrection).where(
        OhlcCorrection.symbol_id == selected.symbol_id,
        OhlcCorrection.trade_date == trade_date,
        OhlcCorrection.status == "APPROVED",
    ).order_by(OhlcCorrection.id)))
    return assess_observation(
        selected, revisions=observations, corrections=corrections,
        approved_exclusion=exclusion is not None,
        approved_validation_exclusion=approved_case is not None,
    )


def assess_observation(
    selected: PriceObservation,
    *,
    revisions: list[PriceObservation],
    corrections: list[OhlcCorrection],
    approved_exclusion: bool = False,
    approved_validation_exclusion: bool = False,
) -> CleanPriceDecision:
    """이미 조회한 증거로 판정한다. 대량 감사에서도 같은 정책을 사용한다."""
    if len({row.symbol_id for row in revisions}) != 1:
        return _without_values("review_required", "ambiguous_price_owner", selected)
    if len({tuple(getattr(row, field) for field in _FIELDS[:5]) for row in revisions}) > 1:
        return _without_values("review_required", "conflicting_observations", selected)
    if approved_exclusion:
        return _without_values("invalid", "approved_exclusion", selected)
    if approved_validation_exclusion:
        return _without_values("invalid", "approved_validation_exclusion", selected)

    values = {field: getattr(selected, field) for field in _FIELDS}
    applied: dict[str, int] = {}
    try:
        for correction in corrections:
            if correction.field_name not in _FIELDS:
                continue
            raw = correction.corrected_value
            if isinstance(raw, dict):
                raw = raw["value"]
            numeric = Decimal(str(raw))
            if not numeric.is_finite():
                raise ValueError("non-finite correction")
            if correction.field_name == "volume":
                if numeric != numeric.to_integral_value():
                    raise ValueError("fractional volume correction")
                values["volume"] = int(numeric)
            else:
                values[correction.field_name] = numeric
            applied[correction.field_name] = correction.id
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return _without_values("invalid", "invalid_approved_correction", selected)

    assessment = classify_price(SimpleNamespace(trade_date=selected.trade_date, **values), source_verified=True)
    if assessment.status != "valid":
        return _without_values("invalid", "|".join(assessment.reasons), selected)
    return CleanPriceDecision(
        status="valid", reason=None, values=values,
        source_symbol_id=selected.symbol_id, source_observation_id=selected.id,
        source_payload_hash=selected.payload_hash,
        correction_ids=tuple(applied[field] for field in sorted(applied)),
    )


def _without_values(status: str, reason: str, row: PriceObservation) -> CleanPriceDecision:
    return CleanPriceDecision(status, reason, None, row.symbol_id, row.id, row.payload_hash, ())


def select_clean_day_decisions(
    session: Session,
    *,
    trade_date: date,
    provider: str,
    adjustment_type: str,
    observation_cutoff: datetime,
) -> dict[int, CleanPriceDecision]:
    """해당 날짜를 한 번 조회해 종목별 결정으로 바꾼다."""
    observations = session.execute(
        select(PriceObservation, Symbol)
        .join(Symbol, Symbol.id == PriceObservation.symbol_id)
        .where(PriceObservation.trade_date == trade_date,
               PriceObservation.provider == provider,
               PriceObservation.adjustment_type == adjustment_type,
               PriceObservation.observed_at <= observation_cutoff,
               Symbol.instrument_id.is_not(None))
        .order_by(PriceObservation.observed_at, PriceObservation.id)
    )
    by_instrument: dict[int, list[PriceObservation]] = {}
    for observation, symbol in observations:
        by_instrument.setdefault(symbol.instrument_id, []).append(observation)

    corrections: dict[int, list[OhlcCorrection]] = {}
    for row in session.scalars(select(OhlcCorrection).where(
        OhlcCorrection.trade_date == trade_date, OhlcCorrection.status == "APPROVED"
    ).order_by(OhlcCorrection.id)):
        corrections.setdefault(row.symbol_id, []).append(row)
    exclusions = {row.symbol_id for row in session.scalars(select(OhlcExclusion).where(
        OhlcExclusion.trade_date == trade_date, OhlcExclusion.status == "APPROVED"
    ))}
    validation_exclusions = {row.symbol_id for row in session.scalars(select(ValidationCase).where(
        ValidationCase.subject_type == "daily_price",
        ValidationCase.trade_date == trade_date,
        ValidationCase.decision == "EXCLUDE",
        ValidationCase.case_status.in_(("auto_resolved", "approved")),
    ))}
    decisions: dict[int, CleanPriceDecision] = {}
    for instrument_id, revisions in by_instrument.items():
        selected = revisions[-1]
        decisions[instrument_id] = assess_observation(
            selected, revisions=revisions,
            corrections=corrections.get(selected.symbol_id, []),
            approved_exclusion=selected.symbol_id in exclusions,
            approved_validation_exclusion=selected.symbol_id in validation_exclusions,
        )
    for price, symbol in session.execute(
        select(DailyPrice, Symbol)
        .join(Symbol, Symbol.id == DailyPrice.symbol_id)
        .where(DailyPrice.trade_date == trade_date, Symbol.instrument_id.is_not(None))
    ):
        decisions.setdefault(symbol.instrument_id, CleanPriceDecision(
            "review_required", "selected_source_missing_canonical_exists", None,
            symbol.id, None, None, (),
        ))
    return decisions
