import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.batch_checkpoint import BatchCheckpoint
from app.models.crawl_job import CrawlJob
from app.models.krx_universe import KrxUniverseSnapshot
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.models.universe_canary_decision import UniverseCanaryDecision
from app.models.universe_reconciliation import UniverseReconciliationRun
from app.services.universe_canary_decision import record_canary_decision


def test_record_canary_decision_derives_immutable_evidence_from_price_checkpoint():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full", status="completed")
    session.add(job)
    session.flush()
    krx_snapshot = KrxUniverseSnapshot(
        crawl_job_id=job.id,
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 20),
        status="completed",
        members_seen=2763,
        members_valid=2763,
    )
    naver_snapshot = SymbolUniverseSnapshot(
        job_id=job.id,
        provider="naver",
        market="ALL",
        status="completed",
    )
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    reconciliation = UniverseReconciliationRun(
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        status="approved",
        report={"mapping_rate": 1.0},
    )
    session.add(reconciliation)
    session.flush()
    session.add(
        BatchCheckpoint(
            job_id=job.id,
            step_name="prices",
            status="completed",
            step_metadata=json.dumps(
                {
                    "universe_selection": {
                        "approved_reconciliation_run_id": reconciliation.id,
                        "approved_krx_snapshot_id": krx_snapshot.id,
                        "authority_by_market": {"KOSPI": "krx"},
                        "fallback_reason_by_market": {"KOSPI": None},
                        "target_count_by_market": {"KOSPI": 2476},
                    }
                }
            ),
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="두 거래일"):
        record_canary_decision(
            session,
            crawl_job_id=job.id,
            market="KOSPI",
            operator_decision="expand",
            approved_by="ops-reviewer",
        )

    decision = record_canary_decision(
        session,
        crawl_job_id=job.id,
        market="KOSPI",
        operator_decision="continue",
        approved_by="ops-reviewer",
    )

    assert decision.crawl_job_id == job.id
    assert decision.market == "KOSPI"
    assert decision.trade_date == date(2026, 8, 20)
    assert decision.krx_snapshot_id == krx_snapshot.id
    assert decision.reconciliation_run_id == reconciliation.id
    assert decision.authority == "krx"
    assert decision.fallback_reason is None
    assert decision.mapping_rate == 1.0
    assert decision.target_count == 2476
    assert decision.operator_decision == "continue"
    assert decision.approved_by == "ops-reviewer"

    reconciliation.report = {"mapping_rate": 0.994}
    with pytest.raises(ValueError, match="매핑률"):
        record_canary_decision(
            session,
            crawl_job_id=job.id,
            market="KOSPI",
            operator_decision="continue",
            approved_by="ops-reviewer",
        )


def test_record_canary_decision_allows_expand_after_two_prior_krx_continues():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full", status="completed")
    session.add(job)
    session.flush()
    krx_snapshot = KrxUniverseSnapshot(
        crawl_job_id=job.id,
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 20),
        status="completed",
        members_seen=2763,
        members_valid=2763,
    )
    naver_snapshot = SymbolUniverseSnapshot(
        job_id=job.id,
        provider="naver",
        market="ALL",
        status="completed",
    )
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    reconciliation = UniverseReconciliationRun(
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        status="approved",
        report={"mapping_rate": 1.0},
    )
    session.add_all(
        [
            reconciliation,
            UniverseCanaryDecision(
                crawl_job_id=job.id,
                trade_date=date(2026, 8, 18),
                market="KOSPI",
                authority="krx",
                target_count=2476,
                operator_decision="continue",
                approved_by="ops-reviewer",
            ),
            UniverseCanaryDecision(
                crawl_job_id=job.id,
                trade_date=date(2026, 8, 19),
                market="KOSPI",
                authority="krx",
                target_count=2476,
                operator_decision="continue",
                approved_by="ops-reviewer",
            ),
        ]
    )
    session.flush()
    session.add(
        BatchCheckpoint(
            job_id=job.id,
            step_name="prices",
            status="completed",
            step_metadata=json.dumps(
                {
                    "universe_selection": {
                        "approved_reconciliation_run_id": reconciliation.id,
                        "approved_krx_snapshot_id": krx_snapshot.id,
                        "authority_by_market": {"KOSPI": "krx"},
                        "fallback_reason_by_market": {"KOSPI": None},
                        "target_count_by_market": {"KOSPI": 2476},
                    }
                }
            ),
        )
    )
    session.commit()

    decision = record_canary_decision(
        session,
        crawl_job_id=job.id,
        market="KOSPI",
        operator_decision="expand",
        approved_by="ops-reviewer",
    )

    assert decision.operator_decision == "expand"
    assert decision.trade_date == date(2026, 8, 20)
