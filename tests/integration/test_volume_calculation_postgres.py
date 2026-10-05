"""Volume runs exercise real server fingerprints, triggers and worker locks."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register all schema dependencies
from app.core.base import Base
from app.models.data_quality import PriceObservation
from app.models.indicator import IndicatorCalculationRun, IndicatorGeneration, IndicatorInputEvidence, IndicatorValue
from app.repositories.volume_indicator_repository import VolumeIndicatorRepository
from app.services.indicators.volume_calculation_service import VolumeCalculationError, VolumeSmaCalculationService
from app.services.indicators.volume_sma import compute_volume_sma50
from app.services.indicators.contracts import EmaInputStatus, InputReasonCode
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


@pytest.mark.parametrize('close', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_close_is_preserved_and_volume_result_and_failed_attempt_match(pg_engine, monkeypatch, close):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_history(session, 2)
        observation = session.scalar(select(PriceObservation).where(PriceObservation.trade_date == dates[0]))
        if close == 'NaN':
            observation.close = Decimal(close)
            session.flush()
        service = VolumeSmaCalculationService(session)
        if close != 'NaN':
            # Source Numeric(18,4) cannot hold Infinity. Exercise the selected
            # contract directly while the shared unconstrained Numeric preserves it.
            original = service.selector.select_rows

            def selected_nonfinite(**kwargs):
                return tuple(replace(row, close=Decimal(close), input_status=EmaInputStatus.INVALID,
                                     reason_code=InputReasonCode.INVALID_OHLCV)
                             if row.trade_date == dates[0] else row for row in original(**kwargs))

            monkeypatch.setattr(service.selector, 'select_rows', selected_nonfinite)
        rows = service.selector.select_rows(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        expected = compute_volume_sma50(rows)
        assert expected.values[0].reason_code == 'invalid_ohlcv'
        outcome = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        run = session.get(IndicatorCalculationRun, outcome.run_id)
        assert run.status == 'completed' and run.result_hash == expected.result_hash
        copied = service.repository.completed_evidence(outcome.generation_id)[0]
        assert str(copied.close) == close
        values = tuple(session.scalars(select(IndicatorValue).where(
            IndicatorValue.calculation_run_id == run.id).order_by(IndicatorValue.trade_date)))
        assert tuple((value.value, value.status, value.reason_code) for value in values) == tuple(
            (value.value, value.status.value, value.reason_code) for value in expected.values)
        assert service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy()).reused

        def fail(**kwargs):
            raise RuntimeError('private failure')

        monkeypatch.setattr(service.repository, 'complete_volume_run', fail)
        with pytest.raises(VolumeCalculationError) as raised:
            service.calculate(instrument_id=instrument.id, trade_dates=dates[:1], policy=_policy())
        failed = session.get(IndicatorCalculationRun, raised.value.run_id)
        assert failed.status == 'failed' and failed.failure_reason == 'RuntimeError'
        assert session.get(IndicatorGeneration, failed.generation_id).status == 'failed'
        assert session.get(IndicatorGeneration, outcome.generation_id).status == 'current'
        session.commit()
        assert session.get(IndicatorCalculationRun, failed.id).status == 'failed'


def test_concurrent_evidence_batches_recover_duplicate_keys_without_duplicate_facts(pg_engine):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_history(session, 3)
        service = VolumeSmaCalculationService(session)
        policy_id = service.repository.get_or_create_policy(_policy()).id
        rows = service.selector.select_rows(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        session.commit()
    barrier = Barrier(2)

    def worker():
        with Session(pg_engine) as session:
            repository = VolumeIndicatorRepository(session)
            original = repository._find_evidence
            first_lookup = True

            def simultaneously_missing(**kwargs):
                nonlocal first_lookup
                found = original(**kwargs)
                if first_lookup:
                    first_lookup = False
                    assert not found
                    barrier.wait(timeout=10)
                return found

            repository._find_evidence = simultaneously_missing
            evidence = repository.get_or_create_evidence_rows(input_policy_id=policy_id, rows=rows)
            ids = tuple(row.id for row in evidence)
            session.commit()
            return ids

    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = (pool.submit(worker), pool.submit(worker))
        results = tuple(worker.result(timeout=10) for worker in workers)
    assert results[0] == results[1]
    with Session(pg_engine) as session:
        assert len(tuple(session.scalars(select(IndicatorInputEvidence)))) == len(rows)
