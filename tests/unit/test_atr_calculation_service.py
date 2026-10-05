"""ATR persistence retains exact calculator output and selected OHLC evidence."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.indicator import (
    IndicatorCalculationRun, IndicatorGeneration, IndicatorInputEvidence,
    IndicatorInputPolicy, IndicatorRunInput, IndicatorSeries, IndicatorValue,
)
from app.services.indicators.atr import AtrInput, compute_atr14
from app.services.indicators.atr_calculation_service import AtrCalculationError, AtrCalculationService
from app.services.indicators.contracts import canonical_json, prefix_hash
from app.services.indicators.volume_calculation_service import VolumeSmaCalculationService
from tests.unit.test_indicator_calculation_service import session, _seed, _policy, _observation
from tests.unit.test_volume_calculation_service import sqlite_generated_keys


def seed_atr_history(session, count=30, missing_index=None):
    instrument, symbol, mapping = _seed(session)
    dates = tuple(date(2024, 1, 2) + timedelta(days=i) for i in range(count))
    for index, day in enumerate(dates):
        if index != missing_index:
            _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                         trade_date=day, close='100', observed_at=datetime(2024, 1, 1, tzinfo=UTC))
    return instrument, symbol, mapping, dates


def run_values(session, run_id):
    return tuple(session.scalars(select(IndicatorValue).where(
        IndicatorValue.calculation_run_id == run_id).order_by(IndicatorValue.trade_date)))


def pure_result(service, instrument_id, dates):
    rows = service.selector.select_rows(instrument_id=instrument_id, trade_dates=dates, policy=_policy())
    return compute_atr14(tuple(AtrInput(row.trade_date, row.high, row.low, row.close,
                                      row.effective_reason().value if row.effective_reason() else None)
                               for row in rows))


def test_persisted_atr_matches_calculator_and_ohlc_evidence_prefixes(session):
    instrument, _, _, dates = seed_atr_history(session, missing_index=14)
    service = AtrCalculationService(session)
    expected = pure_result(service, instrument.id, dates)
    outcome = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    run = session.get(IndicatorCalculationRun, outcome.run_id)
    assert outcome.run_kind == 'backfill' and not outcome.reused
    assert (run.status, run.result_hash, run.input_count, run.result_count, run.excluded_count) == (
        'completed', expected.result_hash, 30, 30, 1)
    assert session.get(IndicatorGeneration, outcome.generation_id).status == 'current'
    series = session.get(IndicatorSeries, outcome.series_id)
    assert (series.indicator_kind, series.input_field, series.periods, series.formula_version) == (
        'atr', 'high-low-close', '14', 'wilder-atr-14-v1')
    assert session.get(IndicatorInputPolicy, series.input_policy_id).version == 'validated-observation-ohlcv-v1'
    stored = run_values(session, run.id)
    assert tuple((value.value, value.status, value.reason_code, value.available_observations)
                 for value in stored) == tuple((value.value, value.status.value, value.reason_code,
                                               value.available_observations) for value in expected.values)
    assert all((value.indicator_kind, value.period) == ('atr', 14) for value in stored)
    refs = session.execute(select(IndicatorRunInput, IndicatorInputEvidence).join(
        IndicatorInputEvidence, IndicatorRunInput.evidence_id == IndicatorInputEvidence.id).where(
        IndicatorRunInput.calculation_run_id == run.id).order_by(IndicatorRunInput.ordinal)).all()
    previous = None
    for ordinal, ((ref, evidence), value) in enumerate(zip(refs, stored, strict=True)):
        previous = prefix_hash(previous, evidence.evidence_key)
        assert (ref.ordinal, ref.prefix_hash, value.input_prefix_hash) == (ordinal, previous, previous)
        if ordinal != 14:
            assert (evidence.high, evidence.low, evidence.close) == (Decimal('101'), Decimal('99'), Decimal('100'))
    assert run.input_hash == previous
    assert stored[13].value == Decimal('2') and stored[14].value is None and stored[-1].value == Decimal('2')


def test_reuse_incremental_and_rebuild_are_append_only(session):
    instrument, symbol, mapping, dates = seed_atr_history(session)
    service = AtrCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:13], policy=_policy())
    repeated = service.calculate(instrument_id=instrument.id, trade_dates=dates[:13], policy=_policy())
    assert repeated.reused and repeated.run_id == first.run_id
    assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1
    extension = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert extension.run_kind == 'incremental' and extension.generation_id == first.generation_id
    suffix = pure_result(service, instrument.id, dates).values[13:]
    assert session.get(IndicatorCalculationRun, extension.run_id).result_hash == sha256(
        canonical_json([value.material() for value in suffix]).encode()).hexdigest()
    assert run_values(session, extension.run_id)[0].value == Decimal('2')
    old_evidence = service.repository.completed_evidence(first.generation_id)
    old_run_hash = session.get(IndicatorCalculationRun, first.run_id).result_hash
    correction = _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                              trade_date=dates[0], close='100', observed_at=datetime(2024, 5, 1, tzinfo=UTC))
    correction.high = Decimal('102')
    session.flush()
    rebuilt = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert rebuilt.run_kind == 'rebuild' and rebuilt.generation_id != first.generation_id
    assert session.get(IndicatorGeneration, first.generation_id).status == 'superseded'
    assert old_evidence[0].high == Decimal('101')
    assert service.repository.completed_evidence(rebuilt.generation_id)[0].high == Decimal('102')
    assert session.get(IndicatorCalculationRun, first.run_id).result_hash == old_run_hash
    assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 31


@pytest.mark.parametrize('mode', ['initial', 'incremental', 'rebuild'])
def test_partial_storage_failure_preserves_previous_current_and_can_retry(session, monkeypatch, mode):
    instrument, _, _, dates = seed_atr_history(session, 3)
    service = AtrCalculationService(session)
    first = None if mode == 'initial' else service.calculate(
        instrument_id=instrument.id, trade_dates=dates[:2], policy=_policy())
    selected_dates = dates[:1] if mode == 'rebuild' else dates
    original = service.repository.complete_atr_run
    def fail_after_writing(**kwargs):
        original(**kwargs)
        raise RuntimeError('private provider detail')
    monkeypatch.setattr(service.repository, 'complete_atr_run', fail_after_writing)
    with pytest.raises(AtrCalculationError) as raised:
        service.calculate(instrument_id=instrument.id, trade_dates=selected_dates, policy=_policy())
    failed = session.get(IndicatorCalculationRun, raised.value.run_id)
    assert (failed.status, failed.completed_at, failed.input_hash, failed.result_hash) == ('failed', None, None, None)
    assert (failed.input_count, failed.result_count, failed.failure_reason) == (0, 0, 'RuntimeError')
    assert run_values(session, failed.id) == ()
    assert session.scalar(select(func.count()).select_from(IndicatorRunInput).where(
        IndicatorRunInput.calculation_run_id == failed.id)) == 0
    if first is not None:
        assert session.get(IndicatorGeneration, first.generation_id).status == 'current'
    assert session.get(IndicatorGeneration, failed.generation_id).status == ('current' if mode == 'incremental' else 'failed')
    session.commit()
    monkeypatch.setattr(service.repository, 'complete_atr_run', original)
    retry = service.calculate(instrument_id=instrument.id, trade_dates=selected_dates, policy=_policy())
    assert session.get(IndicatorCalculationRun, retry.run_id).status == 'completed'


def test_atr_and_volume_share_policy_and_ohlc_evidence_but_separate_series(session):
    instrument, _, _, dates = seed_atr_history(session, 2)
    volume = VolumeSmaCalculationService(session).calculate(
        instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    atr = AtrCalculationService(session).calculate(
        instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert atr.series_id != volume.series_id
    assert session.scalar(select(func.count()).select_from(IndicatorInputPolicy)) == 1
    assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 2


def test_running_attempt_blocks_second_worker(session):
    instrument, _, _, dates = seed_atr_history(session, 2)
    service = AtrCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:1], policy=_policy())
    generation = session.get(IndicatorGeneration, first.generation_id)
    service.repository.create_run(generation=generation, run_kind='incremental', input_cutoff=_policy().observation_cutoff)
    with pytest.raises(ValueError, match='running'):
        service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    with pytest.raises(IntegrityError), session.begin_nested():
        service.repository.create_run(generation=generation, run_kind='incremental', input_cutoff=_policy().observation_cutoff)


def test_empty_dates_rejected_without_series(session):
    with pytest.raises(ValueError, match='trade date'):
        AtrCalculationService(session).calculate(instrument_id=1, trade_dates=(), policy=_policy())
    assert session.scalar(select(func.count()).select_from(IndicatorSeries)) == 0


def test_completed_atr_run_is_immutable_and_forged_result_hash_is_rejected(session):
    from dataclasses import replace

    instrument, _, _, dates = seed_atr_history(session, 1)
    service = AtrCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    evidence = service.repository.completed_evidence(first.generation_id)
    completed = session.get(IndicatorCalculationRun, first.run_id)
    expected = pure_result(service, instrument.id, dates)
    prefixes = (prefix_hash(None, evidence[0].evidence_key),)
    with pytest.raises(ValueError, match='immutable'):
        service.repository.complete_atr_run(run=completed, evidence=evidence, prefix_hashes=prefixes, result=expected)
    generation = session.get(IndicatorGeneration, first.generation_id)
    run = service.repository.create_run(generation=generation, run_kind='incremental',
                                        input_cutoff=_policy().observation_cutoff)
    with pytest.raises(ValueError, match='result hash'):
        service.repository.complete_atr_run(run=run, evidence=evidence, prefix_hashes=prefixes,
                                            result=replace(expected, result_hash='a' * 64))
    assert run_values(session, run.id) == ()
    assert run.status == 'running'
