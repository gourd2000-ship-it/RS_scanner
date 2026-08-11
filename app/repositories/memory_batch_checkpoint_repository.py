import json
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
