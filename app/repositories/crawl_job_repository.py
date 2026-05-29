"""CrawlJob 레포지토리."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob


class CrawlJobRepository:
    """배치 작업 추적 레포지토리."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(self, job_type: str) -> CrawlJob:
        """새 작업 레코드 생성."""
        job = CrawlJob(
            job_type=job_type,
            started_at=datetime.utcnow(),
            status="running",
            symbols_total=0,
            symbols_succeeded=0,
            symbols_failed=0,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def finish_job(
        self,
        job_id: int,
        status: str,
        symbols_total: int = 0,
        symbols_succeeded: int = 0,
        symbols_failed: int = 0,
        message: str | None = None,
    ) -> CrawlJob:
        """작업 완료/실패 기록."""
        job = self.session.get(CrawlJob, job_id)
        if job is None:
            raise ValueError(f"CrawlJob with id {job_id} not found")

        job.finished_at = datetime.utcnow()
        job.status = status
        job.symbols_total = symbols_total
        job.symbols_succeeded = symbols_succeeded
        job.symbols_failed = symbols_failed
        job.message = message
        self.session.flush()
        return job

    def get_latest(self, job_type: str | None = None) -> CrawlJob | None:
        """최근 작업 조회."""
        stmt = select(CrawlJob).order_by(CrawlJob.started_at.desc()).limit(1)
        if job_type:
            stmt = stmt.where(CrawlJob.job_type == job_type)
        return self.session.scalar(stmt)
