"""완료된 가격 배치의 target 수와 종목 결과 수를 읽기 전용으로 대조한다."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.services.price_target_reverification import (
    PriceTargetResultVerification,
    build_price_target_result_verification,
)


def build_verification_from_database(*, job_id: int | None) -> PriceTargetResultVerification:
    with SessionLocal() as session:
        if job_id is None:
            job = session.scalar(
                select(CrawlJob)
                .where(
                    CrawlJob.job_type == "daily_full",
                    CrawlJob.finished_at.is_not(None),
                    CrawlJob.status.in_(("completed", "completed_with_errors")),
                )
                .order_by(CrawlJob.finished_at.desc(), CrawlJob.id.desc())
                .limit(1)
            )
        else:
            job = session.get(CrawlJob, job_id)
        if job is None:
            raise ValueError("완료된 daily_full crawl job을 찾을 수 없습니다")

        def results_for(step_name: str) -> list[CrawlTargetResult]:
            return list(
                session.scalars(
                    select(CrawlTargetResult)
                    .where(
                        CrawlTargetResult.job_id == job.id,
                        CrawlTargetResult.step_name == step_name,
                    )
                    .order_by(CrawlTargetResult.target_key)
                )
            )

        return build_price_target_result_verification(
            job_id=job.id,
            job_status=job.status,
            recorded_target_count=job.symbols_total,
            price_results=results_for("prices"),
            eod_results=results_for("eod"),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="가격 배치 target/result 정합성 검증")
    parser.add_argument("--job-id", type=int, help="기본값은 최신 완료 daily_full job")
    args = parser.parse_args()
    try:
        report = build_verification_from_database(job_id=args.job_id)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.target_count_matches_results else 1


if __name__ == "__main__":
    raise SystemExit(main())
