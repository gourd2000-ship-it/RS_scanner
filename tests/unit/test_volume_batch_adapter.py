"""Daily Volume MA50 policy, persistence and checkpoint regression coverage."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.indicator import IndicatorCalculationRun, IndicatorSeries
from app.repositories.memory_batch_checkpoint_repository import MemoryBatchCheckpointRepository
from app.services.batch.volume_adapter import (
    VolumeBatchOutcome, calculate_daily_volume_sma50, completed_volume_outcome,
    record_volume_checkpoint, volume_sma50_enabled,
)
from app.services.indicators.volume_calculation_service import VolumeSmaCalculationService
from tests.unit.test_indicator_calculation_service import _observation, session
from tests.unit.test_volume_calculation_service import seed_history, sqlite_generated_keys


def volume_settings(**kwargs):
    return Settings(
        _env_file=None, volume_sma50_enabled=True,
        volume_sma50_source_provider="kiwoom", volume_sma50_adjustment_type="1",
        volume_sma50_allowed_parser_versions="kiwoom-v2", **kwargs,
    )


def test_volume_is_disabled_and_requires_explicit_source_policy_by_default():
    settings = Settings(_env_file=None)
    assert not volume_sma50_enabled(settings)
    assert settings.volume_sma50_source_provider == ""
    assert settings.volume_sma50_adjustment_type == ""
    assert settings.volume_sma50_allowed_parser_versions == ""


@pytest.mark.parametrize("field,value,reason", [
    ("volume_sma50_source_provider", "", "volume_source_policy_unconfigured"),
    ("volume_sma50_adjustment_type", "", "volume_source_policy_unconfigured"),
    ("volume_sma50_allowed_parser_versions", "", "volume_source_policy_unconfigured"),
    ("volume_sma50_source_provider", "kiwoom\nother", "volume_source_policy_invalid"),
    ("volume_sma50_adjustment_type", "1,2", "volume_source_policy_invalid"),
    ("volume_sma50_allowed_parser_versions", "kiwoom-v2,,other", "volume_source_policy_invalid"),
])
def test_missing_or_invalid_policy_fails_safely_without_querying(field, value, reason):
    settings = volume_settings().model_copy(update={field: value})
    result = calculate_daily_volume_sma50(SimpleNamespace(session=object()),
                                        target_date=datetime.now(UTC).date(), settings=settings)
    assert result == VolumeBatchOutcome.failure(processed=0, failed=1, reason=reason)


def test_volume_checkpoint_is_separate_and_only_completed_outcomes_are_resumable():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=12)
    repository.create_checkpoint(12, "ema", status="completed")
    assert completed_volume_outcome(context) is None
    record_volume_checkpoint(context, VolumeBatchOutcome.skipped("validation_gate_blocked"))
    checkpoint = repository.get_checkpoint(12, "volume_sma50")
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_failed == 1
    assert json.loads(checkpoint.step_metadata) == {"outcome": "skipped", "reason": "validation_gate_blocked"}
    assert completed_volume_outcome(context) is None
    record_volume_checkpoint(context, VolumeBatchOutcome.completed(processed=3))
    assert completed_volume_outcome(context) == VolumeBatchOutcome.completed(processed=3)
    assert repository.get_checkpoint(12, "ema").status == "completed"


def test_completed_volume_checkpoint_does_not_hide_changed_or_missing_policy():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=13)
    settings = volume_settings()
    record_volume_checkpoint(context, VolumeBatchOutcome.completed(processed=2), settings=settings)
    assert completed_volume_outcome(context, settings=settings).processed == 2
    assert completed_volume_outcome(context, settings=settings.model_copy(update={
        "volume_sma50_source_provider": "naver"})) is None
    assert completed_volume_outcome(context, settings=Settings(_env_file=None)) is None


def test_daily_adapter_extends_and_rebuilds_one_volume_series(session):
    instrument, symbol, mapping, dates = seed_history(session, 2)
    context = SimpleNamespace(session=session)
    settings = volume_settings()
    assert calculate_daily_volume_sma50(context, target_date=dates[0], settings=settings).processed == 1
    assert calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings).processed == 1
    assert calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings).processed == 1
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=dates[0], close="101", observed_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings).processed == 1
    assert session.scalars(select(IndicatorCalculationRun.run_kind).order_by(IndicatorCalculationRun.id)).all() == [
        "backfill", "incremental", "rebuild",
    ]
    assert session.scalars(select(IndicatorSeries.indicator_kind)).all() == ["volume_sma"]


def test_daily_adapter_keeps_storage_failure_evidence_and_retries(session, monkeypatch):
    _, _, _, dates = seed_history(session, 2)
    context = SimpleNamespace(session=session)
    settings = volume_settings()
    service = VolumeSmaCalculationService(session)
    original = service.repository.complete_volume_run

    def fail(**_kwargs):
        raise RuntimeError("private provider detail")

    monkeypatch.setattr(service.repository, "complete_volume_run", fail)
    monkeypatch.setattr("app.services.batch.volume_adapter.VolumeSmaCalculationService", lambda _: service)
    failed = calculate_daily_volume_sma50(context, target_date=dates[-1], settings=settings)
    assert failed.outcome == "failed" and failed.failed == 1
    assert failed.reason == "VolumeCalculationError"
    session.commit()
    runs = session.scalars(select(IndicatorCalculationRun)).all()
    assert len(runs) == 1 and runs[0].status == "failed"
    assert runs[0].failure_reason == "RuntimeError"
    monkeypatch.setattr(service.repository, "complete_volume_run", original)
    assert calculate_daily_volume_sma50(context, target_date=dates[-1], settings=settings).outcome == "completed"
    assert session.scalars(select(IndicatorCalculationRun.status).order_by(IndicatorCalculationRun.id)).all() == [
        "failed", "completed",
    ]


def test_daily_adapter_records_query_failure_without_exposing_message(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private connection detail")

    monkeypatch.setattr("app.services.batch.volume_adapter.expected_trade_dates", fail)
    result = calculate_daily_volume_sma50(SimpleNamespace(session=SimpleNamespace(begin_nested=nullcontext)),
                                        target_date=datetime.now(UTC).date(), settings=volume_settings())
    assert result.reason == "RuntimeError" and result.outcome == "failed"


def test_daily_adapter_continues_other_series_after_failure(monkeypatch):
    day = datetime.now(UTC).date()
    monkeypatch.setattr("app.services.batch.volume_adapter.expected_trade_dates", lambda *_args, **_kwargs: (day,))
    monkeypatch.setattr("app.services.batch.volume_adapter.eligible_instrument_ids", lambda *_args, **_kwargs: (1, 2))
    completed = []

    def calculate(*, instrument_id, **_kwargs):
        if instrument_id == 1:
            raise RuntimeError("private detail")
        completed.append(instrument_id)

    monkeypatch.setattr("app.services.batch.volume_adapter.VolumeSmaCalculationService",
                        lambda _: SimpleNamespace(calculate=calculate))
    result = calculate_daily_volume_sma50(SimpleNamespace(session=SimpleNamespace(begin_nested=nullcontext)),
                                        target_date=day, settings=volume_settings())
    assert completed == [2]
    assert result == VolumeBatchOutcome.failure(processed=1, failed=1, reason="RuntimeError")


@pytest.mark.parametrize("reason", ["volume_session_unavailable", "target_date_observations_missing", "no_eligible_identity_inputs"])
def test_daily_adapter_records_missing_input_evidence(monkeypatch, reason):
    day = datetime.now(UTC).date()
    monkeypatch.setattr("app.services.batch.volume_adapter.expected_trade_dates",
                        lambda *_args, **_kwargs: () if reason == "target_date_observations_missing" else (day,))
    monkeypatch.setattr("app.services.batch.volume_adapter.eligible_instrument_ids", lambda *_args, **_kwargs: ())
    context = SimpleNamespace(session=None if reason == "volume_session_unavailable" else SimpleNamespace(begin_nested=nullcontext))
    assert calculate_daily_volume_sma50(context, target_date=day, settings=volume_settings()) == VolumeBatchOutcome.skipped(reason)
