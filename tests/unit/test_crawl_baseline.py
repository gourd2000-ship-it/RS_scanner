from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.core.base import Base
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.services.monitoring.crawl_baseline import build_baseline_report


def test_baseline_report_contains_three_batch_metrics_and_universe_counts():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime(2026, 8, 11, 12, 0)
    symbol = Symbol(code="A", name="Alpha", market="KOSPI", symbol_type="stock")
    etf = Symbol(code="E", name="ETF", market="KOSPI", symbol_type="etf", is_active=False)
    session.add_all([symbol, etf])
    session.flush()

    jobs = []
    for index in range(3):
        job = CrawlJob(
            job_type="daily_full",
            started_at=now - timedelta(days=index),
            finished_at=now - timedelta(days=index) + timedelta(minutes=5),
            status="completed_with_errors" if index == 0 else "completed",
            symbols_total=2,
            symbols_succeeded=1,
            symbols_failed=1,
        )
        session.add(job)
        session.flush()
        jobs.append(job)
        session.add_all(
            [
                CrawlTargetResult(
                    job_id=job.id,
                    step_name="prices",
                    target_key="A",
                    status="fetched",
                    attempt_count=2,
                    retry_count=1,
                ),
                CrawlTargetResult(
                    job_id=job.id,
                    step_name="prices",
                    target_key="E",
                    status="failed",
                    attempt_count=1,
                    retry_count=0,
                ),
                CrawlFailure(
                    job_id=job.id,
                    target_type="daily_price",
                    target_key="E",
                    url="https://provider.test/E",
                    error_class="PriceFetchError",
                    error_message="timeout",
                ),
            ]
        )
    session.add(
        DailyPrice(
            symbol_id=symbol.id,
            trade_date=date(2026, 8, 10),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=1,
            change_rate=Decimal("0"),
        )
    )
    session.commit()

    report = build_baseline_report(session, now=now)

    assert len(report.batches) == 3
    assert report.batches[0].request_count == 3
    assert report.batches[0].retry_count == 1
    assert report.batches[0].coverage_rate == 0.5
    assert report.universe_counts["KOSPI"] == {
        "stock": 1,
        "etf": 1,
        "etn": 0,
        "active": 1,
        "inactive": 1,
    }
    assert report.repeated_failure_codes == ["E"]
    assert report.latest_trade_date == "2026-08-10"
    assert report.legacy_claim["verified"] is False

    session.close()
    engine.dispose()
