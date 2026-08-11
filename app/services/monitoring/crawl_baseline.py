"""Build a reproducible baseline report for the crawling roadmap.

The report is deliberately derived from persisted jobs, target results and
symbols rather than process logs.  An optional log file can supplement the
report for legacy claims such as "2,400 symbols in two hours", but it is never
treated as proof when the log does not contain an unambiguous observation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import re
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol


@dataclass(frozen=True)
class BaselineBatch:
    job_id: int
    status: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    eligible: int
    fetched: int
    no_new_data: int
    partial: int
    failed: int
    skipped: int
    coverage_rate: float
    request_count: int | None
    retry_count: int | None
    failure_count: int
    repeated_failure_codes: list[str]


@dataclass(frozen=True)
class BaselineReport:
    generated_at: str
    latest_trade_date: str | None
    batches: list[BaselineBatch]
    universe_counts: dict[str, dict[str, int]]
    repeated_failure_codes: list[str]
    legacy_claim: dict[str, object]


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _targets_for_job(session: Session, job_id: int) -> list[CrawlTargetResult]:
    prices = list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "prices",
            )
        )
    )
    if prices:
        return prices
    return list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "eod",
            )
        )
    )


def _repeated_failures(
    session: Session,
    job_ids: list[int],
) -> tuple[list[str], dict[int, list[str]]]:
    if not job_ids:
        return [], {}
    failures = list(
        session.scalars(
            select(CrawlFailure).where(CrawlFailure.job_id.in_(job_ids))
        )
    )
    by_job: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for failure in failures:
        by_job[failure.job_id].add((failure.target_key, failure.error_class))

    common: set[tuple[str, str]] = set()
    if len(job_ids) >= 3:
        sets = [by_job[job_id] for job_id in job_ids[:3]]
        common = set.intersection(*sets)
    common_codes = sorted({code for code, _error in common})
    per_job = {
        job_id: sorted({code for code, _error in by_job.get(job_id, set()) if code in common_codes})
        for job_id in job_ids
    }
    return common_codes, per_job


def _universe_counts(session: Session) -> dict[str, dict[str, int]]:
    rows = list(session.scalars(select(Symbol)))
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        symbol_type = row.symbol_type if row.symbol_type in {"stock", "etf", "etn"} else "unknown"
        counts[row.market][symbol_type] += 1
        counts[row.market]["active" if row.is_active else "inactive"] += 1
    return {
        market: {
            "stock": values["stock"],
            "etf": values["etf"],
            "etn": values["etn"],
            "active": values["active"],
            "inactive": values["inactive"],
        }
        for market, values in sorted(counts.items())
    }


def _legacy_claim_from_log(log_path: str | Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "target_count": 2400,
        "duration_hours": 2.0,
        "verified": False,
        "source": str(log_path) if log_path else None,
        "reason": "no operational log supplied",
    }
    if not log_path:
        return result
    path = Path(log_path)
    if not path.exists():
        result["reason"] = "operational log does not exist"
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    count_match = re.search(r"(?:symbols|종목)[^\n\d]{0,30}(2[,.]?400)", text, re.IGNORECASE)
    duration_match = re.search(r"(?:2\s*hours?|2시간)", text, re.IGNORECASE)
    result["verified"] = bool(count_match and duration_match)
    result["reason"] = (
        "unambiguous 2,400-target/2-hour observation found"
        if result["verified"]
        else "log does not contain both required observations"
    )
    return result


def build_baseline_report(
    session: Session,
    *,
    batch_limit: int = 3,
    log_path: str | Path | None = None,
    now: datetime | None = None,
) -> BaselineReport:
    """Collect the CRAWL-00 baseline from persisted operational data."""
    jobs = list(
        session.scalars(
            select(CrawlJob)
            .order_by(desc(CrawlJob.started_at))
            .limit(batch_limit)
        )
    )
    job_ids = [job.id for job in jobs]
    repeated_codes, per_job_repeated = _repeated_failures(session, job_ids)
    batches: list[BaselineBatch] = []
    for job in jobs:
        targets = _targets_for_job(session, job.id)
        counts = Counter(target.status for target in targets)
        eligible = len(targets) or job.symbols_total
        fetched = counts["fetched"] or (job.symbols_succeeded if not targets else 0)
        no_new_data = counts["no_new_data"]
        partial = counts["partial"]
        failed = counts["failed"] or (job.symbols_failed if not targets else 0)
        skipped = counts["skipped"]
        covered = fetched + no_new_data + skipped
        duration = (
            (job.finished_at - job.started_at).total_seconds()
            if job.finished_at is not None
            else None
        )
        batches.append(
            BaselineBatch(
                job_id=job.id,
                status=job.status,
                started_at=job.started_at.isoformat(),
                finished_at=_iso(job.finished_at),
                duration_seconds=duration,
                eligible=eligible,
                fetched=fetched,
                no_new_data=no_new_data,
                partial=partial,
                failed=failed,
                skipped=skipped,
                coverage_rate=(covered / eligible if eligible else 0.0),
                request_count=(sum(target.attempt_count for target in targets) if targets else None),
                retry_count=(sum(target.retry_count for target in targets) if targets else None),
                failure_count=sum(
                    1
                    for failure in session.scalars(
                        select(CrawlFailure).where(CrawlFailure.job_id == job.id)
                    )
                ),
                repeated_failure_codes=per_job_repeated.get(job.id, []),
            )
        )

    latest_trade_date = session.scalar(
        select(DailyPrice.trade_date).order_by(desc(DailyPrice.trade_date)).limit(1)
    )
    return BaselineReport(
        generated_at=(now or datetime.utcnow()).isoformat(),
        latest_trade_date=_iso(latest_trade_date),
        batches=batches,
        universe_counts=_universe_counts(session),
        repeated_failure_codes=repeated_codes,
        legacy_claim=_legacy_claim_from_log(log_path),
    )


def write_baseline_report(
    session: Session,
    output_path: str | Path,
    *,
    batch_limit: int = 3,
    log_path: str | Path | None = None,
) -> BaselineReport:
    """Collect and atomically write a JSON baseline report."""
    report = build_baseline_report(
        session,
        batch_limit=batch_limit,
        log_path=log_path,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return report
