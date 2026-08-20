"""Create missing immutable quality reports for completed daily crawl jobs.

This command is an autobot-only recovery tool for `quality_report_write_error`.
It never alters an existing report and never creates analysis requests or calls
Sam/Kiwoom.
"""

from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.services.monitoring.crawl_quality_report import (
    ensure_crawl_quality_report,
    missing_daily_quality_report_job_ids,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-id", type=int, action="append", default=[])
    target.add_argument(
        "--all-missing",
        action="store_true",
        help="consider completed daily jobs with no quality report",
    )
    target.add_argument(
        "--latest-missing",
        action="store_true",
        help="consider newest completed daily jobs with no quality report first",
    )
    parser.add_argument("--limit", type=int, default=100, help="maximum jobs for --all-missing or --latest-missing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        job_ids = missing_daily_quality_report_job_ids(
            session,
            crawl_job_ids=args.job_id or None,
            limit=args.limit,
            newest_first=args.latest_missing,
        )

    if not job_ids:
        print("No missing completed daily crawl quality reports.")
        return 0
    if args.dry_run:
        print("Would create reports for crawl job IDs: " + ", ".join(map(str, job_ids)))
        return 0

    for job_id in job_ids:
        with SessionLocal.begin() as session:
            report = ensure_crawl_quality_report(session, crawl_job_id=job_id)
        print(f"Created quality report {report.id} for crawl job {job_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
