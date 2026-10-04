from types import SimpleNamespace

from app.repositories.memory_batch_checkpoint_repository import MemoryBatchCheckpointRepository
from app.services.batch.ema_adapter import EmaBatchOutcome, record_ema_checkpoint


def test_ema_checkpoint_records_a_skipped_enabled_step_as_completed_with_errors():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=17)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.skipped("validation_gate_blocked"),
    )

    checkpoint = repository.get_checkpoint(17, "ema")
    assert checkpoint is not None
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_failed == 1
    assert checkpoint.step_metadata == (
        '{"outcome": "skipped", "reason": "validation_gate_blocked"}'
    )
    assert not repository.is_step_completed(17, "ema")


def test_ema_checkpoint_records_a_failed_step_without_raising():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=18)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.failure(processed=2, failed=1, reason="RuntimeError"),
    )

    checkpoint = repository.get_checkpoint(18, "ema")
    assert checkpoint is not None
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_processed == 2
    assert checkpoint.items_failed == 1
    assert checkpoint.step_metadata == (
        '{"outcome": "failed", "reason": "RuntimeError"}'
    )


def test_completed_ema_checkpoint_is_resumable_as_a_completed_step():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=19)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.completed(processed=2),
    )

    assert repository.is_step_completed(19, "ema")
