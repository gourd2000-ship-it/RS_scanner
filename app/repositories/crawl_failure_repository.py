"""CrawlFailure 레포지토리."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crawl_failure import CrawlFailure


class CrawlFailureRepository:
    """크롤링 실패 기록 레포지토리."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_failure(
        self,
        job_id: int,
        target_type: str,
        target_key: str,
        url: str | None = None,
        http_status: int | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> CrawlFailure:
        """실패 기록 생성."""
        failure = CrawlFailure(
            job_id=job_id,
            target_type=target_type,
            target_key=target_key,
            url=url,
            http_status=http_status,
            error_class=error_class,
            error_message=error_message,
            retry_count=retry_count,
            created_at=datetime.utcnow(),
        )
        self.session.add(failure)
        self.session.flush()
        return failure

    def list_by_job(self, job_id: int) -> list[CrawlFailure]:
        """특정 작업의 실패 목록 조회."""
        stmt = select(CrawlFailure).where(CrawlFailure.job_id == job_id).order_by(CrawlFailure.created_at)
        return list(self.session.scalars(stmt).all())
