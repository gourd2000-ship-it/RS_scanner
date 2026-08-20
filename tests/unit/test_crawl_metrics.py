from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.core.base import Base
from app.core.metrics import metrics
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_repair import CrawlRepairAttempt, CrawlRepairRequest
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.services.monitoring.crawl_metrics import build_crawl_metrics


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def add_job(session, started_at, *, status="completed", total=3, succeeded=2, failed=1):
    job = CrawlJob(
        job_type="daily_full",
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=10),
        status=status,
        symbols_total=total,
        symbols_succeeded=succeeded,
        symbols_failed=failed,
    )
    session.add(job)
    session.flush()
    return job


def test_crawl_metrics_aggregate_target_status_and_alerts():
    metrics.reset()
    engine, session = make_session()
    now = datetime(2026, 8, 11, 12, 0, 0)
    jobs = [
        add_job(session, now - timedelta(days=2)),
        add_job(session, now - timedelta(days=1)),
        add_job(session, now - timedelta(hours=1), status="completed_with_errors"),
    ]
    latest = jobs[-1]
    session.add_all(
        [
            CrawlTargetResult(job_id=latest.id, step_name="prices", target_key="A", status="fetched"),
            CrawlTargetResult(job_id=latest.id, step_name="prices", target_key="B", status="no_new_data"),
            CrawlTargetResult(job_id=latest.id, step_name="prices", target_key="C", status="failed"),
            DailyPrice(
                symbol_id=1,
                trade_date=date(2026, 8, 10),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
                change_rate=0,
            ),
            SymbolUniverseSnapshot(
                job_id=latest.id,
                provider="fixture",
                status="completed",
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(minutes=50),
                deactivation_candidates=["OLD"],
            ),
        ]
    )
    session.flush()
    for job in jobs:
        session.add(
            CrawlFailure(
                job_id=job.id,
                target_type="daily_price",
                target_key="REPEAT",
                url="https://provider.test/repeat",
                error_class="PriceFetchError",
                error_message="timeout",
            )
        )
    session.commit()

    snapshot = build_crawl_metrics(session, now=now)

    assert snapshot.job_id == latest.id
    assert snapshot.trade_date == date(2026, 8, 10)
    assert snapshot.metrics["crawl_eligible_total"] == 3
    assert snapshot.metrics["crawl_fetched_total"] == 1
    assert snapshot.metrics["crawl_no_new_data_total"] == 1
    assert snapshot.metrics["crawl_failed_total"] == 1
    assert snapshot.metrics["crawl_coverage_rate"] == 2 / 3
    assert snapshot.metrics["symbols_deactivated_total"] == 1
    assert "coverage_below_threshold" in snapshot.alerts
    assert "latest_job_not_clean" in snapshot.alerts
    assert "repeated_failure_detected" in snapshot.alerts

    session.close()
    engine.dispose()


def test_crawl_metrics_exposes_process_error_counters_and_empty_state():
    metrics.reset()
    metrics.increment("crawl_failure_record_error_total", 2)
    metrics.increment("hermes_api_errors_total")
    engine, session = make_session()

    snapshot = build_crawl_metrics(session, now=datetime(2026, 8, 11, 12, 0, 0))

    assert snapshot.job_id is None
    assert snapshot.metrics["crawl_failure_record_error_total"] == 2
    assert snapshot.metrics["hermes_api_errors_total"] == 1
    assert snapshot.alerts == []

    session.close()
    engine.dispose()


def test_crawl_metrics_exposes_repair_queue_state_and_rate_limits():
    metrics.reset()
    engine, session = make_session()
    now = datetime(2026, 8, 14, 12, 0, 0)
    pending = CrawlRepairRequest(
        dedupe_key="job:pending",
        symbol="005930",
        trade_date=date(2026, 8, 14),
        error_type="empty_response",
        requested_at=now - timedelta(minutes=10),
        next_attempt_at=now,
    )
    completed = CrawlRepairRequest(
        dedupe_key="job:completed",
        symbol="000660",
        trade_date=date(2026, 8, 14),
        error_type="failed",
        status="completed",
        application_status="conflict",
        requested_at=now - timedelta(minutes=20),
        claimed_at=now - timedelta(minutes=19),
        completed_at=now - timedelta(minutes=18),
        next_attempt_at=now,
    )
    failed = CrawlRepairRequest(
        dedupe_key="job:failed",
        symbol="035420",
        trade_date=date(2026, 8, 14),
        error_type="failed",
        status="failed",
        requested_at=now - timedelta(minutes=30),
        next_attempt_at=now,
    )
    session.add_all([pending, completed, failed])
    session.flush()
    session.add(
        CrawlRepairAttempt(
            request_id=failed.id,
            attempt_no=1,
            status="failed",
            executor="sam",
            error_code="rate_limit",
            http_status=429,
            started_at=now - timedelta(minutes=29),
        )
    )
    session.commit()

    snapshot = build_crawl_metrics(session, now=now)

    assert snapshot.metrics["repair_pending"] == 1
    assert snapshot.metrics["repair_completed"] == 1
    assert snapshot.metrics["repair_failed"] == 1
    assert snapshot.metrics["repair_conflicts"] == 1
    assert snapshot.metrics["repair_queue_age_seconds"] == 600
    assert snapshot.metrics["repair_claim_latency_seconds"] == 60
    assert snapshot.metrics["kiwoom_rate_limit_errors"] == 1

    session.close()
    engine.dispose()


def test_crawl_metrics_exposes_krx_mapping_and_partial_snapshot_alert():
    metrics.reset()
    engine, session = make_session()
    now = datetime(2026, 8, 20, 12, 0, 0)
    naver_snapshot = SymbolUniverseSnapshot(
        provider="naver",
        status="completed",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
    )
    completed_krx = KrxUniverseSnapshot(
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 19),
        status="completed",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
    )
    session.add_all([naver_snapshot, completed_krx])
    session.flush()
    session.add_all(
        [
            Symbol(code="005930", name="삼성전자", market="KOSPI", last_snapshot_id=naver_snapshot.id),
            KrxUniverseMembership(
                snapshot_id=completed_krx.id,
                code="005930",
                name="삼성전자",
                market="KOSPI",
                security_type="stock",
                listing_status="listed_observed",
                trading_status="unknown",
                raw_fields={},
            ),
            KrxUniverseSnapshot(
                source="krx_open_api",
                scope="stock_membership",
                as_of_date=date(2026, 8, 20),
                status="partial",
                started_at=now - timedelta(minutes=10),
                finished_at=now - timedelta(minutes=9),
                error_message="KOSDAQ timeout",
            ),
        ]
    )
    session.commit()

    snapshot = build_crawl_metrics(session, now=now)

    assert snapshot.metrics["krx_mapping_rate"] == 1
    assert snapshot.metrics["krx_mapping_exact"] == 1
    assert snapshot.metrics["krx_snapshot_completed"] == 0
    assert "krx_snapshot_not_completed" in snapshot.alerts

    session.close()
    engine.dispose()
