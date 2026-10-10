from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import PriceObservation
from app.models.indicator import PriceObservationIdentitySnapshot
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.indicator_repository import IndicatorRepository
from app.schemas.market_data import DailyPricePayload
from app.services.indicators.contracts import EmaSourcePolicy
from app.services.batch.context import build_db_batch_context
from app.services.batch.observation_inputs import eligible_instrument_ids
from app.services.batch.indicator_source_sync import plan_indicator_source, sync_indicator_source


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_source(session)
        yield session
    engine.dispose()


def seed_source(session):
    instrument = Instrument(krx_short_code='005930', name='sample', market='KOSPI', security_type='stock')
    symbol = Symbol(code='005930', name='sample', market='KOSPI')
    session.add_all([instrument, symbol])
    session.flush()
    mapping = ProviderSymbol(instrument_id=instrument.id, provider='kiwoom', provider_symbol='005930',
                             mapping_status='matched', valid_from=date(2020, 1, 1))
    session.add(mapping)
    session.flush()
    repo = IndicatorRepository(session)
    repo.create_series(instrument_id=instrument.id, policy=EmaSourcePolicy(
        provider='kiwoom', adjustment_type='1', allowed_parser_versions=('kiwoom-history-v1',),
        observation_cutoff=datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)))
    obs = PriceObservation(symbol_id=symbol.id, trade_date=date(2026, 10, 7),
        open=100, high=101, low=99, close=100, volume=1000, change_rate=0,
        provider='kiwoom', adjustment_type='1', parser_version='kiwoom-history-v1', payload_hash='a'*64)
    session.add(obs)
    session.flush()
    repo.create_identity_snapshot(price_observation_id=obs.id, instrument_id=instrument.id,
        provider_symbol_mapping_id=mapping.id, provider='kiwoom', provider_symbol='005930',
        mapping_status='matched', mapping_valid_from=mapping.valid_from, mapping_valid_to=None,
        resolver_version='test', resolved_at=datetime.now(UTC))
    session.commit()


def pages(target):
    def row(day):
        return DailyPricePayload(trade_date=day, open=Decimal(100), high=Decimal(101),
            low=Decimal(99), close=Decimal(100), volume=1000, change_rate=Decimal(0))
    return [SimpleNamespace(rows=(row(date(2026, 10, 7)), row(date(2026, 10, 8))), source_payload_hash='b'*64)]


def test_plan_does_not_write_and_apply_appends_identity_without_canonical_prices(session):
    plan = plan_indicator_source(session, target_date=date(2026, 10, 8))
    assert len(plan['targets']) == 1
    assert session.scalar(select(func.count()).select_from(PriceObservation)) == 1
    outcome = sync_indicator_source(session, plan, page_factory=pages)
    assert outcome['observations_created'] == 1
    assert outcome['failed'] == 0
    assert session.scalar(select(func.count()).select_from(PriceObservationIdentitySnapshot)) == 2
    from app.models.daily_price import DailyPrice
    assert session.scalar(select(func.count()).select_from(DailyPrice)) == 0
    assert sync_indicator_source(session, plan, page_factory=pages)['observations_created'] == 0


def test_changed_overlap_is_rejected_without_mixing_adjustment_bases(session):
    plan = plan_indicator_source(session, target_date=date(2026, 10, 8))
    def revised(target):
        result = pages(target)
        result[0].rows[0].close = Decimal(100.5)
        return result
    outcome = sync_indicator_source(session, plan, page_factory=revised)
    assert outcome['failed'] == 1
    assert outcome['failures'][0]['reason'] == 'source_revision_requires_review'
    assert session.scalar(select(func.count()).select_from(PriceObservation)) == 1


def test_missing_target_date_is_failure_not_up_to_date(session):
    plan = plan_indicator_source(session, target_date=date(2026, 10, 8))
    def missing(target):
        result = pages(target)
        result[0].rows = result[0].rows[:1]
        return result
    outcome = sync_indicator_source(session, plan, page_factory=missing)
    assert outcome['failed'] == 1
    assert outcome['failures'][0]['reason'] == 'expected_source_dates_missing'


def test_indicator_selection_requires_a_policy_observation_on_the_target_date(session):
    policy = EmaSourcePolicy(
        provider='kiwoom', adjustment_type='1', allowed_parser_versions=('kiwoom-history-v1',),
        observation_cutoff=datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC),
    )
    context = build_db_batch_context(session)

    assert eligible_instrument_ids(context, target_date=date(2026, 10, 8), policy=policy) == ()

    plan = plan_indicator_source(session, target_date=date(2026, 10, 8))
    assert sync_indicator_source(session, plan, page_factory=pages)['failed'] == 0

    assert eligible_instrument_ids(context, target_date=date(2026, 10, 8), policy=policy) == (1,)


def test_plan_rejects_expired_identity_mapping(session):
    mapping = session.scalar(select(ProviderSymbol))
    mapping.valid_to = date(2026, 10, 8)
    session.commit()
    plan = plan_indicator_source(session, target_date=date(2026, 10, 8))
    assert not plan['targets']
    assert plan['excluded'][0]['reason'] == 'identity_mapping_unavailable'
