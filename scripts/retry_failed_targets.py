#!/usr/bin/env python3
"""Retry eligible failed/partial targets once, then replay validation."""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.database import session_scope
from app.crawler.sources.naver import NaverPriceSource
from app.services.batch.context import build_db_batch_context
from app.services.batch.sync_prices import retry_failed_price_targets
from app.services.validation.data_quality import validate_crawl_job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--codes", nargs="*", default=None)
    parser.add_argument("--max-requests", type=int)
    args = parser.parse_args()

    settings = get_settings()
    with session_scope() as session:
        context = build_db_batch_context(session)
        context.job_id = args.job_id
        context.price_source = NaverPriceSource()
        result = retry_failed_price_targets(
            context,
            context.price_source,
            args.job_id,
            target_keys=set(args.codes) if args.codes else None,
            max_requests=args.max_requests,
            max_attempts=settings.crawl_retry_max_attempts,
        )
        validation = validate_crawl_job(
            session,
            args.job_id,
            mode=settings.validation_mode,
        )

    print(
        f"Retry job {args.job_id}: targets={result.target_count}, "
        f"fetched={result.fetched_count}, failed={result.failed_count}, "
        f"partial={result.partial_count}"
    )
    print(
        f"Validation: {validation.run.validation_status}, "
        f"fresh coverage={float(validation.run.coverage_rate):.2%}"
    )
    return 2 if settings.validation_mode == "enforce" and validation.would_block else 0


if __name__ == "__main__":
    raise SystemExit(main())
