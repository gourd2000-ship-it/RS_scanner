"""Persist indicator values only after matching them to a complete price dataset."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
    BacktestDatasetIndicatorSnapshotSource,
    BacktestDatasetMembership,
    BacktestDatasetPrice,
)
from app.models.data_quality import OhlcCorrection, PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputEvidence,
    IndicatorInputPolicy,
    IndicatorRunInput,
    IndicatorSeries,
    IndicatorValue,
    PriceObservationIdentitySnapshot,
)
from app.models.instrument import Instrument
from app.services.indicators.contracts import canonical_json


_DEFINITIONS = {
    "volume_sma": (50, "volume-sma-v1"),
    "atr": (14, "wilder-atr-14-v1"),
}


class BacktestIndicatorSnapshotError(ValueError):
    """A stable, machine-readable reason why indicator input could not be pinned."""

    def __init__(self, reason_code: str, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or {}


class BacktestIndicatorSnapshotRepository:
    """Create dataset-bound immutable MA50/ATR14 value bundles.

    The caller chooses one completed run per dataset instrument. This prevents
    a later query of whatever generation happens to be current from changing a
    historical backtest input.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        dataset_id: str,
        indicator_kind: str,
        source_run_ids_by_instrument: Mapping[int, int],
    ) -> BacktestDatasetIndicatorSnapshot:
        definition = _DEFINITIONS.get(indicator_kind)
        if definition is None:
            raise BacktestIndicatorSnapshotError(
                "indicator_evidence_mismatch", f"unsupported backtest indicator kind: {indicator_kind}"
            )
        period, formula_version = definition
        if not source_run_ids_by_instrument:
            raise BacktestIndicatorSnapshotError(
                "indicator_snapshot_missing", "at least one explicitly selected indicator run is required"
            )

        dataset = self.session.scalar(
            select(BacktestDataset).where(BacktestDataset.dataset_id == dataset_id)
        )
        if dataset is None:
            raise BacktestIndicatorSnapshotError(
                "indicator_snapshot_missing", f"backtest dataset not found: {dataset_id}"
            )
        self._validate_dataset(dataset)
        prices, memberships = self._dataset_rows(dataset)
        price_by_key = {(row.instrument_id, row.trade_date): row for row in prices}
        if len(price_by_key) != len(prices):
            self._mismatch("dataset contains duplicate instrument/date prices")
        if set(price_by_key) != set(memberships):
            self._mismatch("complete dataset prices do not match expected membership rows")
        if any(
            price.trade_date < dataset.range_start
            or price.trade_date > dataset.range_end
            or price.market not in set(dataset.markets or [])
            or memberships[(price.instrument_id, price.trade_date)].market != price.market
            for price in prices
        ):
            self._mismatch("dataset price dates or markets fall outside the finalized dataset scope")

        instrument_ids = {instrument_id for instrument_id, _ in price_by_key}
        selected_runs = {int(key): int(value) for key, value in source_run_ids_by_instrument.items()}
        if set(selected_runs) != instrument_ids or len(set(selected_runs.values())) != len(selected_runs):
            self._mismatch("one distinct indicator run must be selected for every dataset instrument")

        adjustment_provider, separator, adjustment_type = dataset.adjustment_policy.partition(":")
        if not separator or not adjustment_provider or not adjustment_type:
            self._mismatch("dataset adjustment policy is not provider:adjustment")

        dates_by_instrument: dict[int, list[date]] = defaultdict(list)
        for instrument_id, trade_date in sorted(price_by_key):
            dates_by_instrument[instrument_id].append(trade_date)

        sources: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        policy_fingerprints: set[str] = set()
        for instrument_id, run_id in sorted(selected_runs.items()):
            source, source_rows = self._load_source(
                instrument_id=instrument_id,
                run_id=run_id,
                indicator_kind=indicator_kind,
                period=period,
                formula_version=formula_version,
                expected_dates=dates_by_instrument[instrument_id],
                prices=price_by_key,
                memberships=memberships,
                dataset_provider=adjustment_provider,
                dataset_adjustment=adjustment_type,
            )
            sources.append(source)
            rows.extend(source_rows)
            policy_fingerprints.add(str(source["source_policy_fingerprint"]))

        if len(policy_fingerprints) != 1:
            self._mismatch("one source policy fingerprint must cover the complete snapshot")
        source_policy_fingerprint = next(iter(policy_fingerprints))
        rows.sort(key=lambda row: (int(row["instrument_id"]), row["trade_date"]))
        source_material = [
            {key: source[key] for key in (
                "instrument_id", "indicator_series_id", "generation_id", "calculation_run_id",
                "input_policy_id", "source_policy_fingerprint", "input_hash", "result_hash",
            )}
            for source in sources
        ]
        input_hash = _hash([{
            "instrument_id": item["instrument_id"], "input_hash": item["input_hash"],
        } for item in source_material])
        result_hash = _hash([{
            "instrument_id": item["instrument_id"], "result_hash": item["result_hash"],
        } for item in source_material])
        content_hash = _hash({
            "dataset_id": dataset.dataset_id,
            "dataset_manifest_hash": dataset.final_manifest_hash,
            "indicator_kind": indicator_kind,
            "period": period,
            "formula_version": formula_version,
            "source_policy_fingerprint": source_policy_fingerprint,
            "range_start": dataset.range_start,
            "range_end": dataset.range_end,
            "sources": source_material,
            "rows": [row["row_hash"] for row in rows],
        })
        snapshot_key = _hash({
            "dataset_id": dataset.dataset_id,
            "dataset_manifest_hash": dataset.final_manifest_hash,
            "indicator_kind": indicator_kind,
            "period": period,
            "formula_version": formula_version,
            "source_policy_fingerprint": source_policy_fingerprint,
            "source_ids": source_material,
        })
        existing = self.session.scalar(
            select(BacktestDatasetIndicatorSnapshot).where(
                BacktestDatasetIndicatorSnapshot.snapshot_key == snapshot_key
            )
        )
        if existing is not None:
            if existing.status != "complete" or existing.content_hash != content_hash:
                raise BacktestIndicatorSnapshotError(
                    "indicator_evidence_mismatch", "the identical snapshot request has different stored content"
                )
            return existing

        # Savepoint means a failed proof cannot leave a visible building bundle.
        with self.session.begin_nested():
            snapshot = BacktestDatasetIndicatorSnapshot(
                snapshot_key=snapshot_key,
                backtest_dataset_id=dataset.id,
                dataset_id=dataset.dataset_id,
                dataset_manifest_hash=dataset.final_manifest_hash,
                indicator_kind=indicator_kind,
                period=period,
                formula_version=formula_version,
                source_policy_fingerprint=source_policy_fingerprint,
                range_start=dataset.range_start,
                range_end=dataset.range_end,
                source_count=len(sources),
                row_count=len(rows),
                input_hash=input_hash,
                result_hash=result_hash,
                content_hash=content_hash,
                status="building",
            )
            self.session.add(snapshot)
            self.session.flush()

            source_id_by_instrument: dict[int, int] = {}
            source_models: list[BacktestDatasetIndicatorSnapshotSource] = []
            for source in sources:
                model = BacktestDatasetIndicatorSnapshotSource(snapshot_id=snapshot.id, **source)
                self.session.add(model)
                source_models.append(model)
            self.session.flush()
            source_id_by_instrument = {
                model.instrument_id: model.id for model in source_models
            }

            self.session.add_all([
                BacktestDatasetIndicatorSnapshotRow(
                    snapshot_id=snapshot.id,
                    source_id=source_id_by_instrument[int(row["instrument_id"])],
                    **{key: value for key, value in row.items() if key != "row_hash"},
                    row_hash=str(row["row_hash"]),
                )
                for row in rows
            ])
            self.session.flush()
            snapshot.status = "complete"
            snapshot.completed_at = datetime.now(UTC)
            self.session.flush()
        return snapshot

    def get_snapshot(self, snapshot_id: int) -> BacktestDatasetIndicatorSnapshot | None:
        return self.session.get(BacktestDatasetIndicatorSnapshot, snapshot_id)

    def list_rows(self, snapshot_id: int) -> tuple[BacktestDatasetIndicatorSnapshotRow, ...]:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None or snapshot.status != "complete":
            return ()
        return tuple(self.session.scalars(
            select(BacktestDatasetIndicatorSnapshotRow)
            .where(BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot_id)
            .order_by(BacktestDatasetIndicatorSnapshotRow.trade_date,
                      BacktestDatasetIndicatorSnapshotRow.instrument_id)
        ))

    def _validate_dataset(self, dataset: BacktestDataset) -> None:
        manifest = dataset.manifest
        if (
            dataset.status != "active"
            or not isinstance(manifest, dict)
            or manifest.get("publication_scope") != "complete_segments_only"
            or not dataset.final_manifest_hash
            or _hash(manifest) != dataset.final_manifest_hash
            or manifest.get("range") != {
                "start": dataset.range_start.isoformat(), "end": dataset.range_end.isoformat(),
            }
        ):
            raise BacktestIndicatorSnapshotError(
                "dataset_not_complete", "only a finalized active complete-segments dataset is accepted"
            )

    def _dataset_rows(self, dataset: BacktestDataset):
        prices = tuple(self.session.scalars(
            select(BacktestDatasetPrice)
            .where(BacktestDatasetPrice.backtest_dataset_id == dataset.id)
            .order_by(BacktestDatasetPrice.instrument_id, BacktestDatasetPrice.trade_date)
        ))
        member_rows = tuple(self.session.scalars(
            select(BacktestDatasetMembership)
            .where(BacktestDatasetMembership.backtest_dataset_id == dataset.id)
            .order_by(BacktestDatasetMembership.instrument_id, BacktestDatasetMembership.trade_date)
        ))
        memberships = {(row.instrument_id, row.trade_date): row for row in member_rows}
        if len(memberships) != len(member_rows) or not prices:
            self._mismatch("complete dataset has empty or duplicate membership/price rows")
        manifest = dataset.manifest
        actual_segments = sorted({
            (price.instrument_id, price.trade_date.year) for price in prices
        })
        recorded_segments = manifest.get("complete_segments")
        if not isinstance(recorded_segments, list):
            self._mismatch("dataset manifest is missing its complete segment list")
        normalized_segments = sorted(
            (item.get("instrument_id"), item.get("year"))
            for item in recorded_segments if isinstance(item, dict)
        )
        coverage = manifest.get("coverage")
        if (
            normalized_segments != actual_segments
            or len(normalized_segments) != len(recorded_segments)
            or not isinstance(coverage, dict)
            or coverage.get("valid") != len(prices)
            or coverage.get("complete_segments") != len(actual_segments)
        ):
            self._mismatch("dataset rows do not match finalized complete-segment coverage")
        return prices, memberships

    def _load_source(
        self,
        *,
        instrument_id: int,
        run_id: int,
        indicator_kind: str,
        period: int,
        formula_version: str,
        expected_dates: list[date],
        prices: Mapping[tuple[int, date], BacktestDatasetPrice],
        memberships: Mapping[tuple[int, date], BacktestDatasetMembership],
        dataset_provider: str,
        dataset_adjustment: str,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        run = self.session.get(IndicatorCalculationRun, run_id)
        generation = self.session.get(IndicatorGeneration, run.generation_id) if run is not None else None
        series = self.session.get(IndicatorSeries, run.series_id) if run is not None else None
        policy = self.session.get(IndicatorInputPolicy, series.input_policy_id) if series is not None else None
        if (
            run is None or generation is None or series is None or policy is None
            or run.status != "completed"
            or generation.status not in {"current", "superseded"}
            or generation.series_id != series.id
            or run.generation_id != generation.id
            or run.series_id != series.id
            or series.instrument_id != instrument_id
            or series.indicator_kind != indicator_kind
            or series.input_policy_version != "validated-observation-ohlcv-v1"
            or policy.version != "validated-observation-ohlcv-v1"
            or series.input_field != ("volume" if indicator_kind == "volume_sma" else "high-low-close")
            or series.periods != str(period)
            or series.formula_version != formula_version
            or series.input_policy_id != policy.id
            or series.observation_cutoff is None
            or _as_utc(series.observation_cutoff) != _as_utc(policy.observation_cutoff)
            or not _is_hash(policy.fingerprint)
            or not _is_hash(run.input_hash)
            or not _is_hash(run.result_hash)
            or policy.provider != dataset_provider
            or policy.adjustment_type != dataset_adjustment
            or series.source_provider != dataset_provider
            or series.adjustment_policy != dataset_adjustment
            or sorted(set(policy.allowed_parser_versions or [])) != sorted(set(series.allowed_parser_versions or []))
        ):
            self._mismatch("selected series, generation, run, or source policy does not match the dataset")

        values = tuple(self.session.scalars(
            select(IndicatorValue)
            .where(
                IndicatorValue.calculation_run_id == run.id,
                IndicatorValue.generation_id == generation.id,
                IndicatorValue.indicator_kind == indicator_kind,
                IndicatorValue.period == period,
                IndicatorValue.trade_date.in_(expected_dates),
            )
            .order_by(IndicatorValue.trade_date)
        ))
        value_by_date = {value.trade_date: value for value in values}
        if len(value_by_date) != len(values):
            self._mismatch("selected calculation run has duplicate values for a dataset date")

        run_evidence_rows = tuple(self.session.execute(
            select(IndicatorRunInput, IndicatorInputEvidence)
            .join(IndicatorInputEvidence, IndicatorInputEvidence.id == IndicatorRunInput.evidence_id)
            .where(
                IndicatorRunInput.calculation_run_id == run.id,
                IndicatorInputEvidence.trade_date.in_(expected_dates),
            )
            .order_by(IndicatorRunInput.ordinal)
        ))
        evidence_by_date: dict[date, list[tuple[IndicatorRunInput, IndicatorInputEvidence]]] = defaultdict(list)
        for run_input, evidence in run_evidence_rows:
            evidence_by_date[evidence.trade_date].append((run_input, evidence))

        source = {
            "instrument_id": instrument_id,
            "indicator_series_id": series.id,
            "generation_id": generation.id,
            "calculation_run_id": run.id,
            "input_policy_id": policy.id,
            "source_policy_fingerprint": policy.fingerprint,
            "input_hash": run.input_hash,
            "result_hash": run.result_hash,
        }
        rows: list[dict[str, object]] = []
        for trade_date in expected_dates:
            value = value_by_date.get(trade_date)
            if value is None:
                raise BacktestIndicatorSnapshotError(
                    "indicator_value_missing",
                    f"indicator value is missing for instrument {instrument_id} on {trade_date}",
                    details=_value_error_details(
                        indicator_kind=indicator_kind, instrument_id=instrument_id,
                        trade_date=trade_date, value=None,
                    ),
                )
            error_details = _value_error_details(
                indicator_kind=indicator_kind, instrument_id=instrument_id,
                trade_date=trade_date, value=value,
            )
            linked_evidence = evidence_by_date.get(trade_date, [])
            if len(linked_evidence) != 1:
                self._mismatch(
                    f"expected one exact input evidence row for instrument {instrument_id} on {trade_date}",
                    details=error_details,
                )
            run_input, evidence = linked_evidence[0]
            if value.input_prefix_hash != run_input.prefix_hash:
                self._mismatch("indicator value prefix does not match its selected run input", details=error_details)
            price = prices[(instrument_id, trade_date)]
            membership = memberships[(instrument_id, trade_date)]
            self._validate_price_evidence(
                instrument_id=instrument_id,
                trade_date=trade_date,
                price=price,
                membership=membership,
                evidence=evidence,
                policy=policy,
                error_details=error_details,
            )
            if not self._valid_value_shape(value):
                self._mismatch(
                    "indicator value has an invalid status/value/reason combination", details=error_details
                )
            row = self._row_material(
                value=value, run_input=run_input, evidence=evidence, price=price,
                error_details=error_details,
            )
            rows.append(row)
        return source, rows

    def _validate_price_evidence(
        self,
        *,
        instrument_id: int,
        trade_date: date,
        price: BacktestDatasetPrice,
        membership: BacktestDatasetMembership,
        evidence: IndicatorInputEvidence,
        policy: IndicatorInputPolicy,
        error_details: dict[str, object],
    ) -> None:
        key = (instrument_id, trade_date)
        instrument = self.session.get(Instrument, instrument_id)
        observation = self.session.get(PriceObservation, evidence.price_observation_id) if evidence.price_observation_id else None
        identity = self.session.get(
            PriceObservationIdentitySnapshot, evidence.price_observation_identity_snapshot_id
        ) if evidence.price_observation_identity_snapshot_id else None
        if (
            membership.price_expectation != "expected"
            or membership.trading_status not in {"trading", "normal"}
            or membership.membership_evidence_state != "observed"
            or membership.security_type != "stock"
            or membership.quality_status != "valid"
            or instrument is None
            or instrument.listing_status != "listed"
            or instrument.security_type != "stock"
            or evidence.input_status != "eligible"
            or evidence.reason_code is not None
            or evidence.trade_date != trade_date
            or evidence.instrument_id != instrument_id
            or not evidence.provider_symbol
            or evidence.source_symbol_id is None
            or evidence.price_observation_id is None
            or evidence.price_observation_identity_snapshot_id is None
            or evidence.provider_symbol_mapping_id is None
            or evidence.input_policy_id != policy.id
            or evidence.resolver_version is None
            or evidence.resolved_at is None
            or evidence.mapping_status != "matched"
            or evidence.provider != policy.provider
            or evidence.provider != price.provider
            or evidence.adjustment_type != policy.adjustment_type
            or evidence.adjustment_type != price.adjustment_type
            or evidence.parser_version not in set(policy.allowed_parser_versions or [])
            or _as_utc(evidence.observed_at) is None
            or _as_utc(evidence.observed_at) > _as_utc(policy.observation_cutoff)
            or not _is_hash(evidence.payload_hash)
            or not _is_hash(evidence.evidence_key)
            or evidence.source_symbol_id != price.source_symbol_id
            or evidence.price_observation_id != price.source_observation_id
            or evidence.payload_hash != price.source_payload_hash
            or list(evidence.correction_ids or []) != list(price.correction_ids or [])
            or observation is None
            or observation.symbol_id != evidence.source_symbol_id
            or observation.trade_date != trade_date
            or observation.provider != evidence.provider
            or observation.adjustment_type != evidence.adjustment_type
            or observation.parser_version != evidence.parser_version
            or observation.payload_hash != evidence.payload_hash
            or _as_utc(observation.observed_at) != _as_utc(evidence.observed_at)
            or identity is None
            or identity.price_observation_id != observation.id
            or identity.instrument_id != instrument_id
            or identity.provider_symbol_mapping_id != evidence.provider_symbol_mapping_id
            or identity.provider != evidence.provider
            or identity.provider_symbol != evidence.provider_symbol
            or identity.mapping_status != "matched"
            or identity.mapping_valid_from != evidence.mapping_valid_from
            or identity.mapping_valid_to != evidence.mapping_valid_to
            or identity.resolver_version != evidence.resolver_version
            or _as_utc(identity.resolved_at) != _as_utc(evidence.resolved_at)
            or (identity.mapping_valid_from is not None and trade_date < identity.mapping_valid_from)
            or (identity.mapping_valid_to is not None and trade_date >= identity.mapping_valid_to)
        ):
            self._mismatch(f"dataset price and indicator evidence disagree for {key}", details=error_details)

        corrections = tuple(self.session.scalars(
            select(OhlcCorrection)
            .where(
                OhlcCorrection.symbol_id == evidence.source_symbol_id,
                OhlcCorrection.trade_date == trade_date,
                OhlcCorrection.status == "APPROVED",
            )
            .order_by(OhlcCorrection.id)
        ))
        latest_by_field = {}
        for correction in corrections:
            latest_by_field[correction.field_name] = correction
        expected_correction_ids = [latest_by_field[field].id for field in sorted(latest_by_field)]
        if expected_correction_ids != list(price.correction_ids or []):
            self._mismatch(
                f"dataset correction evidence is not the latest approved set for {key}", details=error_details
            )

        corrected = {
            "open": observation.open,
            "high": observation.high,
            "low": observation.low,
            "close": observation.close,
            "volume": observation.volume,
        }
        for field, correction in latest_by_field.items():
            if field not in corrected:
                continue
            raw = correction.corrected_value
            if isinstance(raw, dict):
                raw = raw.get("value")
            try:
                number = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                self._mismatch(f"approved correction cannot be reproduced for {key}", details=error_details)
            if not number.is_finite() or (field == "volume" and number != number.to_integral_value()):
                self._mismatch(
                    f"approved correction is not a finite OHLCV value for {key}", details=error_details
                )
            corrected[field] = int(number) if field == "volume" else number

        if (
            corrected["open"] != price.open or corrected["high"] != price.high or corrected["low"] != price.low
            or corrected["close"] != price.close or corrected["volume"] != price.volume
            or evidence.high != price.high or evidence.low != price.low
            or evidence.close != price.close or evidence.volume != price.volume
        ):
            self._mismatch(f"dataset OHLCV and indicator evidence disagree for {key}", details=error_details)

        quality = membership.quality_evidence if isinstance(membership.quality_evidence, dict) else {}
        if (
            quality.get("source_observation_id") != price.source_observation_id
            or quality.get("source_payload_hash") != price.source_payload_hash
            or list(quality.get("correction_ids") or []) != list(price.correction_ids or [])
        ):
            self._mismatch(
                f"dataset membership evidence does not corroborate the price for {key}", details=error_details
            )

    @staticmethod
    def _valid_value_shape(value: IndicatorValue) -> bool:
        if value.available_observations < 0:
            return False
        if value.status == "available":
            return value.value is not None and value.value.is_finite() and value.reason_code is None
        if value.status == "warming_up":
            return value.value is None and value.reason_code == "warming_up"
        if value.status == "data_unavailable":
            return value.value is None and bool(value.reason_code) and value.reason_code != "warming_up"
        return False

    @staticmethod
    def _row_material(
        *, value: IndicatorValue, run_input: IndicatorRunInput, evidence: IndicatorInputEvidence,
        price: BacktestDatasetPrice, error_details: dict[str, object],
    ) -> dict[str, object]:
        if (
            evidence.source_symbol_id is None
            or evidence.price_observation_id is None
            or evidence.price_observation_identity_snapshot_id is None
            or evidence.provider_symbol_mapping_id is None
            or evidence.observed_at is None
            or evidence.resolver_version is None
            or evidence.resolved_at is None
            or evidence.adjustment_type is None
            or evidence.parser_version is None
            or evidence.high is None
            or evidence.low is None
            or evidence.close is None
            or evidence.volume is None
        ):
            raise BacktestIndicatorSnapshotError(
                "indicator_evidence_mismatch",
                "selected evidence is missing required identity or OHLCV facts",
                details=error_details,
            )
        fields: dict[str, object] = {
            "instrument_id": evidence.instrument_id,
            "trade_date": evidence.trade_date,
            "source_value_id": value.id,
            "source_run_input_id": run_input.id,
            "source_evidence_id": evidence.id,
            "value": value.value,
            "status": value.status,
            "reason_code": value.reason_code,
            "available_observations": value.available_observations,
            "input_prefix_hash": value.input_prefix_hash,
            "source_evidence_key": evidence.evidence_key,
            "source_symbol_id": evidence.source_symbol_id,
            "price_observation_id": evidence.price_observation_id,
            "identity_snapshot_id": evidence.price_observation_identity_snapshot_id,
            "provider_symbol_mapping_id": evidence.provider_symbol_mapping_id,
            "mapping_status": evidence.mapping_status,
            "mapping_valid_from": evidence.mapping_valid_from,
            "mapping_valid_to": evidence.mapping_valid_to,
            "resolver_version": evidence.resolver_version,
            "resolved_at": _as_utc(evidence.resolved_at),
            "provider": evidence.provider,
            "provider_symbol": evidence.provider_symbol,
            "adjustment_type": evidence.adjustment_type,
            "parser_version": evidence.parser_version,
            "observed_at": _as_utc(evidence.observed_at),
            "payload_hash": evidence.payload_hash,
            "open": price.open,
            "high": evidence.high,
            "low": evidence.low,
            "close": evidence.close,
            "volume": evidence.volume,
            "correction_ids": list(evidence.correction_ids or []),
            "validation_evidence": list(evidence.validation_evidence or []),
        }
        fields["row_hash"] = _hash(fields)
        return fields

    @staticmethod
    def _mismatch(message: str, *, details: dict[str, object] | None = None) -> None:
        raise BacktestIndicatorSnapshotError("indicator_evidence_mismatch", message, details=details)


def _hash(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _value_error_details(
    *, indicator_kind: str, instrument_id: int, trade_date: date, value: IndicatorValue | None,
) -> dict[str, object]:
    status = value.status if value is not None else None
    reason_code = value.reason_code if value is not None else None
    return {
        "indicator_kind": indicator_kind,
        "instrument_id": instrument_id,
        "trade_date": trade_date.isoformat(),
        "status": status,
        "reason_code": reason_code,
        "original_status": status,
        "original_reason_code": reason_code,
    }


def _is_hash(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
