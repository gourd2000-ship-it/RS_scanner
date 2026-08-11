#!/usr/bin/env python3
"""Replay a persisted crawl job through the deterministic data-quality validator."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from app.core.config import get_settings
from app.core.database import session_scope
from app.services.validation.data_quality import validate_crawl_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--trade-date", type=date.fromisoformat)
    parser.add_argument("--mode", choices=("report_only", "enforce"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help="return exit code 2 when the validation result would block",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with session_scope() as session:
        result = validate_crawl_job(
            session,
            args.job_id,
            target_date=args.trade_date,
            mode=args.mode,
        )
        document = result.to_dict()
        output = args.output
        if output is None:
            output = Path(get_settings().validation_report_dir) / f"job_{args.job_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(output)

    print(f"Validation Job {args.job_id}")
    print(f"Trade date: {document['trade_date']}")
    print(
        "Fresh coverage: "
        f"{document['fresh_symbols']} / {document['expected_symbols']} "
        f"({document['coverage_rate']:.2%})"
    )
    print(
        "RS inputs: "
        f"fresh coverage {document['rs_fresh_input_coverage_rate']:.2%}, "
        f"candidates {document['rs_candidate_symbols']}"
    )
    counts = document["counts"]
    print(
        "Cases: "
        f"warning={counts['warning']}, error={counts['error']}, "
        f"critical={counts['critical']}"
    )
    print(f"Validation status: {document['validation_status']} ({document['mode']})")
    print(f"Report: {output}")

    if args.fail_on_block and result.would_block:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
