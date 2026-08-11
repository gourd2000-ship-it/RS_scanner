"""Persisted crawl quality metrics and alert conditions."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.metrics import metrics
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot


COVERAGE_ALERT_THRESHOLD = 0.995
REPEATED_FAILURE_ALERT_THRESHOLD = 3
QUALITY_METRIC_NAMES = (
    "crawl_eligible_total",
    "crawl_fetched_total",
    "crawl_no_new_data_total",
    "crawl_partial_total",
    "crawl_failed_total",
    "crawl_skipped_total",
    "crawl_failure_record_error_total",
    "crawl_parser_error_total",
    "crawl_provider_request_total",
    "crawl_provider_latency_seconds",
    "crawl_duration_seconds",
    "crawl_coverage_rate",
    "symbols_deactivated_total",
    "hermes_api_errors_total",
)


@dataclass(frozen=True)
class CrawlMetricsSnapshot:
    job_id: int | None
    trade_date: date | None
    metrics: dict[str, float]
    alerts: list[str]


def build_crawl_metrics(
    session: Session,
    *,
    now: datetime | None = None,
) -> CrawlMetricsSnapshot:
    now = now or datetime.utcnow()
    values = {name: 0.0 for name in QUALITY_METRIC_NAMES}
    latest_job = session.scalar(
        select(CrawlJob).order_by(desc(CrawlJob.started_at)).limit(1)
    )
    latest_trade_date = session.scalar(select(DailyPrice.trade_date).order_by(desc(DailyPrice.trade_date)).limit(1))
    alerts: list[str] = []

    if latest_job is not None:
        targets = _latest_price_targets(session, latest_job.id)
        if targets:
            counts = Counter(target.status for target in targets)
            values.update(
                {
                    "crawl_eligible_total": float(len(targets)),
                    "crawl_fetched_total": float(counts["fetched"]),
                    "crawl_no_new_data_total": float(counts["no_new_data"]),
                    "crawl_partial_total": float(counts["partial"]),
                    "crawl_failed_total": float(counts["failed"]),
                    "crawl_skipped_total": float(counts["skipped"]),
                }
            )
            covered = counts["fetched"] + counts["no_new_data"] + counts["skipped"]
            values["crawl_coverage_rate"] = covered / len(targets)
        else:
            values["crawl_eligible_total"] = float(latest_job.symbols_total)
            values["crawl_fetched_total"] = float(latest_job.symbols_succeeded)
            values["crawl_failed_total"] = float(latest_job.symbols_failed)
            if latest_job.symbols_total:
                values["crawl_coverage_rate"] = (
                    latest_job.symbols_succeeded / latest_job.symbols_total
                )

        if latest_job.symbols_total and values["crawl_coverage_rate"] < COVERAGE_ALERT_THRESHOLD:
            alerts.append("coverage_below_threshold")
        if latest_job.status in {"failed", "completed_with_errors"}:
            alerts.append("latest_job_not_clean")
        if latest_job.finished_at is not None:
            freshness_limit = timedelta(hours=get_settings().agent_freshness_max_age_hours)
            if now - latest_job.finished_at > freshness_limit:
                alerts.append("latest_dataset_stale")

    snapshot = session.scalar(
        select(SymbolUniverseSnapshot)
        .where(SymbolUniverseSnapshot.status == "completed")
        .order_by(desc(SymbolUniverseSnapshot.finished_at), desc(SymbolUniverseSnapshot.started_at))
        .limit(1)
    )
    if snapshot is not None:
        values["symbols_deactivated_total"] = float(len(snapshot.deactivation_candidates or []))

    alerts.extend(_repeated_failure_alerts(session))
    process_metrics = metrics.snapshot()
    for name in (
        "crawl_failure_record_error_total",
        "hermes_api_errors_total",
        "crawl_parser_error_total",
        "crawl_provider_request_total",
        "crawl_provider_latency_seconds",
        "crawl_duration_seconds",
    ):
        values[name] = process_metrics.get(name, 0.0)

    return CrawlMetricsSnapshot(
        job_id=latest_job.id if latest_job is not None else None,
        trade_date=latest_trade_date,
        metrics=values,
        alerts=sorted(set(alerts)),
    )


def _latest_price_targets(session: Session, job_id: int) -> list[CrawlTargetResult]:
    targets = list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "prices",
            )
        )
    )
    if targets:
        return targets
    return list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "eod",
            )
        )
    )


def _repeated_failure_alerts(session: Session) -> list[str]:
    recent_job_ids = list(
        session.scalars(
            select(CrawlJob.id)
            .order_by(desc(CrawlJob.started_at))
            .limit(REPEATED_FAILURE_ALERT_THRESHOLD)
        )
    )
    if len(recent_job_ids) < REPEATED_FAILURE_ALERT_THRESHOLD:
        return []

    failures = list(
        session.scalars(
            select(CrawlFailure).where(CrawlFailure.job_id.in_(recent_job_ids))
        )
    )
    by_job: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for failure in failures:
        by_job[failure.job_id].add((failure.target_key, failure.error_class))
    repeated = set.intersection(*(by_job[job_id] for job_id in recent_job_ids))
    if not repeated:
        return []
    return ["repeated_failure_detected"]
