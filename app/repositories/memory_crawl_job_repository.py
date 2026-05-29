"""CrawlJob 메모리 레포지토리 (테스트용)."""

from datetime import datetime


class MemoryCrawlJob:
    """메모리 CrawlJob 모델."""

    def __init__(
        self,
        id: int,
        job_type: str,
        started_at: datetime,
        status: str,
        symbols_total: int,
        symbols_succeeded: int,
        symbols_failed: int,
    ) -> None:
        self.id = id
        self.job_type = job_type
        self.started_at = started_at
        self.finished_at: datetime | None = None
        self.status = status
        self.symbols_total = symbols_total
        self.symbols_succeeded = symbols_succeeded
        self.symbols_failed = symbols_failed
        self.message: str | None = None


class MemoryCrawlJobRepository:
    """배치 작업 추적 메모리 레포지토리 (테스트용)."""

    def __init__(self) -> None:
        self._jobs: dict[int, MemoryCrawlJob] = {}
        self._next_id = 1

    def create_job(self, job_type: str) -> MemoryCrawlJob:
        """새 작업 레코드 생성."""
        job = MemoryCrawlJob(
            id=self._next_id,
            job_type=job_type,
            started_at=datetime.utcnow(),
            status="running",
            symbols_total=0,
            symbols_succeeded=0,
            symbols_failed=0,
        )
        self._jobs[job.id] = job
        self._next_id += 1
        return job

    def finish_job(
        self,
        job_id: int,
        status: str,
        symbols_total: int = 0,
        symbols_succeeded: int = 0,
        symbols_failed: int = 0,
        message: str | None = None,
    ) -> MemoryCrawlJob:
        """작업 완료/실패 기록."""
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"CrawlJob with id {job_id} not found")

        job.finished_at = datetime.utcnow()
        job.status = status
        job.symbols_total = symbols_total
        job.symbols_succeeded = symbols_succeeded
        job.symbols_failed = symbols_failed
        job.message = message
        return job

    def get_latest(self, job_type: str | None = None) -> MemoryCrawlJob | None:
        """최근 작업 조회."""
        jobs = [job for job in self._jobs.values() if job_type is None or job.job_type == job_type]
        if not jobs:
            return None
        return max(jobs, key=lambda j: j.started_at)
