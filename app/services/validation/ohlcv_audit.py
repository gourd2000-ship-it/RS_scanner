"""보존된 OHLCV 한 행의 구조와 출처 증거를 분리하여 판정한다."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_quality import CorporateAction, OhlcCorrection, OhlcExclusion, PriceObservation, ValidationCase
from app.models.daily_price import DailyPrice
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.services.validation.cleansing_policy import CleansingSelection, select_cleansing_universe
from app.services.validation.rules import inspect_ohlc_row

QUALITY_RULE_VERSION = "ohlcv-audit-v2"


@dataclass(frozen=True)
class PriceAssessment:
    status: str
    reasons: tuple[str, ...]
    source_verified: bool


@dataclass(frozen=True)
class OhlcvAuditResult:
    expected: int
    observed: int
    valid: int
    missing: int
    invalid: int
    review_required: int
    non_tradable: int
    source_verified: int
    excluded_delisted: int
    unknown_instruments: int


def classify_price(
    row: object,
    *,
    source_verified: bool,
    adjustment_verified: bool = True,
    source_conflict: bool = False,
) -> PriceAssessment:
    reasons = [finding.reason_code for finding in inspect_ohlc_row(row, rule_id="historical_ohlcv")]
    volume = getattr(row, "volume", None)
    if volume is not None:
        try:
            numeric = Decimal(str(volume))
            if not numeric.is_finite() or numeric != numeric.to_integral_value():
                reasons.append("INVALID_VOLUME")
        except (InvalidOperation, TypeError, ValueError):
            reasons.append("INVALID_VOLUME")
    if reasons:
        return PriceAssessment("invalid", tuple(dict.fromkeys(reasons)), source_verified)
    if not source_verified:
        reasons.append("SOURCE_UNVERIFIED")
    if not adjustment_verified:
        reasons.append("ADJUSTMENT_UNVERIFIED")
    if source_conflict:
        reasons.append("SOURCE_CONFLICT")
    return PriceAssessment(
        "review_required" if reasons else "valid",
        tuple(reasons),
        source_verified,
    )


def classify_transition(
    previous_close: Decimal,
    current_close: Decimal,
    *,
    corporate_action: bool,
    consecutive: bool = True,
    review_threshold: Decimal = Decimal("0.30"),
) -> str | None:
    """연속 관측일의 큰 변화를 조사 대상으로 표시한다. 법정 가격제한 판정은 아니다."""
    if not consecutive or previous_close <= 0 or current_close <= 0:
        return None
    movement = current_close / previous_close - 1
    if abs(movement) > review_threshold and not corporate_action:
        return "EXTREME_RETURN_REVIEW"
    return None


_PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def _same_ohlcv(left: object, right: object) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in _PRICE_FIELDS)


def audit_ohlcv(
    session: Session,
    *,
    selection: CleansingSelection,
    adjustment_policy: str,
    output_dir: Path,
) -> OhlcvAuditResult:
    """원본을 바꾸지 않고 각 기대 거래일과 저장 가격의 근거를 대조한다."""
    from app.services.validation.historical_clean_reader import assess_observation

    provider, separator, adjustment_type = adjustment_policy.partition(":")
    if not separator or not provider or not adjustment_type:
        raise ValueError("adjustment_policy must be provider:adjustment_type")
    selected = select_cleansing_universe(session, selection)
    instruments = {
        row.id: row for row in session.scalars(select(Instrument).order_by(Instrument.id))
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage: dict[tuple[int, int, str], dict[str, int | str]] = {}
    totals = dict(expected=0, observed=0, valid=0, missing=0, invalid=0,
                  review_required=0, non_tradable=0, source_verified=0)
    last_close: dict[int, tuple[int, Decimal]] = {}

    with (output_dir / "gaps.csv").open("w", newline="", encoding="utf-8") as gaps_file, \
         (output_dir / "anomalies.csv").open("w", newline="", encoding="utf-8") as anomalies_file, \
         (output_dir / "source_conflicts.csv").open("w", newline="", encoding="utf-8") as conflicts_file:
        gaps = csv.writer(gaps_file)
        anomalies = csv.writer(anomalies_file)
        conflicts = csv.writer(conflicts_file)
        gaps.writerow(("instrument_id", "code", "trade_date", "reason"))
        anomalies.writerow(("instrument_id", "code", "trade_date", "status", "reasons", "provider"))
        conflicts.writerow(("instrument_id", "code", "trade_date", "reason"))

        from itertools import groupby

        for day_index, (day, entries) in enumerate(groupby(selected.universe.entries, key=lambda entry: entry.trade_date)):
            daily_entries = list(entries)
            action_symbols = {row.symbol_id for row in session.scalars(select(CorporateAction).where(
                CorporateAction.event_date == day
            ))}
            symbol_prices = list(session.execute(
                select(DailyPrice, Symbol)
                .join(Symbol, Symbol.id == DailyPrice.symbol_id)
                .where(DailyPrice.trade_date == day, Symbol.instrument_id.is_not(None))
                .order_by(Symbol.instrument_id, DailyPrice.id)
            ))
            by_instrument: dict[int, list[tuple[DailyPrice, Symbol]]] = {}
            for price, symbol in symbol_prices:
                by_instrument.setdefault(symbol.instrument_id, []).append((price, symbol))
            observations = list(session.execute(
                select(PriceObservation, Symbol)
                .join(Symbol, Symbol.id == PriceObservation.symbol_id)
                .where(PriceObservation.trade_date == day,
                       PriceObservation.observed_at <= selection.observation_cutoff,
                       Symbol.instrument_id.is_not(None))
                .order_by(PriceObservation.observed_at, PriceObservation.id)
            ))
            by_observation_instrument: dict[int, list[PriceObservation]] = {}
            for observation, symbol in observations:
                by_observation_instrument.setdefault(symbol.instrument_id, []).append(observation)
            corrections_by_key: dict[tuple[int, date], list[OhlcCorrection]] = {}
            for correction in session.scalars(select(OhlcCorrection).where(
                OhlcCorrection.trade_date == day, OhlcCorrection.status == "APPROVED"
            ).order_by(OhlcCorrection.id)):
                corrections_by_key.setdefault((correction.symbol_id, day), []).append(correction)
            excluded_keys = {
                (row.symbol_id, day) for row in session.scalars(select(OhlcExclusion).where(
                    OhlcExclusion.trade_date == day, OhlcExclusion.status == "APPROVED"
                ))
            }
            validation_excluded_keys = {
                (row.symbol_id, day) for row in session.scalars(select(ValidationCase).where(
                    ValidationCase.subject_type == "daily_price",
                    ValidationCase.trade_date == day,
                    ValidationCase.decision == "EXCLUDE",
                    ValidationCase.case_status.in_(("auto_resolved", "approved")),
                ))
            }

            for entry in daily_entries:
                instrument = instruments[entry.instrument_id]
                key = (entry.instrument_id, day.year, entry.market)
                counts = coverage.setdefault(key, {
                    "instrument_id": entry.instrument_id, "code": instrument.krx_short_code,
                    "year": day.year, "market": entry.market,
                    "expected": 0, "observed": 0, "valid": 0, "missing": 0,
                    "invalid": 0, "review_required": 0, "non_tradable": 0,
                })
                if entry.price_expectation != "expected":
                    totals["non_tradable"] += 1
                    counts["non_tradable"] += 1
                    last_close.pop(entry.instrument_id, None)
                    continue
                totals["expected"] += 1
                counts["expected"] += 1
                candidates = by_instrument.get(entry.instrument_id, [])
                historical_observations = by_observation_instrument.get(entry.instrument_id, [])
                matching_policy = [row for row in historical_observations
                                   if row.provider == provider and row.adjustment_type == adjustment_type]
                selected_observation = matching_policy[-1] if matching_policy else None
                if not candidates and selected_observation is None:
                    totals["missing"] += 1
                    counts["missing"] += 1
                    gaps.writerow((entry.instrument_id, instrument.krx_short_code, day, "price_missing"))
                    last_close.pop(entry.instrument_id, None)
                    continue
                totals["observed"] += 1
                counts["observed"] += 1
                if (len(candidates) > 1 and selected_observation is None) or len({row.symbol_id for row in matching_policy}) > 1:
                    totals["review_required"] += 1
                    counts["review_required"] += 1
                    conflicts.writerow((entry.instrument_id, instrument.krx_short_code, day, "ambiguous_price_owner"))
                    anomalies.writerow((entry.instrument_id, instrument.krx_short_code, day,
                                        "review_required", "ambiguous_price_owner", ""))
                    last_close.pop(entry.instrument_id, None)
                    continue
                price = candidates[0][0] if candidates else None
                source_conflict = len({_ohlcv_key(row) for row in matching_policy}) > 1
                if source_conflict:
                    conflicts.writerow((entry.instrument_id, instrument.krx_short_code, day, "conflicting_observations"))
                if selected_observation is not None and price is not None and not _same_ohlcv(price, selected_observation):
                    conflicts.writerow((entry.instrument_id, instrument.krx_short_code, day, "canonical_price_differs"))
                if selected_observation is not None:
                    decision = assess_observation(
                        selected_observation, revisions=matching_policy,
                        corrections=corrections_by_key.get((selected_observation.symbol_id, day), []),
                        approved_exclusion=(selected_observation.symbol_id, day) in excluded_keys,
                        approved_validation_exclusion=(selected_observation.symbol_id, day) in validation_excluded_keys,
                    )
                    totals["source_verified"] += 1
                    status, reasons = decision.status, (decision.reason or "",)
                else:
                    assessment = classify_price(price, source_verified=False, adjustment_verified=False)
                    status, reasons = assessment.status, assessment.reasons
                if status == "valid" and selected_observation is not None:
                    previous = last_close.get(entry.instrument_id)
                    if previous is not None:
                        transition_reason = classify_transition(
                            previous[1], decision.values["close"],
                            corporate_action=selected_observation.symbol_id in action_symbols,
                            consecutive=previous[0] == day_index - 1,
                        )
                        if transition_reason is not None:
                            status, reasons = "review_required", (transition_reason,)
                    if status == "valid":
                        last_close[entry.instrument_id] = (day_index, decision.values["close"])
                if status != "valid":
                    last_close.pop(entry.instrument_id, None)
                totals[status] += 1
                counts[status] += 1
                if status != "valid":
                    anomalies.writerow((entry.instrument_id, instrument.krx_short_code, day,
                                        status, "|".join(reasons),
                                        selected_observation.provider if selected_observation is not None else price.source))

    fields = ("instrument_id", "code", "year", "market", "expected", "observed", "valid",
              "missing", "invalid", "review_required", "non_tradable")
    with (output_dir / "symbol_year_coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key in sorted(coverage):
            writer.writerow(coverage[key])
    with (output_dir / "excluded_universe.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "reason"))
        for instrument_id in selected.excluded_delisted_ids:
            writer.writerow((instrument_id, instruments[instrument_id].krx_short_code, "delisted_by_selection_date"))
    with (output_dir / "unresolved_identity.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "reason"))
        for instrument_id in selected.unknown_instrument_ids:
            writer.writerow((instrument_id, instruments[instrument_id].krx_short_code, "listing_evidence_missing"))
    result = OhlcvAuditResult(
        **totals,
        excluded_delisted=len(selected.excluded_delisted_ids),
        unknown_instruments=len(selected.unknown_instrument_ids),
    )
    (output_dir / "manifest.json").write_text(json.dumps({
        "start": selection.start.isoformat(), "end": selection.end.isoformat(),
        "selection_as_of": selection.selection_as_of.isoformat(),
        "observation_cutoff": selection.observation_cutoff.isoformat(),
        "markets": selection.markets, "exclude_delisted": selection.exclude_delisted,
        "adjustment_policy": adjustment_policy,
        "membership_completeness": selected.universe.membership_completeness,
        "quality_rule": QUALITY_RULE_VERSION,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(result.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _ohlcv_key(row: PriceObservation) -> tuple:
    return tuple(getattr(row, field) for field in _PRICE_FIELDS)
