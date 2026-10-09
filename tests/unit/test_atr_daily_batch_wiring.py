"""Both daily entrypoints keep EMA and ATR results independent."""

import json
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.data_quality import ValidationRun
from app.services.batch.context import build_memory_batch_context
from app.services.batch.ema_adapter import EmaBatchOutcome
from app.services.batch.orchestrator import BatchOrchestrator
from app.services.batch.run_daily_job import run_daily_job
from app.services.batch.sync_prices import PriceSyncResult
from app.services.batch.atr_adapter import AtrBatchOutcome, record_atr_checkpoint
from app.services.batch.volume_adapter import VolumeBatchOutcome
from app.services.validation.data_quality import ValidationResult


DAY = date(2025, 9, 17)


def settings(**kwargs):
    return Settings(_env_file=None, atr14_enabled=True, ema_enabled=True,
                    atr14_source_provider="kiwoom", atr14_adjustment_type="1",
                    atr14_allowed_parser_versions="kiwoom-v2",
                    validation_enabled=True, validation_mode="enforce", **kwargs)


def patch_direct(monkeypatch, effective_settings, events, *, blocked=False):
    module = "app.services.batch.run_daily_job"
    monkeypatch.setattr(f"{module}.get_settings", lambda: effective_settings)
    monkeypatch.setattr(f"{module}.sync_symbols", lambda *_: [])
    monkeypatch.setattr(f"{module}.sync_benchmarks", lambda *_: {})
    monkeypatch.setattr(f"{module}.sync_prices", lambda *_args, **_kwargs: events.append("prices") or {})
    validation = SimpleNamespace(
        run=SimpleNamespace(id=3, validation_status="blocked" if blocked else "passed", trade_date=DAY),
        would_block=blocked, to_dict=lambda: {},
    )
    monkeypatch.setattr(f"{module}.validate_crawl_job", lambda *_args, **_kwargs: events.append("validation") or validation)
    monkeypatch.setattr(f"{module}.write_validation_report", lambda _: "report.json")
    monkeypatch.setattr(f"{module}.calculate_rs", lambda *_args, **_kwargs: events.append("rs") or {"KOSPI": [object()]})
    monkeypatch.setattr(f"{module}.ensure_crawl_quality_report", lambda *_args, **_kwargs: None)
    for method in ("send_batch_success_sync", "send_batch_failure_sync"):
        monkeypatch.setattr(f"{module}.notification_service.{method}", lambda **_: None)
    context = build_memory_batch_context()
    context.target_date = DAY
    context.session = object()
    return context


@pytest.mark.parametrize("failed_indicator", [None, "ema", "atr14"])
def test_direct_batch_collects_independent_indicator_results(monkeypatch, failed_indicator):
    events = []
    context = patch_direct(monkeypatch, settings(), events)

    def ema(*_args, **_kwargs):
        events.append("ema")
        if failed_indicator == "ema":
            raise RuntimeError("private detail")
        return EmaBatchOutcome.completed(processed=2)

    def atr(*_args, **_kwargs):
        events.append("atr14")
        if failed_indicator == "atr14":
            raise RuntimeError("private detail")
        return AtrBatchOutcome.completed(processed=3)

    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_ema", ema)
    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_atr14", atr)
    result = run_daily_job(context, source=object())
    assert events == ["prices", "validation", "rs", "ema", "atr14"]
    assert result["rs_results"] == {"KOSPI": 1}
    for name in ("ema", "atr14"):
        assert result[name]["outcome"] == ("failed" if name == failed_indicator else "completed")
        checkpoint = context.checkpoint_repository.get_checkpoint(result["job_id"], name)
        assert checkpoint.status == ("completed_with_errors" if name == failed_indicator else "completed")
    assert context.crawl_job_repository.get_latest().status == ("completed_with_errors" if failed_indicator else "completed")


def test_direct_validation_block_overrides_completed_atr_checkpoint(monkeypatch):
    events = []
    context = patch_direct(monkeypatch, settings(), events, blocked=True)
    context.job_id = context.crawl_job_repository.create_job("daily_full").id
    record_atr_checkpoint(context, AtrBatchOutcome.completed(processed=3))

    def fail(*_args, **_kwargs):
        raise AssertionError("validation-blocked indicators must not run")

    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_ema", fail)
    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_atr14", fail)
    result = run_daily_job(context, source=object())
    assert events == ["prices", "validation"]
    assert result["atr14"]["outcome"] == "skipped"
    checkpoint = context.checkpoint_repository.get_checkpoint(result["job_id"], "atr14")
    assert checkpoint.status == "completed_with_errors"
    assert json.loads(checkpoint.step_metadata)["reason"] == "validation_gate_blocked"


def test_direct_resume_reuses_atr_completion_and_retries_failure(monkeypatch):
    events = []
    context = patch_direct(monkeypatch, settings(), events)
    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_ema", lambda *_args, **_kwargs: EmaBatchOutcome.completed(processed=2))
    outcomes = iter([AtrBatchOutcome.failure(processed=0, failed=1, reason="RuntimeError"),
                     AtrBatchOutcome.completed(processed=3)])
    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_atr14", lambda *_args, **_kwargs: next(outcomes))
    first = run_daily_job(context, source=object())
    second = run_daily_job(context, source=object())
    third = run_daily_job(context, source=object())
    assert first["atr14"]["outcome"] == "failed"
    assert second["atr14"] == third["atr14"] == AtrBatchOutcome.completed(processed=3).to_dict()
    assert first["job_id"] == second["job_id"] == third["job_id"]


def test_direct_batch_skips_atr_when_validation_is_disabled(monkeypatch):
    events = []
    effective_settings = settings().model_copy(update={"validation_enabled": False, "ema_enabled": False})
    context = patch_direct(monkeypatch, effective_settings, events)

    def fail(*_args, **_kwargs):
        raise AssertionError("ATR requires a validation decision")

    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_atr14", fail)
    result = run_daily_job(context, source=object())
    assert result["atr14"]["reason"] == "validation_unavailable"
    assert result["atr14"]["outcome"] == "skipped"


def test_default_daily_batch_does_not_execute_or_checkpoint_atr(monkeypatch):
    events = []
    effective_settings = settings().model_copy(update={"atr14_enabled": False, "ema_enabled": False})
    context = patch_direct(monkeypatch, effective_settings, events)

    def fail(*_args, **_kwargs):
        raise AssertionError("disabled ATR must not execute")

    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_daily_atr14", fail)
    result = run_daily_job(context, source=object())
    assert result["atr14"] is None
    assert context.checkpoint_repository.get_checkpoint(result["job_id"], "atr14") is None


def patch_orchestrator(monkeypatch, *, blocked=False):
    effective_settings = settings()
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: effective_settings)
    monkeypatch.setattr("app.services.batch.orchestrator.batch_target_date", lambda _: DAY)
    for method in ("send_batch_success_sync", "send_batch_failure_sync", "send_step_completed_sync"):
        monkeypatch.setattr(f"app.services.batch.orchestrator.notification_service.{method}", lambda **_: None)
    batch = BatchOrchestrator(source=object())
    batch.job_id = 41
    context = build_memory_batch_context()
    context.job_id = batch.job_id
    context.checkpoint_repository.create_checkpoint(batch.job_id, "rs")

    @contextmanager
    def memory_session():
        yield object()

    monkeypatch.setattr("app.services.batch.orchestrator.session_scope", memory_session)
    monkeypatch.setattr("app.services.batch.orchestrator.build_db_batch_context", lambda _: context)
    monkeypatch.setattr("app.services.batch.orchestrator.write_validation_report", lambda _: "report.json")
    monkeypatch.setattr("app.services.batch.orchestrator.DataQualityRepository", lambda _: SimpleNamespace(
        latest_validation_run=lambda **_kwargs: ValidationRun(validator_version="test", mode="enforce",
            validation_status="blocked" if blocked else "passed", expected_symbols=0,
            error_count=0, critical_count=0, warning_count=0)))
    finished = []
    monkeypatch.setattr(batch, "_finish_job", lambda **kwargs: finished.append(kwargs))
    events = []

    def execute(step_name, step_func):
        events.append(step_name)
        if step_name == "validation":
            return ValidationResult(run=ValidationRun(validator_version="test", mode="enforce",
                validation_status="blocked" if blocked else "passed", expected_symbols=0,
                error_count=0, critical_count=0, warning_count=0), cases=[], metrics={})
        if step_name == "prices":
            return PriceSyncResult()
        if step_name == "symbols":
            return []
        if step_name in {"ema", "volume_sma50", "atr14"}:
            return step_func(context)
        return {"KOSPI": [object()]} if step_name == "rs" else {}

    monkeypatch.setattr(batch, "_execute_step", execute)
    return batch, context, events, finished


@pytest.mark.parametrize("failed_indicator", [None, "ema", "atr14"])
def test_orchestrator_persists_and_resumes_independent_indicators(monkeypatch, failed_indicator):
    batch, context, events, finished = patch_orchestrator(monkeypatch)

    def ema(*_args, **_kwargs):
        if failed_indicator == "ema":
            raise RuntimeError("private detail")
        return EmaBatchOutcome.completed(processed=2)

    def atr(*_args, **_kwargs):
        if failed_indicator == "atr14":
            raise RuntimeError("private detail")
        return AtrBatchOutcome.completed(processed=3)

    monkeypatch.setattr("app.services.batch.orchestrator.calculate_daily_ema", ema)
    monkeypatch.setattr("app.services.batch.orchestrator.calculate_daily_atr14", atr)
    result = batch.run_daily_job()
    assert events[-4:] == ["validation", "rs", "ema", "atr14"]
    assert result["ema"]["outcome"] == ("failed" if failed_indicator == "ema" else "completed")
    assert result["atr14"]["outcome"] == ("failed" if failed_indicator == "atr14" else "completed")
    assert finished[-1]["status"] == ("completed_with_errors" if failed_indicator else "completed")
    checkpoint = context.checkpoint_repository.get_checkpoint(41, "atr14")
    assert checkpoint.items_processed == (0 if failed_indicator == "atr14" else 3)
    assert json.loads(checkpoint.step_metadata)["outcome"] == result["atr14"]["outcome"]
    if failed_indicator is not None:
        assert context.checkpoint_repository.get_checkpoint(41, failed_indicator).error_message == "RuntimeError"
    if failed_indicator is None:
        events.clear()
        resumed = batch.run_daily_job()
        assert "ema" not in events and "atr14" not in events
        assert resumed["atr14"] == result["atr14"]


@pytest.mark.parametrize("failed_indicator", ["volume_sma50", "atr14"])
def test_orchestrator_volume_and_atr_steps_fail_independently(monkeypatch, failed_indicator):
    batch, context, events, finished = patch_orchestrator(monkeypatch)
    effective_settings = settings(volume_sma50_enabled=True, volume_sma50_source_provider="kiwoom",
                                  volume_sma50_adjustment_type="1",
                                  volume_sma50_allowed_parser_versions="kiwoom-v2")
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: effective_settings)
    monkeypatch.setattr("app.services.batch.orchestrator.calculate_daily_ema",
                        lambda *_args, **_kwargs: EmaBatchOutcome.completed(processed=2))

    def volume(*_args, **_kwargs):
        if failed_indicator == "volume_sma50":
            raise RuntimeError("private detail")
        return VolumeBatchOutcome.completed(processed=1)

    def atr(*_args, **_kwargs):
        if failed_indicator == "atr14":
            raise RuntimeError("private detail")
        return AtrBatchOutcome.completed(processed=1)

    monkeypatch.setattr("app.services.batch.orchestrator.calculate_daily_volume_sma50", volume)
    monkeypatch.setattr("app.services.batch.orchestrator.calculate_daily_atr14", atr)

    result = batch.run_daily_job()

    assert events[-3:] == ["ema", "volume_sma50", "atr14"]
    assert result["volume_sma50"]["outcome"] == (
        "failed" if failed_indicator == "volume_sma50" else "completed"
    )
    assert result["atr14"]["outcome"] == ("failed" if failed_indicator == "atr14" else "completed")
    assert context.checkpoint_repository.get_checkpoint(41, "volume_sma50").status == (
        "completed_with_errors" if failed_indicator == "volume_sma50" else "completed"
    )
    assert context.checkpoint_repository.get_checkpoint(41, "atr14").status == (
        "completed_with_errors" if failed_indicator == "atr14" else "completed"
    )
    assert finished[-1]["status"] == "completed_with_errors"


def test_orchestrator_validation_block_keeps_atr_skip_evidence(monkeypatch):
    batch, context, events, _ = patch_orchestrator(monkeypatch, blocked=True)
    result = batch.run_daily_job()
    assert "ema" not in events and "atr14" not in events and "rs" not in events
    assert result["atr14"]["outcome"] == "skipped"
    checkpoint = context.checkpoint_repository.get_checkpoint(41, "atr14")
    assert checkpoint.status == "completed_with_errors"
    assert json.loads(checkpoint.step_metadata)["reason"] == "validation_gate_blocked"


def test_orchestrator_skips_atr_when_validation_is_disabled(monkeypatch):
    batch, context, events, _ = patch_orchestrator(monkeypatch)
    effective_settings = settings().model_copy(update={"validation_enabled": False, "ema_enabled": False})
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: effective_settings)
    result = batch.run_daily_job()
    assert "atr14" not in events
    assert result["atr14"]["reason"] == "validation_unavailable"
    assert context.checkpoint_repository.get_checkpoint(41, "atr14").status == "completed_with_errors"
