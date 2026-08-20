"""Read an explicit crawl-analysis request and its submitted Sam report."""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("ANALYSIS_API_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print only the report Markdown when status is report_ready or later",
    )
    args = parser.parse_args()
    token = os.getenv("ANALYSIS_OPERATOR_TOKEN")
    if not token:
        parser.error("ANALYSIS_OPERATOR_TOKEN must be set")
    response = httpx.get(
        f"{args.api_base_url.rstrip('/')}/internal/v1/crawl-analysis/requests/{args.request_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    if response.is_error:
        print(response.text, file=sys.stderr)
        return 1
    payload = response.json()
    if args.report_only:
        report = payload.get("report")
        if report is None:
            print(f"No submitted report; request status is {payload['status']}.", file=sys.stderr)
            return 2
        print(report["markdown_body"])
        return 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
