"""종목별 크롤링 결과 레포지토리."""

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crawl_target_result import CrawlTargetResult


class CrawlTargetResultRepository:
    """배치 재시작과 운영 조회에 필요한 종목별 최종 결과 저장소."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_result(
        self,
        job_id: int,
        step_name: str,
        target_key: str,
        status: str,
        *,
        target_type: str = "stock",
        provider: str | None = None,
        rows_received: int = 0,
        rows_persisted: int = 0,
        latest_date_before: date | None = None,
        latest_date_after: date | None = None,
        trade_date: date | None = None,
        url: str | None = None,
        http_status: int | None = None,
        response_bytes: int | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> CrawlTargetResult:
        """한 번의 시도를 누적하고 해당 target의 최종 상태를 갱신한다."""
        result = self.get_by_target(job_id, step_name, target_key)
        if result is None:
            result = CrawlTargetResult(
                job_id=job_id,
                step_name=step_name,
                target_type=target_type,
                target_key=target_key,
                attempt_count=0,
            )
            self.session.add(result)

        result.target_type = target_type
        result.status = status
        result.provider = provider
        result.attempt_count = (result.attempt_count or 0) + 1
        result.rows_received = rows_received
        result.rows_persisted = rows_persisted
        result.latest_date_before = latest_date_before
        result.latest_date_after = latest_date_after
        result.trade_date = trade_date
        result.url = url
        result.http_status = http_status
        result.response_bytes = response_bytes
        result.error_class = error_class
        result.error_message = error_message
        result.retry_count = retry_count
        result.updated_at = datetime.utcnow()
        self.session.flush()
        return result

    def get_by_target(
        self,
        job_id: int,
        step_name: str,
        target_key: str,
    ) -> CrawlTargetResult | None:
        stmt = select(CrawlTargetResult).where(
            CrawlTargetResult.job_id == job_id,
            CrawlTargetResult.step_name == step_name,
            CrawlTargetResult.target_key == target_key,
        )
        return self.session.scalar(stmt)

    def list_by_job(
        self,
        job_id: int,
        step_name: str | None = None,
        statuses: Iterable[str] | None = None,
    ) -> list[CrawlTargetResult]:
        stmt = select(CrawlTargetResult).where(CrawlTargetResult.job_id == job_id)
        if step_name:
            stmt = stmt.where(CrawlTargetResult.step_name == step_name)
        if statuses:
            stmt = stmt.where(CrawlTargetResult.status.in_(list(statuses)))
        stmt = stmt.order_by(CrawlTargetResult.target_key)
        return list(self.session.scalars(stmt).all())
