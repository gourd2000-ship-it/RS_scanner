"""Tests for conservative KRX-to-canonical-universe materialization."""

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument, ProviderSymbol
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.services.canonical_universe import materialize_completed_universe


def test_materialization_links_only_exact_market_and_type_matches():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    krx_snapshot = KrxUniverseSnapshot(
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 20),
        status="completed",
    )
    naver_snapshot = SymbolUniverseSnapshot(
        provider="naver",
        market="ALL",
        status="completed",
    )
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=krx_snapshot.id,
                code="005930",
                isin=None,
                name="삼성전자",
                market="KOSPI",
                security_type="stock",
                listing_status="listed_observed",
                trading_status="unknown",
                raw_fields={},
            ),
            KrxUniverseMembership(
                snapshot_id=krx_snapshot.id,
                code="253150",
                isin=None,
                name="ARIRANG ETF",
                market="KOSPI",
                security_type="etf",
                listing_status="listed_observed",
                trading_status="unknown",
                raw_fields={},
            ),
        ]
    )
    exact_stock = Symbol(
        code="005930", name="삼성전자", market="KOSPI", symbol_type="stock",
        last_snapshot_id=naver_snapshot.id,
    )
    exact_etf = Symbol(
        code="253150", name="ARIRANG ETF", market="KOSPI", symbol_type="etf",
        last_snapshot_id=naver_snapshot.id,
    )
    name_only = Symbol(
        code="999999", name="삼성전자", market="KOSPI", symbol_type="stock",
        last_snapshot_id=naver_snapshot.id,
    )
    session.add_all([exact_stock, exact_etf, name_only])
    session.commit()

    result = materialize_completed_universe(
        session,
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        provider="naver",
    )

    assert result.instrument_count == 2
    assert result.exact_mapping_count == 2
    assert result.reconciliation_run_id is not None
    instruments = list(session.scalars(select(Instrument).order_by(Instrument.krx_short_code)))
    assert [(row.krx_short_code, row.listing_status) for row in instruments] == [
        ("005930", "listed"),
        ("253150", "listed"),
    ]
    assert {(row.instrument_id, row.provider_symbol) for row in session.scalars(select(ProviderSymbol))} == {
        (instruments[0].id, "005930"),
        (instruments[1].id, "253150"),
    }
    assert session.get(Symbol, exact_stock.id).instrument_id == instruments[0].id
    assert session.get(Symbol, exact_etf.id).instrument_id == instruments[1].id
    assert session.get(Symbol, name_only.id).instrument_id is None
