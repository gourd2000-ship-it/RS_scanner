from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models
import app.services.agent_data as agent_data
from app.core.base import Base
from app.models.benchmark import Benchmark
from app.models.crawl_job import CrawlJob
from app.models.daily_price import DailyPrice
from app.models.rs_score import RsScore
from app.models.symbol import Symbol


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_job(session: Session, *, status: str, finished_at: datetime):
    symbol = Symbol(code="A", name="Alpha", market="KOSPI", is_active=True)
    session.add(symbol)
    session.flush()
    session.add(
        DailyPrice(
            symbol_id=symbol.id,
            trade_date=date(2026, 8, 10),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1,
            change_rate=Decimal("0"),
        )
    )
    benchmark = Benchmark(
        benchmark_code="KOSPI",
        name="KOSPI",
        market="KOSPI",
    )
    session.add(benchmark)
    session.flush()
    session.add(
        RsScore(
            symbol_id=symbol.id,
            benchmark_id=benchmark.id,
            trade_date=date(2026, 8, 10),
            market="KOSPI",
            return_3m=Decimal("0.1"),
            return_6m=Decimal("0.1"),
            return_9m=Decimal("0.1"),
            return_12m=Decimal("0.1"),
            relative_return_score=Decimal("0.1"),
            rs_percentile=Decimal("0.9"),
            rs_rating=90,
            rank_in_market=1,
        )
    )
    session.add(
        CrawlJob(
            job_type="daily_full",
            started_at=finished_at - timedelta(minutes=10),
            finished_at=finished_at,
            status=status,
            symbols_total=1,
            symbols_succeeded=1 if status != "failed" else 0,
            symbols_failed=0 if status == "completed" else 1,
        )
    )
    session.commit()


def test_agent_meta_is_unavailable_without_a_dataset():
    session = make_session()
    try:
        meta = agent_data.build_agent_meta(session)
        assert meta.data_status == "unavailable"
        assert meta.dataset_id == "rs-unavailable"
        assert meta.coverage == 0
    finally:
        session.close()


def test_agent_meta_exposes_complete_and_partial_states():
    now = datetime.utcnow()
    session = make_session()
    try:
        seed_job(session, status="completed", finished_at=now)
        meta = agent_data.build_agent_meta(session, now=now)
        assert meta.data_status == "complete"
        assert meta.coverage == 1
        assert meta.trade_date == date(2026, 8, 10)
    finally:
        session.close()

    session = make_session()
    try:
        seed_job(session, status="completed_with_errors", finished_at=now)
        meta = agent_data.build_agent_meta(session, now=now)
        assert meta.data_status == "partial"
    finally:
        session.close()


def test_agent_meta_marks_old_complete_dataset_stale(monkeypatch):
    monkeypatch.setattr(
        agent_data,
        "get_settings",
        lambda: SimpleNamespace(agent_freshness_max_age_hours=1),
    )
    now = datetime.utcnow()
    session = make_session()
    try:
        seed_job(session, status="completed", finished_at=now - timedelta(hours=2))
        meta = agent_data.build_agent_meta(session, now=now)
        assert meta.data_status == "stale"
    finally:
        session.close()
