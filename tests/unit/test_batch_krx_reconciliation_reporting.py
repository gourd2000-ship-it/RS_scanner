from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.batch.orchestrator import BatchOrchestrator


def test_orchestrator_writes_a_read_only_krx_reconciliation_report_after_batch(monkeypatch, tmp_path):
    @contextmanager
    def fake_session_scope():
        yield object()

    report = SimpleNamespace(mapping_rate=1.0, alerts=[])
    written: dict[str, object] = {}

    monkeypatch.setattr("app.services.batch.orchestrator.session_scope", fake_session_scope)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.build_universe_reconciliation_report",
        lambda session: report,
    )

    def fake_write(report_arg, *, output_dir, report_stem, generated_at):
        written.update(
            report=report_arg,
            output_dir=output_dir,
            report_stem=report_stem,
            generated_at=generated_at,
        )
        return tmp_path / "krx_universe_reconciliation_20260820_120000.json"

    monkeypatch.setattr(
        "app.services.batch.orchestrator.write_reconciliation_report", fake_write
    )
    orchestrator = BatchOrchestrator(source=object())
    orchestrator.job_id = 69

    result = orchestrator._write_krx_reconciliation_report()

    assert result == Path(tmp_path / "krx_universe_reconciliation_20260820_120000.json")
    assert written["report"] is report
    assert written["output_dir"] == Path("reports/krx_universe")
    assert str(written["report_stem"]).startswith("krx_universe_reconciliation_")


@dataclass(frozen=True)
class OpenMarket:
    is_open: bool = True
    reason: str = "KRX trading day"


def test_orchestrator_writes_krx_report_when_a_shadow_enabled_batch_fails(monkeypatch):
    orchestrator = BatchOrchestrator(source=object())
    report_calls: list[bool] = []

    monkeypatch.setattr(
        "app.services.batch.orchestrator.get_settings",
        lambda: SimpleNamespace(
            krx_shadow_ingestion_enabled=True,
            market_closed_dates="",
        ),
    )
    monkeypatch.setattr("app.services.batch.orchestrator.batch_target_date", lambda _: object())
    monkeypatch.setattr("app.services.batch.orchestrator.krx_market_day_status", lambda *_args, **_kwargs: OpenMarket())
    monkeypatch.setattr(orchestrator, "_create_job", lambda: setattr(orchestrator, "job_id", 70))
    monkeypatch.setattr(orchestrator, "_finish_job", lambda **_kwargs: None)
    monkeypatch.setattr(
        orchestrator,
        "_run_step",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("simulated failure")),
    )
    monkeypatch.setattr(
        orchestrator,
        "_write_krx_reconciliation_report",
        lambda: report_calls.append(True) or Path("reports/krx_universe/failure.json"),
    )
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_batch_failure_sync",
        lambda **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="simulated failure"):
        orchestrator.run_daily_job()

    assert report_calls == [True]
