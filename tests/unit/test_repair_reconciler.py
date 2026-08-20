from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.base import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.services.repair_queue import RepairQueueService, RepairResultRow
from app.services.repair_reconciler import RepairReconciler


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def setup_request(session: Session, *, row_change_rate: Decimal | None = Decimal("1.2")):
    symbol = Symbol(code="005930", name="Samsung", market="KOSPI")
    job = CrawlJob(job_type="daily_full")
    session.add_all([symbol, job])
    session.flush()
    target = CrawlTargetResult(
        job_id=job.id,
        step_name="prices",
        target_key="005930",
        status="failed",
        provider="NaverPriceSource",
        error_class="PriceFetchError",
        error_message="Naver unavailable",
        trade_date=date(2026, 8, 14),
    )
    session.add(target)
    session.flush()

    service = RepairQueueService(session)
    request, created = service.enqueue_from_target(
        job_id=job.id,
        crawl_target_result_id=target.id,
        symbol="005930",
        trade_date=date(2026, 8, 14),
        history_from=date(2026, 8, 1),
        error_type="failed",
    )
    assert created
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None
    completed = service.complete(
        request_id=request.id,
        claim_token=claim.claim_token,
        claim_version=claim.request.claim_version,
        operation="daily_chart",
        symbol="005930",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 14),
        adjusted_price=True,
        executor="sam",
        tool="kiwoomcli",
        mode="demo",
        latest_date=date(2026, 8, 13),
        row_count=1,
        data_complete=True,
        rows=[
            RepairResultRow(
                symbol="005930",
                trade_date=date(2026, 8, 13),
                source="kiwoom",
                adjusted_price=True,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=1000,
                change_rate=row_change_rate,
            )
        ],
    )
    assert completed.status == "completed"
    return request, target


def test_reconciler_applies_missing_rows_and_is_idempotent(session):
    request, target = setup_request(session)

    reconciler = RepairReconciler(session)
    outcome = reconciler.apply_request(request.id)
    assert outcome.application_status == "applied"
    assert outcome.applied_row_count == 1
    assert target.status == "fetched"
    assert target.provider == "kiwoom"

    price = session.scalar(
        select(DailyPrice).join(Symbol).where(
            Symbol.code == "005930", DailyPrice.trade_date == date(2026, 8, 13)
        )
    )
    assert price is not None
    assert price.close == Decimal("105.0000")
    assert price.source == "kiwoom"

    second = reconciler.apply_request(request.id)
    assert second.application_status == "applied"
    assert second.applied_row_count == 1
    assert session.query(DailyPrice).count() == 1


def test_reconciler_marks_conflict_without_overwriting_naver(session):
    request, _target = setup_request(session)
    symbol = session.scalar(select(Symbol).where(Symbol.code == "005930"))
    session.add(
        DailyPrice(
            symbol_id=symbol.id,
            trade_date=date(2026, 8, 13),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("104"),
            volume=1000,
            change_rate=Decimal("1.2"),
            source="naver",
        )
    )
    session.flush()

    outcome = RepairReconciler(session).apply_request(request.id)
    assert outcome.application_status == "conflict"
    assert outcome.conflict_dates == (date(2026, 8, 13),)
    assert "provider_conflict" in outcome.message

    price = session.scalar(
        select(DailyPrice).join(Symbol).where(
            Symbol.code == "005930", DailyPrice.trade_date == date(2026, 8, 13)
        )
    )
    assert price.close == Decimal("104.0000")
    assert price.source == "naver"


def test_reconciler_rejects_result_without_change_rate(session):
    request, _target = setup_request(session, row_change_rate=None)

    outcome = RepairReconciler(session).apply_request(request.id)
    assert outcome.application_status == "rejected"
    assert "change_rate" in outcome.message
    assert session.query(DailyPrice).count() == 0
