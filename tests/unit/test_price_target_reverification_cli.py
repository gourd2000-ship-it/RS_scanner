from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.base import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
import scripts.verify_price_target_results as verifier_cli


def test_verifier_uses_latest_price_completed_job_not_newer_failed_job(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 20, 9, 0)
    with Session(engine) as session:
        completed = CrawlJob(
            job_type="daily_full",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
            status="completed",
            symbols_total=2,
        )
        failed = CrawlJob(
            job_type="daily_full",
            started_at=now - timedelta(minutes=30),
            finished_at=now,
            status="failed",
            symbols_total=0,
        )
        session.add_all([completed, failed])
        session.flush()
        completed_id = completed.id
        session.add_all(
            [
                CrawlTargetResult(
                    job_id=completed.id,
                    step_name="prices",
                    target_key="A",
                    status="fetched",
                ),
                CrawlTargetResult(
                    job_id=completed.id,
                    step_name="prices",
                    target_key="B",
                    status="no_new_data",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(verifier_cli, "SessionLocal", sessionmaker(bind=engine))

    report = verifier_cli.build_verification_from_database(job_id=None)

    assert report.job_id == completed_id
    assert report.target_count_matches_results is True
    engine.dispose()
