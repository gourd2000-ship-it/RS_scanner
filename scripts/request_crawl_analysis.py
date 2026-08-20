"""Create an explicit weekly/ad-hoc crawl analysis request through the local API."""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--kind", choices=("weekly", "ad_hoc"), default="weekly")
    parser.add_argument("--job-id", type=int, action="append", default=[])
    parser.add_argument("--error-type", action="append", default=[])
    parser.add_argument("--market", action="append", default=[])
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--requested-by", default="operator")
    parser.add_argument("--api-base-url", default=os.getenv("ANALYSIS_API_BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    token = os.getenv("ANALYSIS_OPERATOR_TOKEN")
    if not token:
        parser.error("ANALYSIS_OPERATOR_TOKEN must be set")
    payload = {
        "request_id": args.request_id,
        "idempotency_key": args.idempotency_key,
        "requested_by": args.requested_by,
        "request_kind": args.kind,
        "completed_job_ids": args.job_id,
        "error_types": args.error_type,
        "markets": args.market,
        "sample_limit": args.sample_limit,
        "reason": args.reason,
    }
    response = httpx.post(
        f"{args.api_base_url.rstrip('/')}/internal/v1/crawl-analysis/requests",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15.0,
    )
    if response.is_error:
        print(response.text, file=sys.stderr)
        return 1
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
