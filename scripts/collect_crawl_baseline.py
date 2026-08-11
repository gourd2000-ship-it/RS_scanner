"""Write the CRAWL-00 baseline report from the configured database."""

import argparse

from app.core.database import session_scope
from app.services.monitoring.crawl_baseline import write_baseline_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="reports/crawl_baseline.json",
        help="JSON report path (default: reports/crawl_baseline.json)",
    )
    parser.add_argument("--log", default=None, help="optional legacy operations log to inspect")
    parser.add_argument("--batches", type=int, default=3, help="number of recent batches")
    args = parser.parse_args()

    with session_scope() as session:
        report = write_baseline_report(
            session,
            args.output,
            batch_limit=args.batches,
            log_path=args.log,
        )
    print(f"wrote baseline report: {args.output} ({len(report.batches)} batches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
