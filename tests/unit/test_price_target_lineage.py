from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.crawl_job import CrawlJob
from app.models.instrument import Instrument
from app.models.krx_universe import KrxUniverseSnapshot
from app.repositories.crawl_target_result_repository import CrawlTargetResultRepository
from app.schemas.market_data import SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import sync_prices
from app.services.universe_target_builder import UniversePriceTarget
from tests.harness.fake_source import FakePriceSource


def test_price_target_result_preserves_krx_snapshot_instrument_and_eligibility_lineage():
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

    result = CrawlTargetResultRepository(session).record_result(
        job.id,
        "prices",
        "005930",
        "fetched",
        krx_snapshot_id=snapshot.id,
        instrument_id=instrument.id,
        price_eligibility="eligible",
        eligibility_reason=None,
    )

    assert result.krx_snapshot_id == snapshot.id
    assert result.instrument_id == instrument.id
    assert result.price_eligibility == "eligible"


def test_price_sync_records_selected_krx_target_lineage():
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(
        [SymbolPayload(code="005930", name="삼성전자", market="KOSPI")]
    )
    context.job_id = context.crawl_job_repository.create_job("daily_full").id
    source = FakePriceSource(
        symbols=[],
        prices_by_code={"005930": []},
        benchmark_prices_by_market={},
    )
    lineage = UniversePriceTarget(
        krx_snapshot_id=11,
        instrument_id=22,
        krx_code="005930",
        provider_symbol="005930",
        market="KOSPI",
        security_type="stock",
        price_eligibility="eligible",
        reason_code=None,
    )

    sync_prices(
        context,
        source,
        target_codes={"005930"},
        target_lineage={"005930": lineage},
    )

    result = context.crawl_target_result_repository.get_by_target(
        context.job_id, "prices", "005930"
    )
    assert result is not None
    assert result.krx_snapshot_id == 11
    assert result.instrument_id == 22
    assert result.price_eligibility == "eligible"
