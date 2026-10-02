from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.repositories.instrument_repository import InstrumentRepository
from app.services.universe_target_builder import _current_mappings, build_price_targets


def test_target_builder_uses_last_completed_snapshot_and_preserves_exclusion_reasons():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    completed = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    partial = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 20), status="partial"
    )
    session.add_all([completed, partial])
    session.flush()
    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=completed.id, code="005930", name="삼성전자", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            KrxUniverseMembership(
                snapshot_id=completed.id, code="111111", name="제외 종목", market="KOSDAQ",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            KrxUniverseMembership(
                snapshot_id=completed.id, code="222222", name="매핑 없음", market="KOSDAQ",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
        ]
    )
    repository = InstrumentRepository(session)
    samsung = repository.create_instrument(
        krx_short_code="005930", isin=None, name="삼성전자", market="KOSPI", security_type="stock", listing_status="listed"
    )
    excluded = repository.create_instrument(
        krx_short_code="111111", isin=None, name="제외 종목", market="KOSDAQ", security_type="stock", listing_status="listed"
    )
    repository.create_instrument(
        krx_short_code="222222", isin=None, name="매핑 없음", market="KOSDAQ", security_type="stock", listing_status="listed"
    )
    repository.add_provider_symbol(
        instrument_id=samsung.id, provider="naver", provider_symbol="005930", mapping_status="matched"
    )
    repository.add_provider_symbol(
        instrument_id=excluded.id, provider="naver", provider_symbol="111111", mapping_status="matched"
    )
    repository.add_exclusion(
        instrument_id=excluded.id, scope="price", reason_code="policy_excluded"
    )
    session.commit()

    result = build_price_targets(session, provider="naver", as_of_date=date(2026, 8, 20))

    assert result.krx_snapshot_id == completed.id
    by_code = {target.krx_code: target for target in result.targets}
    assert by_code["005930"].price_eligibility == "eligible"
    assert by_code["005930"].provider_symbol == "005930"
    assert by_code["111111"].price_eligibility == "excluded"
    assert by_code["111111"].reason_code == "policy_excluded"
    assert by_code["222222"].price_eligibility == "review_required"
    assert by_code["222222"].reason_code == "provider_symbol_unavailable"


def test_target_builder_uses_half_open_provider_mapping_intervals_for_reused_codes():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2020, 1, 1), status="completed"
    )
    session.add(snapshot)
    session.flush()
    session.add(
        KrxUniverseMembership(
            snapshot_id=snapshot.id, code="123456", name="신 법인", market="KOSPI", security_type="stock",
            listing_status="listed_observed", trading_status="unknown", raw_fields={},
        )
    )
    repository = InstrumentRepository(session)
    former = repository.create_instrument(
        krx_short_code="123456", isin="KR7000000001", name="구 법인", market="KOSDAQ",
        security_type="stock", listing_status="delisted", delisted_at=date(2011, 1, 1),
    )
    successor = repository.create_instrument(
        krx_short_code="123456", isin="KR7000000002", name="신 법인", market="KOSPI",
        security_type="stock", listing_status="listed", listed_at=date(2020, 1, 1),
    )
    repository.add_provider_symbol(
        instrument_id=former.id, provider="naver", provider_symbol="123456", mapping_status="matched",
        valid_from=date(2000, 1, 1), valid_to=date(2011, 1, 1),
    )
    repository.add_provider_symbol(
        instrument_id=successor.id, provider="naver", provider_symbol="123456", mapping_status="matched",
        valid_from=date(2020, 1, 1),
    )
    session.commit()

    result = build_price_targets(session, provider="naver", as_of_date=date(2020, 1, 1))

    assert result.targets[0].instrument_id == successor.id
    assert result.targets[0].provider_symbol == "123456"
    assert _current_mappings(
        session, provider="naver", instrument_ids=[former.id], as_of_date=date(2011, 1, 1)
    ) == {}
