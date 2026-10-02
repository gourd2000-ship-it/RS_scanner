#!/usr/bin/env python3
"""Replay every materialized backtest API page and write a deterministic report."""

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.endpoints.backtest import _materialized_dataset_page
from app.core.database import session_scope


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--start", required=True, type=_date)
    parser.add_argument("--end", required=True, type=_date)
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.page_size < 1 or args.page_size > 5000:
        parser.error("--page-size must be between 1 and 5000")

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    cursor = None
    digest = sha256()
    pages = items = partial_items = price_rows = available_rs_rows = 0
    reasons: dict[str, int] = {}
    manifest_hash = None
    with session_scope() as session:
        while True:
            response = Response()
            page = _materialized_dataset_page(
                request=request, response=response, session=session,
                dataset_id=args.dataset_id, start=args.start, end=args.end,
                markets=("KOSPI", "KOSDAQ"), cursor=cursor,
                page_size=args.page_size, strict=False,
            )
            if manifest_hash is None:
                manifest_hash = page.manifest_hash
            elif manifest_hash != page.manifest_hash:
                raise RuntimeError("manifest changed during replay")
            payload = page.model_dump(mode="json")
            digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode())
            pages += 1
            items += len(page.items)
            for item in page.items:
                partial_items += item.quality == "partial"
                price_rows += item.price is not None
                available_rs_rows += item.rs is not None
                reason = item.price_reason or item.rs_reason
                if reason:
                    reasons[reason] = reasons.get(reason, 0) + 1
            cursor = page.next_cursor
            if cursor is None:
                break
    report = {
        "dataset_id": args.dataset_id,
        "manifest_hash": manifest_hash,
        "range": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "page_size": args.page_size,
        "pages": pages,
        "items": items,
        "partial_items": partial_items,
        "price_rows": price_rows,
        "available_rs_rows": available_rs_rows,
        "reason_counts": reasons,
        "replay_hash": digest.hexdigest(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
