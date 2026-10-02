import json
from contextlib import contextmanager
from types import SimpleNamespace

from app.repositories.memory_batch_checkpoint_repository import MemoryBatchCheckpointRepository
from app.services.batch.orchestrator import BatchOrchestrator


def test_failed_naver_universe_is_not_recorded_as_completed_checkpoint(monkeypatch):
    repository = MemoryBatchCheckpointRepository()
    repository.create_checkpoint(job_id=7, step_name="symbols")
    repository.start_step(job_id=7, step_name="symbols")
    context = SimpleNamespace(checkpoint_repository=repository)

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr("app.services.batch.orchestrator.session_scope", fake_session_scope)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.build_db_batch_context",
        lambda session: context,
    )
    monkeypatch.setattr(
        "app.services.batch.orchestrator.notification_service.send_step_completed_sync",
        lambda **kwargs: None,
    )

    orchestrator = BatchOrchestrator(source=object())
    orchestrator.job_id = 7
    orchestrator.universe_snapshot_status = "failed"
    orchestrator._complete_step_checkpoint("symbols", [])

    checkpoint = repository.get_checkpoint(7, "symbols")
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_failed == 1
    assert json.loads(checkpoint.step_metadata) == {
        "universe_snapshot_status": "failed"
    }
    assert not repository.is_step_completed(7, "symbols")
