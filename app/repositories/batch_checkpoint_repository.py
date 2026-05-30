from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_checkpoint import BatchCheckpoint


class BatchCheckpointRepository:
    """배치 체크포인트 레포지토리 - DB 기반"""

    def __init__(self, session: Session):
        self.session = session

    def create_checkpoint(
        self,
        job_id: int,
        step_name: str,
        status: str = "pending",
        items_total: int = 0,
    ) -> BatchCheckpoint:
        """체크포인트 생성"""
        checkpoint = BatchCheckpoint(
            job_id=job_id,
            step_name=step_name,
            status=status,
            items_total=items_total,
        )
        self.session.add(checkpoint)
        self.session.flush()
        return checkpoint

    def get_checkpoint(self, job_id: int, step_name: str) -> BatchCheckpoint | None:
        """특정 단계 체크포인트 조회"""
        stmt = select(BatchCheckpoint).where(
            BatchCheckpoint.job_id == job_id,
            BatchCheckpoint.step_name == step_name,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_checkpoints(self, job_id: int) -> list[BatchCheckpoint]:
        """작업의 모든 체크포인트 조회"""
        stmt = select(BatchCheckpoint).where(BatchCheckpoint.job_id == job_id).order_by(BatchCheckpoint.id)
        return list(self.session.execute(stmt).scalars().all())

    def start_step(self, job_id: int, step_name: str) -> BatchCheckpoint:
        """단계 시작"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            checkpoint = self.create_checkpoint(job_id, step_name)

        checkpoint.status = "running"
        checkpoint.started_at = datetime.utcnow()
        self.session.flush()
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
        self.session.flush()
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
        self.session.flush()
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
        self.session.flush()
        return checkpoint

    def is_step_completed(self, job_id: int, step_name: str) -> bool:
        """단계 완료 여부 확인"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        return checkpoint is not None and checkpoint.status == "completed"
