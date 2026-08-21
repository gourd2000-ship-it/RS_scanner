import json
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
        status: str = "completed",
        items_processed: int = 0,
        items_failed: int = 0,
        step_metadata: str | None = None,
    ) -> BatchCheckpoint:
        """단계 완료"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: job_id={job_id}, step_name={step_name}")

        checkpoint.status = status
        checkpoint.completed_at = datetime.utcnow()
        checkpoint.items_processed = items_processed
        checkpoint.items_failed = items_failed
        if step_metadata:
            checkpoint.step_metadata = _merge_step_metadata(
                checkpoint.step_metadata,
                step_metadata,
            )
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

    def update_chunk_progress(
        self,
        job_id: int,
        step_name: str,
        chunk_index: int,
        total_chunks: int,
        chunk_size: int,
        items_processed_this_chunk: int,
        items_failed_this_chunk: int = 0,
        chunk_succeeded: bool = True,
    ) -> BatchCheckpoint:
        """청크 완료 시 메타데이터 업데이트"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: job_id={job_id}, step_name={step_name}")

        # 기존 메타데이터 파싱
        if checkpoint.step_metadata:
            try:
                metadata = json.loads(checkpoint.step_metadata)
            except json.JSONDecodeError:
                metadata = {}
        else:
            metadata = {}

        # 청크 진행 정보 업데이트
        if "chunks_completed" not in metadata:
            metadata["chunks_completed"] = []
        if "chunk_size" not in metadata:
            metadata["chunk_size"] = chunk_size
        if "total_chunks" not in metadata:
            metadata["total_chunks"] = total_chunks
        if "chunks_failed" not in metadata:
            metadata["chunks_failed"] = []

        # 실패가 없는 청크만 재시작 시 완료 청크로 간주한다.
        if chunk_succeeded:
            if chunk_index not in metadata["chunks_completed"]:
                metadata["chunks_completed"].append(chunk_index)
            metadata["chunks_failed"] = [
                index for index in metadata["chunks_failed"] if index != chunk_index
            ]
        elif chunk_index not in metadata["chunks_failed"]:
            metadata["chunks_failed"].append(chunk_index)
        metadata["last_attempted_chunk"] = chunk_index

        # JSON 직렬화
        checkpoint.step_metadata = json.dumps(metadata)

        # 전체 진행률 업데이트
        checkpoint.items_processed = checkpoint.items_processed + items_processed_this_chunk
        checkpoint.items_failed = checkpoint.items_failed + items_failed_this_chunk

        self.session.flush()
        return checkpoint

    def get_completed_chunks(self, job_id: int, step_name: str) -> set[int]:
        """완료된 청크 인덱스 목록 반환"""
        checkpoint = self.get_checkpoint(job_id, step_name)
        if not checkpoint or not checkpoint.step_metadata:
            return set()

        try:
            metadata = json.loads(checkpoint.step_metadata)
            return set(metadata.get("chunks_completed", []))
        except json.JSONDecodeError:
            return set()


def _merge_step_metadata(
    existing: str | None,
    incoming: str,
) -> str:
    """Merge JSON metadata so completed steps retain restart evidence."""
    try:
        existing_data = json.loads(existing) if existing else {}
        incoming_data = json.loads(incoming)
    except json.JSONDecodeError:
        return incoming
    if not isinstance(existing_data, dict) or not isinstance(incoming_data, dict):
        return incoming
    existing_data.update(incoming_data)
    return json.dumps(existing_data, sort_keys=True)
