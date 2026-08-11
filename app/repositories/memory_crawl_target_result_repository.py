"""종목별 크롤링 결과 메모리 레포지토리 (테스트용)."""

from collections.abc import Iterable
from datetime import date, datetime


class MemoryCrawlTargetResult:
    def __init__(
        self,
        *,
        id: int,
        job_id: int,
        step_name: str,
        target_type: str,
        target_key: str,
        status: str,
        provider: str | None,
        attempt_count: int,
        rows_received: int,
        rows_persisted: int,
        latest_date_before: date | None,
        latest_date_after: date | None,
        trade_date: date | None,
        url: str | None,
        http_status: int | None,
        response_bytes: int | None,
        error_class: str | None,
        error_message: str | None,
        retry_count: int,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.job_id = job_id
        self.step_name = step_name
        self.target_type = target_type
        self.target_key = target_key
        self.status = status
        self.provider = provider
        self.attempt_count = attempt_count
        self.rows_received = rows_received
        self.rows_persisted = rows_persisted
        self.latest_date_before = latest_date_before
        self.latest_date_after = latest_date_after
        self.trade_date = trade_date
        self.url = url
        self.http_status = http_status
        self.response_bytes = response_bytes
        self.error_class = error_class
        self.error_message = error_message
        self.retry_count = retry_count
        self.created_at = created_at
        self.updated_at = updated_at


class MemoryCrawlTargetResultRepository:
    def __init__(self) -> None:
        self._results: dict[tuple[int, str, str], MemoryCrawlTargetResult] = {}
        self._next_id = 1

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
    ) -> MemoryCrawlTargetResult:
        key = (job_id, step_name, target_key)
        now = datetime.utcnow()
        result = self._results.get(key)
        if result is None:
            result = MemoryCrawlTargetResult(
                id=self._next_id,
                job_id=job_id,
                step_name=step_name,
                target_type=target_type,
                target_key=target_key,
                status=status,
                provider=provider,
                attempt_count=0,
                rows_received=0,
                rows_persisted=0,
                latest_date_before=None,
                latest_date_after=None,
                trade_date=None,
                url=None,
                http_status=None,
                response_bytes=None,
                error_class=None,
                error_message=None,
                retry_count=0,
                created_at=now,
                updated_at=now,
            )
            self._results[key] = result
            self._next_id += 1

        result.target_type = target_type
        result.status = status
        result.provider = provider
        result.attempt_count += 1
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
        result.updated_at = now
        return result

    def get_by_target(
        self,
        job_id: int,
        step_name: str,
        target_key: str,
    ) -> MemoryCrawlTargetResult | None:
        return self._results.get((job_id, step_name, target_key))

    def list_by_job(
        self,
        job_id: int,
        step_name: str | None = None,
        statuses: Iterable[str] | None = None,
    ) -> list[MemoryCrawlTargetResult]:
        allowed = set(statuses) if statuses else None
        results = [result for result in self._results.values() if result.job_id == job_id]
        if step_name:
            results = [result for result in results if result.step_name == step_name]
        if allowed:
            results = [result for result in results if result.status in allowed]
        return sorted(results, key=lambda result: result.target_key)
