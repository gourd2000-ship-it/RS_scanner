from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.v1.endpoints.crawl import (
    list_krx_universe_snapshots,
    list_crawl_target_results,
    list_universe_reconciliation_runs,
)
from app.core.base import Base
from app.models.krx_universe import KrxUniverseSnapshot
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.models.universe_reconciliation import UniverseReconciliationRun
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.instrument import Instrument


def test_operations_api_lists_krx_snapshots_and_reconciliation_runs_with_filters():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    krx = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    naver = SymbolUniverseSnapshot(provider="naver", status="completed")
    session.add_all([krx, naver])
    session.flush()
    session.add(
        UniverseReconciliationRun(
            krx_snapshot_id=krx.id,
            naver_snapshot_id=naver.id,
            status="pending_review",
            report={"mapping_rate": 1.0},
        )
    )
    session.commit()

    snapshots = list_krx_universe_snapshots(
        page=1, size=20, status="completed", scope=None, session=session
    )
    runs = list_universe_reconciliation_runs(
        page=1,
        size=20,
        krx_snapshot_id=krx.id,
        naver_snapshot_id=None,
        status="pending_review",
        session=session,
    )

    assert snapshots.total_count == 1
    assert snapshots.items[0].as_of_date == date(2026, 8, 19)
    assert runs.total_count == 1
    assert runs.items[0].report == {"mapping_rate": 1.0}


def test_operations_api_filters_price_target_lineage_by_krx_snapshot_and_eligibility():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full")
    snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    instrument = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    session.add_all([job, snapshot, instrument])
    session.flush()
    session.add(
        CrawlTargetResult(
            job_id=job.id,
            step_name="prices",
            target_key="005930",
            target_type="stock",
            status="fetched",
            krx_snapshot_id=snapshot.id,
            instrument_id=instrument.id,
            price_eligibility="eligible",
        )
    )
    session.commit()

    response = list_crawl_target_results(
        page=1,
        size=20,
        job_id=job.id,
        step_name="prices",
        status=None,
        krx_snapshot_id=snapshot.id,
        instrument_id=instrument.id,
        price_eligibility="eligible",
        session=session,
    )

    assert response.total_count == 1
    assert response.items[0].krx_snapshot_id == snapshot.id
    assert response.items[0].instrument_id == instrument.id
    assert response.items[0].price_eligibility == "eligible"
