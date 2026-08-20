#!/usr/bin/env python3
"""Apply completed Sam repair results after autobot validation and conflict checks."""

from __future__ import annotations

import argparse
import logging

from app.core.config import get_settings
from app.core.database import session_scope
from app.services.repair_reconciler import RepairReconciler


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of completed requests to inspect (default: configured batch size)",
    )
    args = parser.parse_args()
    settings = get_settings()
    limit = args.limit or settings.repair_apply_batch_size
    if limit < 1 or limit > 1000:
        parser.error("--limit must be between 1 and 1000")

    with session_scope() as session:
        outcomes = RepairReconciler(
            session,
            max_rows=settings.repair_max_rows,
        ).apply_completed(limit=limit)

    counts = {"applied": 0, "conflict": 0, "rejected": 0}
    for outcome in outcomes:
        counts[outcome.application_status] = counts.get(outcome.application_status, 0) + 1
        logger.info(
            "repair request %s: application_status=%s applied_rows=%s conflicts=%s",
            outcome.request_id,
            outcome.application_status,
            outcome.applied_row_count,
            ",".join(item.isoformat() for item in outcome.conflict_dates) or "none",
        )

    print(
        "Repair apply: "
        f"inspected={len(outcomes)} applied={counts['applied']} "
        f"conflict={counts['conflict']} rejected={counts['rejected']}"
    )
    # Conflict/rejected are deliberate review outcomes, not a process crash.
    # The queue metrics and application status are the operational signal.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
