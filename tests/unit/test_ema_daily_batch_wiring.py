from datetime import date
from types import SimpleNamespace

from app.core.config import Settings
from app.models.data_quality import ValidationRun
from app.services.batch.context import build_memory_batch_context
from app.services.batch.ema_adapter import EmaBatchOutcome
from app.services.batch.orchestrator import BatchOrchestrator
from app.services.batch.run_daily_job import run_daily_job
from app.services.batch.sync_prices import PriceSyncResult
from app.services.validation.data_quality import ValidationResult


def _settings(*, validation_enabled: bool = False, validation_mode: str = "report_only") -> Settings:
    return Settings(
        ema_enabled=True,
        validation_enabled=validation_enabled,
        validation_mode=validation_mode,
    )


def _patch_direct_batch(monkeypatch, settings: Settings, events: list[str]) -> None:
    monkeypatch.setattr("app.services.batch.run_daily_job.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_symbols", lambda *_: [])
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_benchmarks", lambda *_: {})
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_prices", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.batch.run_daily_job.ema_enabled", lambda _: True)
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.notification_service.send_batch_success_sync",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.notification_service.send_batch_failure_sync",
        lambda **_: None,
    )


def test_direct_daily_batch_runs_ema_after_rs_and_reuses_the_current_job(monkeypatch):
    events: list[str] = []
    _patch_direct_batch(monkeypatch, _settings(), events)
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_rs",
        lambda *_args, **_kwargs: events.append("rs") or {"KOSPI": [object()]},
    )
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_daily_ema",
        lambda *_args, **_kwargs: events.append("ema") or EmaBatchOutcome.completed(processed=2),
    )
    context = build_memory_batch_context()
    context.target_date = date(2025, 9, 17)
    existing = context.crawl_job_repository.create_job("daily_full")
    context.job_id = existing.id

    result = run_daily_job(context, source=object())

    assert events == ["rs", "ema"]
    assert result["job_id"] == existing.id
    assert result["ema"] == {
        "outcome": "completed", "processed": 2, "failed": 0, "reason": None,
    }
    assert len(context.crawl_job_repository._jobs) == 1
    assert context.checkpoint_repository.is_step_completed(existing.id, "ema")

    resumed = run_daily_job(context, source=object())

    assert events == ["rs", "ema", "rs"]
    assert resumed["ema"]["outcome"] == "completed"


def test_direct_daily_batch_keeps_rs_when_ema_fails(monkeypatch):
    events: list[str] = []
    _patch_direct_batch(monkeypatch, _settings(), events)
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_rs",
        lambda *_args, **_kwargs: events.append("rs") or {"KOSPI": [object()]},
    )
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_daily_ema",
        lambda *_args, **_kwargs: EmaBatchOutcome.failure(
            processed=1, failed=1, reason="RuntimeError"
        ),
    )
    context = build_memory_batch_context()
    context.target_date = date(2025, 9, 17)

    result = run_daily_job(context, source=object())

    assert events == ["rs"]
    assert result["rs_results"] == {"KOSPI": 1}
    assert result["ema"]["outcome"] == "failed"
    assert context.crawl_job_repository.get_latest().status == "completed_with_errors"
    assert context.checkpoint_repository.get_checkpoint(result["job_id"], "ema").status == "completed_with_errors"


def test_direct_daily_batch_records_ema_skip_when_validation_blocks(monkeypatch):
    events: list[str] = []
    _patch_direct_batch(monkeypatch, _settings(validation_enabled=True, validation_mode="enforce"), events)
    validation = SimpleNamespace(
        run=SimpleNamespace(id=3, validation_status="blocked", trade_date=date(2025, 9, 17)),
        would_block=True,
        to_dict=lambda: {"validation_status": "blocked"},
    )
    monkeypatch.setattr("app.services.batch.run_daily_job.validate_crawl_job", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr("app.services.batch.run_daily_job.write_validation_report", lambda _: "report.json")
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_rs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("RS must be blocked")),
    )
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.calculate_daily_ema",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("EMA must be skipped")),
    )
    context = build_memory_batch_context()
    context.session = object()
    context.target_date = date(2025, 9, 17)

    result = run_daily_job(context, source=object())

    checkpoint = context.checkpoint_repository.get_checkpoint(result["job_id"], "ema")
    assert result["rs_results"] == {}
    assert result["ema"]["outcome"] == "skipped"
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.step_metadata == '{"outcome": "skipped", "reason": "validation_gate_blocked"}'


def test_checkpoint_orchestrator_runs_the_same_ema_adapter_after_rs(monkeypatch):
    settings = _settings()
    events: list[str] = []
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.batch.orchestrator.batch_target_date", lambda _: date(2025, 9, 17))
    monkeypatch.setattr("app.services.batch.orchestrator.ema_enabled", lambda _: True)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_batch_success_sync",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_batch_failure_sync",
        lambda **_: None,
    )
    batch = BatchOrchestrator(source=object())
    monkeypatch.setattr(batch, "_create_job", lambda: setattr(batch, "job_id", 41))
    monkeypatch.setattr(batch, "_finish_job", lambda **_: None)

    def run_step(*, step_name, **_kwargs):
        if step_name == "rs":
            events.append("rs")
            return {"KOSPI": [object()]}
        if step_name == "ema":
            events.append("ema")
            return EmaBatchOutcome.completed(processed=2)
        if step_name == "prices":
            return PriceSyncResult()
        return [] if step_name == "symbols" else {}

    monkeypatch.setattr(batch, "_run_step", run_step)

    result = batch.run_daily_job()

    assert events == ["rs", "ema"]
    assert result["ema"]["outcome"] == "completed"


def test_checkpoint_orchestrator_skips_ema_when_clean_validation_blocks(monkeypatch):
    settings = _settings(validation_enabled=True, validation_mode="enforce")
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.batch.orchestrator.batch_target_date", lambda _: date(2025, 9, 17))
    monkeypatch.setattr("app.services.batch.orchestrator.ema_enabled", lambda _: True)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_batch_success_sync",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_batch_failure_sync",
        lambda **_: None,
    )
    batch = BatchOrchestrator(source=object())
    monkeypatch.setattr(batch, "_create_job", lambda: setattr(batch, "job_id", 42))
    monkeypatch.setattr(batch, "_finish_job", lambda **_: None)
    blocked_steps: list[str] = []
    ema_outcomes: list[EmaBatchOutcome] = []
    monkeypatch.setattr(batch, "_block_step_checkpoint", lambda step, _: blocked_steps.append(step))
    monkeypatch.setattr(batch, "_record_ema_outcome", lambda outcome: ema_outcomes.append(outcome))
    validation = ValidationResult(
        run=ValidationRun(validator_version="test", mode="enforce", validation_status="blocked"),
        cases=[],
        metrics={},
    )

    def run_step(*, step_name, **_kwargs):
        if step_name == "validation":
            return validation
        if step_name == "rs" or step_name == "ema":
            raise AssertionError(f"{step_name} must not execute")
        if step_name == "prices":
            return PriceSyncResult()
        return [] if step_name == "symbols" else {}

    monkeypatch.setattr(batch, "_run_step", run_step)

    result = batch.run_daily_job()

    assert blocked_steps == ["rs"]
    assert ema_outcomes == [EmaBatchOutcome.skipped("validation_gate_blocked")]
    assert result["ema"]["outcome"] == "skipped"


def test_orchestrator_does_not_create_a_second_crawl_job_for_resume(monkeypatch):
    batch = BatchOrchestrator(source=object())
    batch.job_id = 99
    monkeypatch.setattr(
        "app.services.batch.orchestrator.session_scope",
        lambda: (_ for _ in ()).throw(AssertionError("must not open a new job transaction")),
    )

    batch._create_job()
