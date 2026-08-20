from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager

import app.models
from app.core.base import Base
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.services.monitoring.crawl_quality_report import (
    classify_quality_error,
    ensure_crawl_quality_report,
    missing_daily_quality_report_job_ids,
)
from app.services.batch import orchestrator as orchestrator_module
from app.services.batch.orchestrator import BatchOrchestrator


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def add_job(session, *, days_ago: int, status: str = "completed_with_errors"):
    now = datetime(2026, 8, 15, 9, 0, 0)
    job = CrawlJob(
        job_type="daily_full",
        started_at=now - timedelta(days=days_ago, minutes=30),
        finished_at=now - timedelta(days=days_ago),
        status=status,
        symbols_total=4,
        symbols_succeeded=2,
        symbols_failed=2,
    )
    session.add(job)
    session.flush()
    return job


def add_failure(session, job_id, target_key, message, *, error_class="ValidationError", http_status=None):
    session.add(
        CrawlFailure(
            job_id=job_id,
            target_type="stock",
            target_key=target_key,
            url="https://example.test/fchart",
            error_class=error_class,
            error_message=message,
            http_status=http_status,
        )
    )


def test_quality_report_is_immutable_job_snapshot_with_classified_counts():
    engine, session = make_session()
    older_jobs = [add_job(session, days_ago=offset) for offset in (3, 2)]
    job = add_job(session, days_ago=1)
    for current in [*older_jobs, job]:
        add_failure(session, current.id, "005930", "fchart response has no data rows")
    add_failure(session, job.id, "000660", "OHLC fields must be positive")
    session.add_all(
        [
            CrawlTargetResult(
                job_id=job.id,
                step_name="prices",
                target_key="005930",
                status="failed",
                rows_received=0,
                rows_persisted=0,
                trade_date=date(2026, 8, 14),
            ),
            CrawlTargetResult(
                job_id=job.id,
                step_name="prices",
                target_key="000660",
                status="failed",
                rows_received=1,
                rows_persisted=0,
                trade_date=date(2026, 8, 14),
            ),
            CrawlTargetResult(
                job_id=job.id,
                step_name="prices",
                target_key="035420",
                status="fetched",
                provider="naver",
                rows_received=1,
                rows_persisted=1,
                trade_date=date(2026, 8, 14),
            ),
        ]
    )
    session.commit()

    report = ensure_crawl_quality_report(session, crawl_job_id=job.id)
    same_report = ensure_crawl_quality_report(session, crawl_job_id=job.id)

    assert same_report.id == report.id
    assert report.trade_date == date(2026, 8, 14)
    assert report.failure_event_count == 2
    assert report.error_distribution == {
        "invalid_ohlc": {"events": 1, "symbols": 1},
        "no_data_rows": {"events": 1, "symbols": 1},
    }
    assert report.success_rate == 0.5
    assert report.coverage_rate == 1 / 3
    assert report.repeated_failure_summary["items"] == [
        {"target_key": "005930", "error_type": "no_data_rows", "job_count": 3}
    ]
    assert report.sample_refs["no_data_rows"]["failure_ids"]
    assert report.report_hash

    session.close()
    engine.dispose()


def test_quality_error_taxonomy_separates_data_and_transport_errors():
    assert classify_quality_error(error_class="ValidationError", error_message="corporate action remains") == "corporate_action"
    assert classify_quality_error(error_class="ValidationError", error_message="OHLC values are inconsistent") == "invalid_ohlc"
    assert classify_quality_error(error_class="PriceFetchError", error_message="timed out") == "network_error"
    assert classify_quality_error(error_class="JSONDecodeError", error_message="bad body") == "parse_error"


def test_backfill_selection_only_returns_missing_completed_daily_jobs():
    engine, session = make_session()
    reported_job = add_job(session, days_ago=2)
    missing_daily_job = add_job(session, days_ago=1)
    non_daily_job = CrawlJob(
        job_type="sync_symbols",
        started_at=datetime(2026, 8, 15, 8, 0, 0),
        finished_at=datetime(2026, 8, 15, 9, 0, 0),
        status="completed",
    )
    running_daily_job = CrawlJob(job_type="daily_full", started_at=datetime(2026, 8, 15, 9, 0, 0))
    session.add_all([non_daily_job, running_daily_job])
    session.commit()
    ensure_crawl_quality_report(session, crawl_job_id=reported_job.id)
    session.commit()

    assert missing_daily_quality_report_job_ids(session) == [missing_daily_job.id]
    assert missing_daily_quality_report_job_ids(
        session,
        crawl_job_ids=[reported_job.id, missing_daily_job.id, non_daily_job.id],
    ) == [missing_daily_job.id]
    newest_daily_job = add_job(session, days_ago=0)
    session.commit()
    assert missing_daily_quality_report_job_ids(session, newest_first=True) == [
        newest_daily_job.id,
        missing_daily_job.id,
    ]
    session.close()
    engine.dispose()


def test_batch_finish_writes_quality_report_in_a_follow_up_transaction(monkeypatch):
    engine, session = make_session()
    job = CrawlJob(job_type="daily_full", started_at=datetime(2026, 8, 15, 8, 0, 0))
    session.add(job)
    session.commit()

    @contextmanager
    def sqlite_scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(orchestrator_module, "session_scope", sqlite_scope)
    batch = BatchOrchestrator(source=object())
    batch.job_id = job.id
    batch._finish_job(
        status="completed",
        symbols_total=1,
        symbols_succeeded=1,
        symbols_failed=0,
        message="complete",
    )

    report = ensure_crawl_quality_report(session, crawl_job_id=job.id)
    assert report.job_status == "completed"
    assert report.symbols_total == 1
    session.close()
    engine.dispose()


def test_orchestrator_ignores_legacy_fallback_source():
    primary = object()
    legacy_fallback = object()

    batch = BatchOrchestrator(source=primary, fallback_source=legacy_fallback)

    assert batch.source is primary
    assert batch.fallback_source is None
