"""Volume runs exercise real server fingerprints, triggers and worker locks."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register all schema dependencies
from app.core.base import Base
from app.models.indicator import IndicatorCalculationRun, IndicatorInputEvidence, IndicatorValue
from app.services.indicators.volume_calculation_service import VolumeCalculationError, VolumeSmaCalculationService
from app.services.indicators.volume_sma import compute_volume_sma50
from tests.integration.test_common_indicator_migration import migration
from tests.unit.test_indicator_calculation_service import _observation, _policy
from tests.unit.test_volume_calculation_service import seed_history


@pytest.fixture
def pg_engine():
    database_url = os.getenv('TEST_DATABASE_URL', 'postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test')
    admin = create_engine(database_url)
    schema = 'volume_test_' + uuid4().hex
    try:
        connection = admin.connect()
    except SQLAlchemyError as exc:
        admin.dispose()
        pytest.skip(f'isolated PostgreSQL unavailable: {type(exc).__name__}')
    with connection:
        with connection.begin():
            connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
    engine = create_engine(database_url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=[
                table for table in Base.metadata.sorted_tables
                if not table.name.startswith('indicator_') and table.name != 'price_observation_identity_snapshots'
            ])
            for revision in ('w4a5b6c7d8e9', 'x5b6c7d8e9f0', 'y6c7d8e9f0a1'):
                migration(revision, connection).upgrade()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        admin.dispose()


def test_volume_lifecycle_uses_postgres_generated_evidence_and_exact_calculator_hash(pg_engine):
    with Session(pg_engine) as session:
        instrument, symbol, mapping, dates = seed_history(session, 52)
        service = VolumeSmaCalculationService(session)
        first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:49], policy=_policy())
        extended = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        assert extended.run_kind == 'incremental' and extended.generation_id == first.generation_id
        assert service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy()).reused
        _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                     trade_date=dates[0], close='110', observed_at=datetime(2024, 5, 1, tzinfo=UTC))
        rebuilt = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        expected = compute_volume_sma50(service.selector.select_rows(
            instrument_id=instrument.id, trade_dates=dates, policy=_policy()))
        assert rebuilt.run_kind == 'rebuild'
        assert session.get(IndicatorCalculationRun, rebuilt.run_id).result_hash == expected.result_hash
        values = tuple(session.scalars(select(IndicatorValue).where(
            IndicatorValue.calculation_run_id == rebuilt.run_id).order_by(IndicatorValue.trade_date)))
        assert tuple((value.value, value.status) for value in values) == tuple(
            (value.value, value.status.value) for value in expected.values)
        assert len(tuple(session.scalars(select(IndicatorInputEvidence)))) == 53
        session.commit()


def test_postgres_storage_error_rolls_back_output_and_persists_failed_attempt(pg_engine, monkeypatch):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_history(session, 2)
        service = VolumeSmaCalculationService(session)
        original = service.repository.complete_volume_run

        def violate_definition(**kwargs):
            result = kwargs['result']
            run = kwargs['run']
            # The real trigger rejects a value that differs from the Volume series.
            session.add(IndicatorValue(calculation_run_id=run.id, generation_id=run.generation_id,
                                       indicator_kind='ema', period=50, trade_date=result.values[0].trade_date,
                                       value=100, status='available', available_observations=1,
                                       input_prefix_hash='a' * 64))
            session.flush()
            original(**kwargs)

        monkeypatch.setattr(service.repository, 'complete_volume_run', violate_definition)
        with pytest.raises(VolumeCalculationError) as raised:
            service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        failed = session.get(IndicatorCalculationRun, raised.value.run_id)
        assert failed.status == 'failed' and failed.completed_at is None
        assert tuple(session.scalars(select(IndicatorValue))) == ()
        session.commit()


def test_concurrent_postgres_workers_produce_one_completed_run(pg_engine):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_history(session, 2)
        instrument_id = instrument.id
        session.commit()
    selected = Event()
    contender_started = Event()
    release = Event()

    def worker(first):
        with Session(pg_engine) as session:
            service = VolumeSmaCalculationService(session)
            if first:
                original = service.selector.select_rows

                def pause(**kwargs):
                    selected.set()
                    assert release.wait(10)
                    return original(**kwargs)

                service.selector.select_rows = pause
            else:
                contender_started.set()
            outcome = service.calculate(instrument_id=instrument_id, trade_dates=dates, policy=_policy())
            session.commit()
            return outcome

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker, True)
        try:
            assert selected.wait(10)
            contender = pool.submit(worker, False)
            assert contender_started.wait(10)
        finally:
            release.set()
        results = (first.result(timeout=10), contender.result(timeout=10))
    assert sorted(result.reused for result in results) == [False, True]
    assert results[0].generation_id == results[1].generation_id
    with Session(pg_engine) as session:
        runs = tuple(session.scalars(select(IndicatorCalculationRun)))
        assert len(runs) == 1 and runs[0].status == 'completed'
