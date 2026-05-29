"""CrawlFailure 메모리 레포지토리 (테스트용)."""

from datetime import datetime


class MemoryCrawlFailure:
    """메모리 CrawlFailure 모델."""

    def __init__(
        self,
        id: int,
        job_id: int,
        target_type: str,
        target_key: str,
        url: str | None,
        http_status: int | None,
        error_class: str | None,
        error_message: str | None,
        retry_count: int,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.job_id = job_id
        self.target_type = target_type
        self.target_key = target_key
        self.url = url
        self.http_status = http_status
        self.error_class = error_class
        self.error_message = error_message
        self.retry_count = retry_count
        self.created_at = created_at


class MemoryCrawlFailureRepository:
    """크롤링 실패 기록 메모리 레포지토리 (테스트용)."""

    def __init__(self) -> None:
        self._failures: dict[int, MemoryCrawlFailure] = {}
        self._next_id = 1

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
    ) -> MemoryCrawlFailure:
        """실패 기록 생성."""
        failure = MemoryCrawlFailure(
            id=self._next_id,
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
        self._failures[failure.id] = failure
        self._next_id += 1
        return failure

    def list_by_job(self, job_id: int) -> list[MemoryCrawlFailure]:
        """특정 작업의 실패 목록 조회."""
        return [f for f in self._failures.values() if f.job_id == job_id]
