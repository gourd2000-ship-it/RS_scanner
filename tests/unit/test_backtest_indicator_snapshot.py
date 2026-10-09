"""Backtest indicator snapshots pin dataset-matched indicator evidence."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
    BacktestDatasetIndicatorSnapshotSource,
    BacktestDatasetMembership,
    BacktestDatasetPrice,
)
from app.models.data_quality import PriceObservation
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
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.backtest_indicator_snapshot_repository import (
    BacktestIndicatorSnapshotError,
    BacktestIndicatorSnapshotRepository,
)


TRADE_DATE = date(2024, 1, 2)
OBSERVED_AT = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _seed(session: Session, *, kind: str = "volume_sma") -> tuple[BacktestDataset, int]:
    manifest = {
        "publication_scope": "complete_segments_only",
        "range": {"start": TRADE_DATE.isoformat(), "end": TRADE_DATE.isoformat()},
        "complete_segments": [{"instrument_id": 1, "year": TRADE_DATE.year}],
        "coverage": {"valid": 1, "complete_segments": 1},
    }
    dataset = BacktestDataset(
        dataset_id="clean-dataset-1", manifest_hash="a" * 64,
        final_manifest_hash=_hash(manifest), range_start=TRADE_DATE, range_end=TRADE_DATE,
        markets=["KOSPI"], reconstruction_mode="historical_reconstructed", as_known_at=None,
        adjustment_policy="kiwoom:1", policy_version="ohlcv-v1", preparation_start=None,
        manifest=manifest, status="active",
    )
    instrument = Instrument(
        id=1, krx_short_code="005930", name="Samsung", market="KOSPI", security_type="stock",
        listing_status="listed",
    )
    symbol = Symbol(id=10, code="005930", name="Samsung", market="KOSPI", instrument_id=1)
    mapping = ProviderSymbol(
        id=20, instrument_id=1, provider="kiwoom", provider_symbol="A005930",
        mapping_status="matched", valid_from=date(1990, 1, 1), valid_to=None,
    )
    observation = PriceObservation(
        id=30, symbol_id=10, trade_date=TRADE_DATE, open=Decimal("100"), high=Decimal("110"),
        low=Decimal("90"), close=Decimal("105"), volume=1000, change_rate=Decimal("0"),
        provider="kiwoom", parser_version="parser-v1", adjustment_type="1",
        payload_hash="b" * 64, observed_at=OBSERVED_AT.replace(tzinfo=None),
    )
    identity = PriceObservationIdentitySnapshot(
        id=40, price_observation_id=30, instrument_id=1, provider_symbol_mapping_id=20,
        provider="kiwoom", provider_symbol="A005930", mapping_status="matched",
        mapping_valid_from=date(1990, 1, 1), mapping_valid_to=None,
        resolver_version="resolver-v1", resolved_at=OBSERVED_AT,
    )
    session.add_all([instrument, symbol, mapping, observation, identity, dataset])
    session.flush()
    session.add_all([
        BacktestDatasetMembership(
            backtest_dataset_id=dataset.id, instrument_id=1, trade_date=TRADE_DATE,
            market="KOSPI", security_type="stock", membership_evidence_state="observed",
            trading_status="trading", price_expectation="expected", event_revision_hashes=[],
            code="005930", name="Samsung", quality_status="valid", quality_reason=None,
            quality_evidence={
                "source_observation_id": 30, "source_payload_hash": "b" * 64, "correction_ids": [],
            },
        ),
        BacktestDatasetPrice(
            backtest_dataset_id=dataset.id, instrument_id=1, source_symbol_id=10,
            source_observation_id=30, code="005930", name="Samsung", market="KOSPI",
            trade_date=TRADE_DATE, open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("105"), volume=1000, change_rate=Decimal("0"), provider="kiwoom",
            adjustment_type="1", source_payload_hash="b" * 64, correction_ids=[],
        ),
    ])
    policy = IndicatorInputPolicy(
        provider="kiwoom", adjustment_type="1", allowed_parser_versions=["parser-v1"],
        observation_cutoff=OBSERVED_AT, selector_version="selector-v1", validation_version="validation-v1",
        correction_version="correction-v1", fingerprint="c" * 64,
    )
    session.add(policy)
    session.flush()
    series = IndicatorSeries(
        instrument_id=1, indicator_kind=kind,
        input_field="volume" if kind == "volume_sma" else "high-low-close",
        periods="50" if kind == "volume_sma" else "14",
        input_policy_version="validated-observation-ohlcv-v1",
        formula_version="volume-sma-v1" if kind == "volume_sma" else "wilder-atr-14-v1",
        source_provider="kiwoom", adjustment_policy="1", allowed_parser_versions=["parser-v1"],
        observation_cutoff=OBSERVED_AT, input_policy_id=policy.id,
    )
    session.add(series)
    session.flush()
    generation = IndicatorGeneration(series_id=series.id, generation=1, status="current")
    session.add(generation)
    session.flush()
    run = IndicatorCalculationRun(
        generation_id=generation.id, series_id=series.id, run_kind="backfill", status="completed",
        input_cutoff=TRADE_DATE, range_start=TRADE_DATE, range_end=TRADE_DATE,
        input_hash="d" * 64, result_hash="e" * 64, input_count=1, result_count=1,
        completed_at=OBSERVED_AT,
    )
    session.add(run)
    session.flush()
    evidence = IndicatorInputEvidence(
        input_policy_id=policy.id, trade_date=TRADE_DATE, instrument_id=1, source_symbol_id=10,
        price_observation_id=30, price_observation_identity_snapshot_id=40,
        provider_symbol_mapping_id=20, provider="kiwoom", provider_symbol="A005930",
        adjustment_type="1", parser_version="parser-v1", high=Decimal("110"), low=Decimal("90"),
        close=Decimal("105"), volume=1000, observed_at=OBSERVED_AT, payload_hash="b" * 64,
        mapping_status="matched", mapping_valid_from=date(1990, 1, 1),
        resolver_version="resolver-v1", resolved_at=OBSERVED_AT, correction_ids=[],
        validation_evidence=[], input_status="eligible", reason_code=None, evidence_key="f" * 64,
    )
    session.add(evidence)
    session.flush()
    session.add(IndicatorRunInput(
        calculation_run_id=run.id, evidence_id=evidence.id, ordinal=0, prefix_hash="1" * 64,
    ))
    value = IndicatorValue(
        calculation_run_id=run.id, generation_id=generation.id, indicator_kind=kind,
        period=50 if kind == "volume_sma" else 14, trade_date=TRADE_DATE,
        value=Decimal("1000") if kind == "volume_sma" else Decimal("20"),
        status="available", reason_code=None, available_observations=50 if kind == "volume_sma" else 14,
        input_prefix_hash="1" * 64,
    )
    session.add(value)
    session.flush()
    return dataset, run.id


def _create(session: Session, dataset: BacktestDataset, run_id: int):
    return BacktestIndicatorSnapshotRepository(session).create_snapshot(
        dataset_id=dataset.dataset_id,
        indicator_kind="volume_sma",
        source_run_ids_by_instrument={1: run_id},
    )


def test_snapshot_matches_complete_dataset_captures_lineage_and_retries_idempotently():
    session = _session()
    dataset, run_id = _seed(session)

    first = _create(session, dataset, run_id)
    second = _create(session, dataset, run_id)

    assert first.id == second.id
    assert first.status == "complete"
    assert first.dataset_id == dataset.dataset_id
    assert first.dataset_manifest_hash == dataset.final_manifest_hash
    assert first.indicator_kind == "volume_sma" and first.period == 50
    assert first.source_count == first.row_count == 1
    assert len(first.input_hash) == len(first.result_hash) == len(first.content_hash) == 64
    source = session.scalar(select(BacktestDatasetIndicatorSnapshotSource).where(
        BacktestDatasetIndicatorSnapshotSource.snapshot_id == first.id,
    ))
    row = session.scalar(select(BacktestDatasetIndicatorSnapshotRow).where(
        BacktestDatasetIndicatorSnapshotRow.snapshot_id == first.id,
    ))
    assert source.indicator_series_id == 1
    assert source.generation_id == 1 and source.calculation_run_id == run_id
    assert source.source_policy_fingerprint == "c" * 64
    assert row.source_value_id is not None
    assert row.source_evidence_id is not None
    assert row.price_observation_id == 30 and row.identity_snapshot_id == 40
    assert row.high == Decimal("110") and row.volume == 1000
    assert row.value == Decimal("1000") and row.status == "available"
    assert row.input_prefix_hash == "1" * 64


@pytest.mark.parametrize(
    "change, reason",
    [
        ("incomplete_dataset", "dataset_not_complete"),
        ("wrong_observation", "indicator_evidence_mismatch"),
        ("wrong_ohlcv", "indicator_evidence_mismatch"),
        ("wrong_parser", "indicator_evidence_mismatch"),
        ("identity_unmatched", "indicator_evidence_mismatch"),
        ("missing_value", "indicator_value_missing"),
    ],
)
def test_snapshot_rejects_incomplete_or_unproven_dataset_input_without_persisting(change, reason):
    session = _session()
    dataset, run_id = _seed(session)
    if change == "incomplete_dataset":
        dataset.manifest = {"publication_scope": "partial"}
    elif change == "wrong_observation":
        evidence = session.scalar(select(IndicatorInputEvidence))
        evidence.price_observation_id = 999
    elif change == "wrong_ohlcv":
        evidence = session.scalar(select(IndicatorInputEvidence))
        evidence.high = Decimal("111")
    elif change == "wrong_parser":
        evidence = session.scalar(select(IndicatorInputEvidence))
        evidence.parser_version = "parser-v2"
    elif change == "identity_unmatched":
        evidence = session.scalar(select(IndicatorInputEvidence))
        evidence.mapping_status = "ambiguous"
    elif change == "missing_value":
        session.query(IndicatorValue).delete()
    session.flush()

    with pytest.raises(BacktestIndicatorSnapshotError) as error:
        _create(session, dataset, run_id)

    assert error.value.reason_code == reason
    assert session.scalar(select(BacktestDatasetIndicatorSnapshot.id)) is None


def test_completed_snapshot_does_not_change_when_indicator_generation_advances():
    session = _session()
    dataset, run_id = _seed(session)
    snapshot = _create(session, dataset, run_id)
    original = session.scalar(select(BacktestDatasetIndicatorSnapshotRow).where(
        BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
    ))
    before = (snapshot.content_hash, original.source_value_id, original.value, original.input_prefix_hash)

    old_generation = session.get(IndicatorGeneration, 1)
    old_generation.status = "superseded"
    new_generation = IndicatorGeneration(series_id=1, generation=2, status="current")
    session.add(new_generation)
    session.flush()
    new_run = IndicatorCalculationRun(
        generation_id=new_generation.id, series_id=1, run_kind="incremental", status="completed",
        input_cutoff=TRADE_DATE, range_start=TRADE_DATE, range_end=TRADE_DATE,
        input_hash="2" * 64, result_hash="3" * 64, input_count=1, result_count=1,
        completed_at=OBSERVED_AT,
    )
    session.add(new_run)
    session.flush()
    evidence = session.scalar(select(IndicatorInputEvidence))
    session.add(IndicatorRunInput(
        calculation_run_id=new_run.id, evidence_id=evidence.id, ordinal=0, prefix_hash="4" * 64,
    ))
    session.add(IndicatorValue(
        calculation_run_id=new_run.id, generation_id=new_generation.id, indicator_kind="volume_sma",
        period=50, trade_date=TRADE_DATE, value=Decimal("999"), status="available",
        available_observations=50, input_prefix_hash="4" * 64,
    ))
    session.flush()
    session.expire_all()

    current = session.get(BacktestDatasetIndicatorSnapshot, snapshot.id)
    pinned = session.scalar(select(BacktestDatasetIndicatorSnapshotRow).where(
        BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
    ))
    assert (current.content_hash, pinned.source_value_id, pinned.value, pinned.input_prefix_hash) == before


def test_atr14_uses_same_contract_with_its_fixed_formula_and_period():
    session = _session()
    dataset, run_id = _seed(session, kind="atr")

    snapshot = BacktestIndicatorSnapshotRepository(session).create_snapshot(
        dataset_id=dataset.dataset_id,
        indicator_kind="atr",
        source_run_ids_by_instrument={1: run_id},
    )

    assert snapshot.indicator_kind == "atr" and snapshot.period == 14
    assert snapshot.formula_version == "wilder-atr-14-v1"


@pytest.mark.parametrize(
    "status, value, reason",
    [
        ("warming_up", None, "warming_up"),
        ("data_unavailable", None, "missing_selected_source"),
    ],
)
def test_snapshot_preserves_nonavailable_value_status_and_reason(status, value, reason):
    session = _session()
    dataset, run_id = _seed(session)
    source_value = session.scalar(select(IndicatorValue))
    source_value.value = value
    source_value.status = status
    source_value.reason_code = reason
    session.flush()

    snapshot = _create(session, dataset, run_id)
    row = session.scalar(select(BacktestDatasetIndicatorSnapshotRow).where(
        BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
    ))

    assert row.value is None
    assert row.status == status
    assert row.reason_code == reason


@pytest.mark.parametrize(
    "change", ["missing_evidence", "mismatched_ohlcv", "unproven_input_status"]
)
def test_nonavailable_value_requires_exact_input_evidence_and_keeps_error_context(change):
    session = _session()
    dataset, run_id = _seed(session)
    source_value = session.scalar(select(IndicatorValue))
    source_value.value = None
    source_value.status = "data_unavailable"
    source_value.reason_code = "missing_selected_source"
    evidence = session.scalar(select(IndicatorInputEvidence))
    if change == "missing_evidence":
        session.query(IndicatorRunInput).delete()
    else:
        if change == "mismatched_ohlcv":
            evidence.high = Decimal("111")
        else:
            evidence.input_status = "review_required"
            evidence.reason_code = "open_validation_case"
    session.flush()

    with pytest.raises(BacktestIndicatorSnapshotError) as error:
        _create(session, dataset, run_id)

    assert error.value.reason_code == "indicator_evidence_mismatch"
    assert error.value.details == {
        "indicator_kind": "volume_sma",
        "instrument_id": 1,
        "trade_date": TRADE_DATE.isoformat(),
        "status": "data_unavailable",
        "reason_code": "missing_selected_source",
        "original_status": "data_unavailable",
        "original_reason_code": "missing_selected_source",
    }
    assert session.scalar(select(BacktestDatasetIndicatorSnapshot.id)) is None
