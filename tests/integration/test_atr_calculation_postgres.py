"""ATR persistence exercises production fingerprints, Decimal storage and locks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from threading import Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_quality import PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun, IndicatorGeneration, IndicatorInputEvidence, IndicatorRunInput, IndicatorValue,
)
from app.services.indicators.atr_calculation_service import AtrCalculationError, AtrCalculationService
from app.services.indicators.contracts import canonical_json, prefix_hash
from tests.integration.test_volume_calculation_postgres import pg_engine
from tests.unit.test_atr_calculation_service import seed_atr_history, pure_result, run_values
from tests.unit.test_indicator_calculation_service import _observation, _policy


def test_atr_lifecycle_exact_decimal_results_hashes_and_immutable_ohlc_evidence(pg_engine):
    with Session(pg_engine) as session:
        instrument, symbol, mapping, dates = seed_atr_history(session, 32)
        observations = tuple(session.scalars(select(PriceObservation).order_by(PriceObservation.trade_date)))
        for index, observation in enumerate(observations):
            observation.high = Decimal('101') + Decimal(index % 3) / Decimal('10')
        session.flush()
        service = AtrCalculationService(session)
        expected = pure_result(service, instrument.id, dates)
        first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:13], policy=_policy())
        extended = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        assert extended.run_kind == 'incremental' and extended.generation_id == first.generation_id
        assert service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy()).reused
        values = run_values(session, first.run_id) + run_values(session, extended.run_id)
        assert tuple((value.value, value.status, value.reason_code, value.available_observations)
                     for value in values) == tuple((value.value, value.status.value, value.reason_code,
                                                   value.available_observations) for value in expected.values)
        assert session.get(IndicatorCalculationRun, extended.run_id).result_hash == sha256(
            canonical_json([value.material() for value in expected.values[13:]]).encode()).hexdigest()
        original_evidence = service.repository.completed_evidence(first.generation_id)
        previous = None
        for evidence, value in zip(original_evidence, values, strict=True):
            previous = prefix_hash(previous, evidence.evidence_key)
            assert previous == value.input_prefix_hash
        assert session.get(IndicatorCalculationRun, extended.run_id).input_hash == previous
        assert original_evidence[1].high == Decimal('101.1')
        revised = _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                               trade_date=dates[0], close='100', observed_at=datetime(2024, 5, 1, tzinfo=UTC))
        revised.high = Decimal('103')
        session.flush()
        rebuilt = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        assert rebuilt.run_kind == 'rebuild'
        assert session.get(IndicatorGeneration, first.generation_id).status == 'superseded'
        expected = pure_result(service, instrument.id, dates)
        assert session.get(IndicatorCalculationRun, rebuilt.run_id).result_hash == expected.result_hash
        assert original_evidence[0].high == Decimal('101')
        assert service.repository.completed_evidence(rebuilt.generation_id)[0].high == Decimal('103')
        assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 33
        session.commit()


def test_postgres_definition_rejection_keeps_failed_run_and_previous_current(pg_engine, monkeypatch):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_atr_history(session, 2)
        service = AtrCalculationService(session)
        first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:1], policy=_policy())
        def invalid_definition(**kwargs):
            run = kwargs['run']
            session.add(IndicatorValue(calculation_run_id=run.id, generation_id=run.generation_id,
                                       indicator_kind='volume_sma', period=50, trade_date=dates[-1],
                                       value=100, status='available', available_observations=50,
                                       input_prefix_hash='a' * 64))
            session.flush()
        monkeypatch.setattr(service.repository, 'complete_atr_run', invalid_definition)
        with pytest.raises(AtrCalculationError) as raised:
            service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        failed = session.get(IndicatorCalculationRun, raised.value.run_id)
        assert failed.status == 'failed' and failed.completed_at is None
        assert run_values(session, failed.id) == ()
        assert session.scalar(select(func.count()).select_from(IndicatorRunInput).where(
            IndicatorRunInput.calculation_run_id == failed.id)) == 0
        assert session.get(IndicatorGeneration, first.generation_id).status == 'current'
        session.commit()


def test_concurrent_atr_workers_complete_one_run(pg_engine):
    with Session(pg_engine) as session:
        instrument, _, _, dates = seed_atr_history(session, 2)
        instrument_id = instrument.id
        session.commit()
    selected = Event()
    contender_started = Event()
    release = Event()
    def worker(first):
        with Session(pg_engine) as session:
            service = AtrCalculationService(session)
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
