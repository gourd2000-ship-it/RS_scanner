from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.symbol import Symbol
from app.repositories.instrument_repository import InstrumentRepository


def build_repository() -> tuple[Session, InstrumentRepository]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, InstrumentRepository(session)


def test_canonical_instrument_preserves_krx_identity_and_provider_mapping():
    session, repository = build_repository()

    instrument = repository.create_instrument(
        krx_short_code="005930",
        isin="KR7005930003",
        name="삼성전자",
        market="KOSPI",
        security_type="stock",
        listed_at=date(1975, 6, 11),
        listing_status="listed",
    )
    mapping = repository.add_provider_symbol(
        instrument_id=instrument.id,
        provider="naver",
        provider_symbol="005930",
        mapping_status="matched",
        valid_from=date(2026, 8, 19),
        evidence_snapshot_id=7,
    )
    exclusion = repository.add_exclusion(
        instrument_id=instrument.id,
        scope="rs",
        reason_code="policy_excluded",
        valid_from=date(2026, 8, 19),
    )

    assert instrument.krx_short_code == "005930"
    assert mapping.instrument_id == instrument.id
    assert mapping.mapping_status == "matched"
    assert exclusion.reason_code == "policy_excluded"
    assert repository.get_by_krx_short_code("005930").id == instrument.id


def test_linking_a_legacy_symbol_keeps_its_code_and_price_history_identity():
    session, repository = build_repository()
    symbol = Symbol(code="005930", name="삼성전자", market="KOSPI")
    session.add(symbol)
    session.flush()
    instrument = repository.create_instrument(
        krx_short_code="005930",
        isin=None,
        name="삼성전자",
        market="KOSPI",
        security_type="stock",
        listing_status="listed",
    )

    linked = repository.link_legacy_symbol(symbol_id=symbol.id, instrument_id=instrument.id)

    assert linked.id == symbol.id
    assert linked.code == "005930"
    assert linked.legacy_code == "005930"
    assert linked.instrument_id == instrument.id
