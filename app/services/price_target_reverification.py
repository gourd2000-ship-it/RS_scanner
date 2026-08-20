"""가격 배치 target과 종목별 결과의 정합성을 읽기 전용으로 검증한다."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class PriceTargetResultVerification:
    job_id: int
    job_status: str
    recorded_target_count: int
    result_step: str | None
    result_count: int
    status_counts: dict[str, int]
    target_count_matches_results: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["verifiable"] = self.result_step is not None
        return payload


def build_price_target_result_verification(
    *,
    job_id: int,
    job_status: str,
    recorded_target_count: int,
    price_results: Iterable[object],
    eod_results: Iterable[object],
) -> PriceTargetResultVerification:
    """`prices` 우선, 없을 때 `eod` 결과로 target 수를 비교한다.

    EOD canary는 동일 job에 `eod`와 fallback `prices` 결과를 모두 남길 수 있으므로,
    기존 운영 metric과 같은 우선순위를 사용해 두 집합을 중복 합산하지 않는다.
    """
    price_items = tuple(price_results)
    eod_items = tuple(eod_results)
    if price_items:
        result_step = "prices"
        items = price_items
    elif eod_items:
        result_step = "eod"
        items = eod_items
    else:
        result_step = None
        items = ()

    status_counts = dict(
        sorted(Counter(str(getattr(item, "status", "unknown")) for item in items).items())
    )
    return PriceTargetResultVerification(
        job_id=job_id,
        job_status=job_status,
        recorded_target_count=recorded_target_count,
        result_step=result_step,
        result_count=len(items),
        status_counts=status_counts,
        target_count_matches_results=(
            result_step is not None and recorded_target_count == len(items)
        ),
    )
