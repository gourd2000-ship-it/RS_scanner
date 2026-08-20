"""Write a read-only KRX/Naver universe reconciliation report.

Example:
    .venv/bin/python scripts/report_universe_reconciliation.py \
      --output-dir reports/krx_universe
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.services.monitoring.reconciliation_report import write_reconciliation_report
from app.services.monitoring.universe_reconciliation import (
    UniverseReconciliationReport,
    build_universe_reconciliation_report,
)


def build_report_from_database(*, sample_limit: int) -> UniverseReconciliationReport:
    with SessionLocal() as session:
        return build_universe_reconciliation_report(session, sample_limit=sample_limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX/Naver shadow reconciliation report")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/krx_universe"),
        help="JSON report directory",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="maximum samples per mismatch reason",
    )
    args = parser.parse_args()
    if args.sample_limit < 1:
        parser.error("--sample-limit must be positive")

    report = build_report_from_database(sample_limit=args.sample_limit)
    generated_at = datetime.now(UTC)
    output = write_reconciliation_report(
        report,
        output_dir=args.output_dir,
        report_stem=f"krx_universe_reconciliation_{generated_at.strftime('%Y%m%d_%H%M%S')}",
        generated_at=generated_at,
    )
    print(
        "KRX/Naver reconciliation report written: "
        f"{output} (mapping_rate={report.mapping_rate:.4f}, alerts={','.join(report.alerts) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
