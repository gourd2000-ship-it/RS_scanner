"""Preview or apply the one-year retention policy for terminal analysis workflows.

The default is dry-run.  It never deletes requested, accepted, report-ready, or
Codex-reviewed work; `--apply` is required for a database mutation.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta

from app.core.database import SessionLocal
from app.services.analysis.retention import (
    expired_terminal_analysis_request_ids,
    prune_terminal_analysis_requests,
)


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.combine(date.today() - timedelta(days=365), time.min)
    return datetime.combine(date.fromisoformat(value), time.min)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", help="exclusive YYYY-MM-DD cutoff; default is 365 days ago")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="perform deletion after preview")
    args = parser.parse_args()
    cutoff = _cutoff(args.before)
    with SessionLocal() as session:
        request_ids = expired_terminal_analysis_request_ids(
            session,
            before=cutoff,
            limit=args.limit,
        )
        if not args.apply:
            print(
                f"Would prune {len(request_ids)} terminal analysis request(s) before "
                f"{cutoff.date().isoformat()}: {', '.join(map(str, request_ids)) or 'none'}"
            )
            return 0
        deleted = prune_terminal_analysis_requests(session, request_ids=request_ids)
        session.commit()
    print(f"Pruned {deleted} terminal analysis request(s) before {cutoff.date().isoformat()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
