"""BT12 probe 측정값으로 고정된 역사 적재 실행안을 산정한다."""

from dataclasses import dataclass
from math import ceil

from app.services.historical_backfill import HistoricalBackfillPlan


@dataclass(frozen=True)
class BackfillProbe:
    """운영 가격을 쓰지 않는 제한 probe에서 얻은 측정값이다."""

    expected_rows: int
    request_count: int
    retry_count: int
    fetch_seconds: float
    store_seconds: float
    validation_seconds: float
    rs_seconds: float
    response_bytes: int
    database_bytes: int

    def __post_init__(self) -> None:
        if self.expected_rows < 1 or self.request_count < 1:
            raise ValueError("probe must contain at least one row and request")
        if self.retry_count < 0 or self.response_bytes < 0 or self.database_bytes < 0:
            raise ValueError("probe counts and byte values must not be negative")
        if any(value < 0 for value in (
            self.fetch_seconds, self.store_seconds, self.validation_seconds, self.rs_seconds,
        )):
            raise ValueError("probe durations must not be negative")


@dataclass(frozen=True)
class BackfillEstimate:
    """승인 manifest에 기록할 보수적 선형 추정 결과다."""

    expected_rows: int
    projected_requests: int
    retry_rate: float
    projected_fetch_seconds: float
    projected_store_seconds: float
    projected_validation_seconds: float
    projected_rs_seconds: float
    projected_response_bytes: int
    projected_database_bytes: int
    request_budget: int
    within_request_budget: bool
    minimum_runs: int

    @property
    def projected_total_seconds(self) -> float:
        return (
            self.projected_fetch_seconds + self.projected_store_seconds
            + self.projected_validation_seconds + self.projected_rs_seconds
        )

    def serialized(self) -> dict:
        return {
            "expected_rows": self.expected_rows,
            "projected_requests": self.projected_requests,
            "retry_rate": self.retry_rate,
            "projected_fetch_seconds": self.projected_fetch_seconds,
            "projected_store_seconds": self.projected_store_seconds,
            "projected_validation_seconds": self.projected_validation_seconds,
            "projected_rs_seconds": self.projected_rs_seconds,
            "projected_total_seconds": self.projected_total_seconds,
            "projected_response_bytes": self.projected_response_bytes,
            "projected_database_bytes": self.projected_database_bytes,
            "request_budget": self.request_budget,
            "within_request_budget": self.within_request_budget,
            "minimum_runs": self.minimum_runs,
        }


def estimate_backfill(plan: HistoricalBackfillPlan, probe: BackfillProbe) -> BackfillEstimate:
    """대상 거래일 수 비율로 요청·시간·용량을 외삽한다.

    이 값은 provider 지원 범위나 결측을 성공으로 가정하지 않는다. 따라서 실제
    실행 전 manifest와 함께 ``partial`` 가능성을 계속 공개해야 한다.
    """
    expected_rows = sum(len(target.expected_dates) for target in plan.targets)
    ratio = expected_rows / probe.expected_rows
    projected_requests = ceil(probe.request_count * ratio)
    return BackfillEstimate(
        expected_rows=expected_rows,
        projected_requests=projected_requests,
        retry_rate=probe.retry_count / probe.request_count,
        projected_fetch_seconds=probe.fetch_seconds * ratio,
        projected_store_seconds=probe.store_seconds * ratio,
        projected_validation_seconds=probe.validation_seconds * ratio,
        projected_rs_seconds=probe.rs_seconds * ratio,
        projected_response_bytes=ceil(probe.response_bytes * ratio),
        projected_database_bytes=ceil(probe.database_bytes * ratio),
        request_budget=plan.request_budget,
        within_request_budget=projected_requests <= plan.request_budget,
        minimum_runs=max(1, ceil(projected_requests / plan.request_budget)),
    )
