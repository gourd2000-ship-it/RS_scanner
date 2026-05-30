from datetime import datetime

from app.models.batch_checkpoint import BatchCheckpoint


class MemoryBatchCheckpointRepository:
    """배치 체크포인트 레포지토리 - 메모리 기반 (테스트용)"""

    def __init__(self):
        self._checkpoints: dict[tuple[int, str], BatchCheckpoint] = {}
        self._next_id = 1

    def create_checkpoint(
        self,
        job_id: int,
        step_name: str,
        status: str = "pending",
        items_total: int = 0,
    ) -> BatchCheckpoint:
        """체크포인트 생성"""
        checkpoint = BatchCheckpoint(
            id=self._next_id,
            job_id=job_id,
            step_name=step_name,
            status=status,
            items_total=items_total,
        )
        self._next_id += 1
        self._checkpoints[(job_id, step_name)] = checkpoint
        return checkpoint

    def get_checkpoint(self, job_id: int, step_name: str) -> BatchCheckpoint | None:
        """특정 단계 체크포인트 조회"""
        return self._checkpoints.get((job_id, step_name))

    def list_checkpoints(self, job_id: int) -> list[BatchCheckpoint]:
        """작업의 모든 체크포인트 조회"""
        return [cp for (jid, _), cp in self._checkpoints.items() if jid == job_id]

    def start_step(self, job_id: int, step_name: str) -> BatchCheckpoint:
        """단계 시작"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            checkpoint = self.create_checkpoint(job_id, step_name)

        checkpoint.status = "running"
        checkpoint.started_at = datetime.utcnow()
        return checkpoint

    def complete_step(
        self,
        job_id: int,
        step_name: str,
        items_processed: int = 0,
        items_failed: int = 0,
        step_metadata: str | None = None,
    ) -> BatchCheckpoint:
        """단계 완료"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: job_id={job_id}, step_name={step_name}")

        checkpoint.status = "completed"
        checkpoint.completed_at = datetime.utcnow()
        checkpoint.items_processed = items_processed
        checkpoint.items_failed = items_failed
        if step_metadata:
            checkpoint.step_metadata = step_metadata
        return checkpoint

    def fail_step(
        self,
        job_id: int,
        step_name: str,
        error_message: str,
        items_processed: int = 0,
        items_failed: int = 0,
    ) -> BatchCheckpoint:
        """단계 실패"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: job_id={job_id}, step_name={step_name}")

        checkpoint.status = "failed"
        checkpoint.completed_at = datetime.utcnow()
        checkpoint.error_message = error_message
        checkpoint.items_processed = items_processed
        checkpoint.items_failed = items_failed
        return checkpoint

    def update_progress(
        self,
        job_id: int,
        step_name: str,
        items_processed: int,
        items_total: int | None = None,
    ) -> BatchCheckpoint:
        """진행률 업데이트"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: job_id={job_id}, step_name={step_name}")

        checkpoint.items_processed = items_processed
        if items_total is not None:
            checkpoint.items_total = items_total
        return checkpoint

    def is_step_completed(self, job_id: int, step_name: str) -> bool:
        """단계 완료 여부 확인"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        return checkpoint is not None and checkpoint.status == "completed"
