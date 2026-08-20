"""Build immutable quality snapshots from crawl audit records."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import json

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_quality_report import CrawlQualityReport
from app.models.crawl_target_result import CrawlTargetResult
from app.repositories.crawl_quality_report_repository import CrawlQualityReportRepository


QUALITY_REPORT_SCHEMA_VERSION = 1
REPEATED_FAILURE_WINDOW_JOBS = 3
MAX_SAMPLE_REFS_PER_ERROR = 3


def classify_quality_error(
    *,
    error_class: str | None,
    error_message: str | None,
    http_status: int | None = None,
) -> str:
    """Map raw crawler failures to a compact, stable analysis taxonomy."""
    message = (error_message or "").lower()
    error_name = (error_class or "").lower()
    if "corporate action" in message or "adjusted-price" in message:
        return "corporate_action"
    if (
        "ohlc" in message
        or "price fields must be positive" in message
        or "price field" in message
        or "inconsistent" in message
    ):
        return "invalid_ohlc"
    if "no data rows" in message or "empty response" in message or "no rows" in message:
        return "no_data_rows"
    if "json" in error_name or "parse" in error_name or "decode" in message:
        return "parse_error"
    if "persist" in error_name or "database" in message or "integrityerror" in error_name:
        return "persistence_error"
    if (
        http_status is not None
        or "timeout" in message
        or "timed out" in message
        or "connection" in message
        or "network" in message
        or "http" in error_name
    ):
        return "network_error"
    return "unclassified"


def ensure_crawl_quality_report(session: Session, *, crawl_job_id: int) -> CrawlQualityReport:
    """Return the immutable report for a job, creating it exactly once."""
    repository = CrawlQualityReportRepository(session)
    existing = repository.get_by_job_id(crawl_job_id)
    if existing is not None:
        return existing

    job = session.get(CrawlJob, crawl_job_id)
    if job is None:
        raise ValueError(f"CrawlJob with id {crawl_job_id} not found")

    targets = _job_targets(session, crawl_job_id)
    failures = list(
        session.scalars(
            select(CrawlFailure)
            .where(CrawlFailure.job_id == crawl_job_id)
            .order_by(CrawlFailure.created_at, CrawlFailure.id)
        )
    )
    error_distribution = _error_distribution(failures)
    sample_refs = _sample_refs(failures, targets)
    trade_date = _latest_trade_date(targets)
    symbols_total = job.symbols_total if job.symbols_total else len(targets)
    symbols_succeeded = job.symbols_succeeded
    symbols_failed = job.symbols_failed
    if targets and symbols_succeeded + symbols_failed == 0:
        counts = Counter(target.status for target in targets)
        symbols_succeeded = counts["fetched"] + counts["no_new_data"] + counts["skipped"]
        symbols_failed = counts["failed"] + counts["partial"]

    covered = sum(
        1 for target in targets if target.status in {"fetched", "no_new_data", "skipped"}
    )
    coverage_denominator = len(targets) or symbols_total
    source_snapshot = {
        "target_result_count": len(targets),
        "provider_counts": dict(sorted(Counter((target.provider or "unknown") for target in targets).items())),
        "target_status_counts": dict(sorted(Counter(target.status for target in targets).items())),
    }
    values = {
        "crawl_job_id": job.id,
        "report_schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "trade_date": trade_date,
        "job_type": job.job_type,
        "job_status": job.status,
        "symbols_total": symbols_total,
        "symbols_succeeded": symbols_succeeded,
        "symbols_failed": symbols_failed,
        "failure_event_count": len(failures),
        "success_rate": (symbols_succeeded / symbols_total) if symbols_total else 0.0,
        "coverage_rate": (covered / coverage_denominator) if coverage_denominator else 0.0,
        "error_distribution": error_distribution,
        "repeated_failure_summary": _repeated_failure_summary(session, crawl_job_id),
        "anomaly_summary": _anomaly_summary(targets, failures),
        "sample_refs": sample_refs,
        "source_snapshot": source_snapshot,
    }
    values["report_hash"] = _report_hash(values)
    return repository.create(**values)


def missing_daily_quality_report_job_ids(
    session: Session,
    *,
    crawl_job_ids: list[int] | None = None,
    limit: int = 1_000,
    newest_first: bool = False,
) -> list[int]:
    """Find completed daily jobs that have not yet received an immutable report.

    This powers the operator backfill command after an independent report-write
    failure.  It intentionally never selects an already reported job, so a
    backfill cannot overwrite an immutable quality snapshot.
    """
    if limit < 1 or limit > 10_000:
        raise ValueError("limit must be between 1 and 10000")
    stmt = (
        select(CrawlJob.id)
        .outerjoin(CrawlQualityReport, CrawlQualityReport.crawl_job_id == CrawlJob.id)
        .where(
            CrawlJob.job_type == "daily_full",
            CrawlJob.finished_at.is_not(None),
            CrawlQualityReport.id.is_(None),
        )
        .order_by(
            desc(CrawlJob.finished_at) if newest_first else CrawlJob.finished_at,
            desc(CrawlJob.id) if newest_first else CrawlJob.id,
        )
        .limit(limit)
    )
    if crawl_job_ids:
        stmt = stmt.where(CrawlJob.id.in_(sorted(set(crawl_job_ids))))
    return list(session.scalars(stmt))


def _job_targets(session: Session, crawl_job_id: int) -> list[CrawlTargetResult]:
    targets = list(
        session.scalars(
            select(CrawlTargetResult)
            .where(
                CrawlTargetResult.job_id == crawl_job_id,
                CrawlTargetResult.step_name == "prices",
            )
            .order_by(CrawlTargetResult.target_key)
        )
    )
    if targets:
        return targets
    return list(
        session.scalars(
            select(CrawlTargetResult)
            .where(
                CrawlTargetResult.job_id == crawl_job_id,
                CrawlTargetResult.step_name == "eod",
            )
            .order_by(CrawlTargetResult.target_key)
        )
    )


def _error_distribution(failures: list[CrawlFailure]) -> dict[str, dict[str, int]]:
    events: Counter[str] = Counter()
    symbols: dict[str, set[str]] = defaultdict(set)
    for failure in failures:
        error_type = classify_quality_error(
            error_class=failure.error_class,
            error_message=failure.error_message,
            http_status=failure.http_status,
        )
        events[error_type] += 1
        symbols[error_type].add(failure.target_key)
    return {
        error_type: {"events": events[error_type], "symbols": len(symbols[error_type])}
        for error_type in sorted(events)
    }


def _sample_refs(
    failures: list[CrawlFailure],
    targets: list[CrawlTargetResult],
) -> dict[str, dict[str, list[int]]]:
    refs: dict[str, dict[str, list[int]]] = {}
    target_by_key = {target.target_key: target.id for target in targets}
    for failure in failures:
        error_type = classify_quality_error(
            error_class=failure.error_class,
            error_message=failure.error_message,
            http_status=failure.http_status,
        )
        current = refs.setdefault(error_type, {"failure_ids": [], "target_result_ids": []})
        if len(current["failure_ids"]) < MAX_SAMPLE_REFS_PER_ERROR:
            current["failure_ids"].append(failure.id)
        target_id = target_by_key.get(failure.target_key)
        if target_id is not None and len(current["target_result_ids"]) < MAX_SAMPLE_REFS_PER_ERROR:
            current["target_result_ids"].append(target_id)
    return {key: refs[key] for key in sorted(refs)}


def _latest_trade_date(targets: list[CrawlTargetResult]) -> date | None:
    candidates = [
        candidate
        for target in targets
        for candidate in (target.trade_date, target.latest_date_after)
        if candidate is not None
    ]
    return max(candidates) if candidates else None


def _repeated_failure_summary(session: Session, crawl_job_id: int) -> dict[str, object]:
    window_job_ids = list(
        session.scalars(
            select(CrawlJob.id)
            .where(CrawlJob.finished_at.is_not(None), CrawlJob.id <= crawl_job_id)
            .order_by(desc(CrawlJob.finished_at), desc(CrawlJob.id))
            .limit(REPEATED_FAILURE_WINDOW_JOBS)
        )
    )
    if not window_job_ids:
        return {"window_job_ids": [], "items": []}
    failures = list(
        session.scalars(
            select(CrawlFailure).where(CrawlFailure.job_id.in_(window_job_ids))
        )
    )
    jobs_by_failure: dict[tuple[str, str], set[int]] = defaultdict(set)
    for failure in failures:
        error_type = classify_quality_error(
            error_class=failure.error_class,
            error_message=failure.error_message,
            http_status=failure.http_status,
        )
        jobs_by_failure[(failure.target_key, error_type)].add(failure.job_id)
    items = [
        {"target_key": target_key, "error_type": error_type, "job_count": len(job_ids)}
        for (target_key, error_type), job_ids in jobs_by_failure.items()
        if len(job_ids) >= REPEATED_FAILURE_WINDOW_JOBS
    ]
    items.sort(key=lambda item: (-item["job_count"], item["error_type"], item["target_key"]))
    return {"window_job_ids": sorted(window_job_ids), "items": items[:50]}


def _anomaly_summary(
    targets: list[CrawlTargetResult],
    failures: list[CrawlFailure],
) -> dict[str, int]:
    return {
        "failed_target_count": sum(target.status == "failed" for target in targets),
        "partial_target_count": sum(target.status == "partial" for target in targets),
        "zero_rows_fetched_count": sum(
            target.status == "fetched" and target.rows_received == 0 for target in targets
        ),
        "failure_without_http_status_count": sum(
            failure.http_status is None for failure in failures
        ),
    }


def _report_hash(values: dict[str, object]) -> str:
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
