"""Tests for market-scoped KRX price target selection."""

from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.crawl_job import CrawlJob
from app.models.instrument import Instrument, ProviderSymbol
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.models.universe_reconciliation import UniverseReconciliationRun
from app.schemas.market_data import SymbolPayload
from app.services.batch.context import build_db_batch_context
from app.services.batch.sync_prices import _resolve_universe_price_selection
from app.services.universe_price_selection import select_price_targets


def test_krx_canary_replaces_only_the_enabled_market_with_eligible_targets():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 20), status="completed"
    )
    session.add(snapshot)
    session.flush()
    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=snapshot.id, code="005930", name="삼성전자", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            KrxUniverseMembership(
                snapshot_id=snapshot.id, code="100001", name="Beta", market="KOSDAQ",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
        ]
    )
    samsung = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    beta = Instrument(
        krx_short_code="100001", name="Beta", market="KOSDAQ", security_type="stock", listing_status="listed"
    )
    session.add_all([samsung, beta])
    session.flush()
    session.add_all(
        [
            ProviderSymbol(instrument_id=samsung.id, provider="naver", provider_symbol="005930", mapping_status="matched"),
            ProviderSymbol(instrument_id=beta.id, provider="naver", provider_symbol="100001", mapping_status="matched"),
            UniverseReconciliationRun(
                krx_snapshot_id=snapshot.id,
                naver_snapshot_id=7,
                status="approved",
                report={"mapping_rate": 1.0},
            ),
        ]
    )
    session.commit()

    selection = select_price_targets(
        session,
        provider="naver",
        as_of_date=date(2026, 8, 20),
        naver_snapshot_id=7,
        naver_targets=[
            SymbolPayload(code="005930", name="삼성전자", market="KOSPI", symbol_type="stock"),
            SymbolPayload(code="999999", name="stale", market="KOSPI", symbol_type="stock"),
            SymbolPayload(code="ETF001", name="ETF 관측", market="KOSPI", symbol_type="etf"),
            SymbolPayload(code="100001", name="Beta", market="KOSDAQ", symbol_type="stock"),
        ],
        settings=SimpleNamespace(
            universe_authority="krx",
            universe_canary_markets="KOSPI",
            universe_mapping_rate_threshold=0.995,
        ),
    )

    assert selection.target_codes == frozenset({"005930", "ETF001", "100001"})
    assert selection.authority_by_market == {"KOSDAQ": "naver_last_completed", "KOSPI": "krx"}
    assert selection.lineage_by_code["005930"].instrument_id == samsung.id
    assert "100001" not in selection.lineage_by_code
    assert selection.to_audit_metadata() == {
        "approved_reconciliation_run_id": 1,
        "approved_krx_snapshot_id": snapshot.id,
        "authority_by_market": {"KOSDAQ": "naver_last_completed", "KOSPI": "krx"},
        "fallback_reason_by_market": {"KOSDAQ": "market_not_in_canary", "KOSPI": None},
        "target_count_by_market": {"KOSDAQ": 1, "KOSPI": 2},
    }


def test_pending_reconciliation_run_forces_naver_fallback_before_canary_approval():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 20), status="completed"
    )
    session.add(snapshot)
    session.flush()
    session.add(
        KrxUniverseMembership(
            snapshot_id=snapshot.id, code="005930", name="삼성전자", market="KOSPI",
            security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
        )
    )
    instrument = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    session.add(instrument)
    session.flush()
    session.add_all(
        [
            ProviderSymbol(
                instrument_id=instrument.id, provider="naver", provider_symbol="005930", mapping_status="matched"
            ),
            UniverseReconciliationRun(
                krx_snapshot_id=snapshot.id, naver_snapshot_id=7, status="pending_review", report={"mapping_rate": 1.0}
            ),
        ]
    )
    session.commit()

    selection = select_price_targets(
        session,
        provider="naver",
        as_of_date=date(2026, 8, 20),
        naver_snapshot_id=7,
        naver_targets=[
            SymbolPayload(code="005930", name="삼성전자", market="KOSPI", symbol_type="stock"),
            SymbolPayload(code="999999", name="stale", market="KOSPI", symbol_type="stock"),
        ],
        settings=SimpleNamespace(
            universe_authority="krx", universe_canary_markets="KOSPI", universe_mapping_rate_threshold=0.995
        ),
    )

    assert selection.target_codes == frozenset({"005930", "999999"})
    assert selection.authority_by_market == {"KOSPI": "naver_last_completed"}
    assert selection.fallback_reason_by_market == {"KOSPI": "krx_reconciliation_not_approved"}


def test_canary_uses_last_approved_snapshot_while_current_reconciliation_is_pending():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    approved_snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    current_snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 20), status="completed"
    )
    session.add_all([approved_snapshot, current_snapshot])
    session.flush()
    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=approved_snapshot.id, code="005930", name="삼성전자", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            KrxUniverseMembership(
                snapshot_id=current_snapshot.id, code="100001", name="새 종목", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
        ]
    )
    instrument = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    session.add(instrument)
    session.flush()
    session.add_all(
        [
            ProviderSymbol(
                instrument_id=instrument.id, provider="naver", provider_symbol="005930", mapping_status="matched"
            ),
            UniverseReconciliationRun(
                krx_snapshot_id=approved_snapshot.id, naver_snapshot_id=7, status="approved", report={"mapping_rate": 1.0}
            ),
            UniverseReconciliationRun(
                krx_snapshot_id=current_snapshot.id, naver_snapshot_id=8, status="pending_review", report={"mapping_rate": 1.0}
            ),
        ]
    )
    session.commit()

    selection = select_price_targets(
        session,
        provider="naver",
        as_of_date=date(2026, 8, 20),
        naver_snapshot_id=8,
        krx_snapshot_status="completed",
        naver_targets=[
            SymbolPayload(code="005930", name="삼성전자", market="KOSPI", symbol_type="stock"),
            SymbolPayload(code="100001", name="새 종목", market="KOSPI", symbol_type="stock"),
        ],
        settings=SimpleNamespace(
            universe_authority="krx", universe_canary_markets="KOSPI", universe_mapping_rate_threshold=0.995
        ),
    )

    assert selection.target_codes == frozenset({"005930"})
    assert selection.lineage_by_code["005930"].krx_snapshot_id == approved_snapshot.id
    assert selection.authority_by_market == {"KOSPI": "krx"}


def test_partial_current_krx_snapshot_forces_naver_fallback_even_with_prior_mapping():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 20), status="completed"
    )
    session.add(snapshot)
    session.flush()
    session.add(
        KrxUniverseMembership(
            snapshot_id=snapshot.id, code="005930", name="삼성전자", market="KOSPI",
            security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
        )
    )
    instrument = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    session.add(instrument)
    session.flush()
    session.add_all(
        [
            ProviderSymbol(instrument_id=instrument.id, provider="naver", provider_symbol="005930", mapping_status="matched"),
            UniverseReconciliationRun(
                krx_snapshot_id=snapshot.id, naver_snapshot_id=7, status="pending_review", report={"mapping_rate": 1.0}
            ),
        ]
    )
    session.commit()

    selection = select_price_targets(
        session,
        provider="naver",
        as_of_date=date(2026, 8, 20),
        naver_snapshot_id=7,
        krx_snapshot_status="partial",
        naver_targets=[
            SymbolPayload(code="005930", name="삼성전자", market="KOSPI", symbol_type="stock"),
            SymbolPayload(code="999999", name="stale", market="KOSPI", symbol_type="stock"),
        ],
        settings=SimpleNamespace(
            universe_authority="krx", universe_canary_markets="KOSPI", universe_mapping_rate_threshold=0.995
        ),
    )

    assert selection.target_codes == frozenset({"005930", "999999"})
    assert selection.authority_by_market == {"KOSPI": "naver_last_completed"}
    assert selection.fallback_reason_by_market == {"KOSPI": "krx_snapshot_partial"}


def test_price_sync_resolver_materializes_same_job_snapshots_but_waits_for_reconciliation_approval(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    job = CrawlJob(job_type="daily_full")
    session.add(job)
    session.flush()
    krx_snapshot = KrxUniverseSnapshot(
        crawl_job_id=job.id, source="krx_open_api", scope="stock_membership",
        as_of_date=date(2026, 8, 20), status="completed",
    )
    naver_snapshot = SymbolUniverseSnapshot(
        job_id=job.id, provider="naver", market="ALL", status="completed",
    )
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=krx_snapshot.id, code="005930", name="삼성전자", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            Symbol(
                code="005930", name="삼성전자", market="KOSPI", symbol_type="stock",
                is_active=True, last_snapshot_id=naver_snapshot.id,
            ),
            Symbol(
                code="999999", name="stale", market="KOSPI", symbol_type="stock",
                is_active=True, last_snapshot_id=naver_snapshot.id,
            ),
        ]
    )
    session.commit()
    context = build_db_batch_context(session)
    context.job_id = job.id
    context.target_date = date(2026, 8, 20)
    monkeypatch.setattr(
        "app.services.batch.sync_prices.get_settings",
        lambda: SimpleNamespace(
            universe_authority="krx", universe_canary_markets="KOSPI", universe_mapping_rate_threshold=0.995
        ),
    )

    selection = _resolve_universe_price_selection(
        context, SimpleNamespace(provider_name="naver")
    )

    assert selection is not None
    assert selection.target_codes == frozenset({"005930", "999999"})
    assert selection.authority_by_market == {"KOSPI": "naver_last_completed"}
    assert selection.fallback_reason_by_market == {"KOSPI": "krx_reconciliation_not_approved"}
