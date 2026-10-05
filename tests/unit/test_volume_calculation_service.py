"""Volume persistence preserves calculator output and immutable evidence lineage."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.models.data_quality import OhlcCorrection, ValidationCase, ValidationRun
from app.models.indicator import (
    IndicatorCalculationRun, IndicatorGeneration, IndicatorInputEvidence,
    IndicatorInputPolicy, IndicatorRunInput, IndicatorSeries, IndicatorValue,
)
from app.services.indicators.contracts import canonical_json, prefix_hash
from app.services.indicators.volume_calculation_service import (
    VolumeSmaCalculationService, VolumeCalculationError,
)
from app.services.indicators.volume_sma import compute_volume_sma50
from tests.unit.test_indicator_calculation_service import session, _seed, _policy, _observation


@pytest.fixture(autouse=True)
def sqlite_generated_keys():
    # SQLite lacks the production PostgreSQL BEFORE INSERT hash triggers.
    def generate(mapper, connection, target):
        field = 'fingerprint' if isinstance(target, IndicatorInputPolicy) else 'evidence_key'
        material = {column.name: getattr(target, column.name)
                    for column in target.__table__.columns
                    if column.name not in {'id', 'created_at', field}}
        setattr(target, field, sha256(canonical_json(material).encode()).hexdigest())
    for model in (IndicatorInputPolicy, IndicatorInputEvidence):
        event.listen(model, 'before_insert', generate)
    yield
    for model in (IndicatorInputPolicy, IndicatorInputEvidence):
        event.remove(model, 'before_insert', generate)


def seed_history(session, count=101):
    instrument, symbol, mapping = _seed(session)
    dates = tuple(date(2024, 1, 2) + timedelta(days=i) for i in range(count))
    for index, day in enumerate(dates):
        if index == 50:  # visible missing date resets the rolling window
            continue
        observation = _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                                   trade_date=day, close='100', observed_at=datetime(2024, 1, 1, tzinfo=UTC))
        observation.volume = 0 if index == 0 else index
    session.flush()
    return instrument, symbol, mapping, dates


def run_values(session, run_id):
    return tuple(session.scalars(select(IndicatorValue).where(
        IndicatorValue.calculation_run_id == run_id).order_by(IndicatorValue.trade_date)))


def test_persisted_volume_exactly_matches_pure_calculator_and_evidence_prefixes(session):
    instrument, _, _, dates = seed_history(session)
    service = VolumeSmaCalculationService(session)
    rows = service.selector.select_rows(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    expected = compute_volume_sma50(rows)
    outcome = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    run = session.get(IndicatorCalculationRun, outcome.run_id)
    assert run.status == 'completed' and run.result_hash == expected.result_hash
    assert run.input_count == run.result_count == 101 and run.excluded_count == 1
    assert session.get(IndicatorGeneration, outcome.generation_id).status == 'current'
    series = session.get(IndicatorSeries, outcome.series_id)
    assert (series.indicator_kind, series.formula_version) == ('volume_sma', 'volume-sma-v1')
    assert session.get(IndicatorInputPolicy, series.input_policy_id).version == 'validated-observation-ohlcv-v1'
    for stored, pure in zip(run_values(session, run.id), expected.values, strict=True):
        assert (stored.value, stored.status, stored.reason_code, stored.available_observations) == (
            pure.value, pure.status.value, pure.reason_code, pure.available_observations)
        assert (stored.indicator_kind, stored.period) == ('volume_sma', 50)
    refs = session.execute(select(IndicatorRunInput, IndicatorInputEvidence).join(
        IndicatorInputEvidence, IndicatorRunInput.evidence_id == IndicatorInputEvidence.id).where(
        IndicatorRunInput.calculation_run_id == run.id).order_by(IndicatorRunInput.ordinal)).all()
    previous = None
    for ordinal, ((ref, evidence), source, value) in enumerate(zip(refs, rows, run_values(session, run.id), strict=True)):
        previous = prefix_hash(previous, evidence.evidence_key)
        assert (ref.ordinal, ref.prefix_hash, value.input_prefix_hash) == (ordinal, previous, previous)
        assert evidence.price_observation_id == source.observation_id
        assert evidence.input_status == source.input_status.value
    assert run.input_hash == previous


def test_reuse_incremental_and_rebuild_preserve_and_share_evidence(session):
    instrument, symbol, mapping, dates = seed_history(session, 52)
    service = VolumeSmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:49], policy=_policy())
    repeated = service.calculate(instrument_id=instrument.id, trade_dates=dates[:49], policy=_policy())
    assert repeated.reused and repeated.run_id == first.run_id
    assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1
    extension = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert extension.run_kind == 'incremental' and extension.generation_id == first.generation_id
    assert session.get(IndicatorCalculationRun, extension.run_id).input_count == 3
    assert run_values(session, extension.run_id)[0].status == 'available'
    assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 52
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=dates[0], close='110', observed_at=datetime(2024, 5, 1, tzinfo=UTC))
    rebuilt = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert rebuilt.run_kind == 'rebuild' and rebuilt.generation_id != first.generation_id
    assert session.get(IndicatorGeneration, first.generation_id).status == 'superseded'
    assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 53
    assert len(run_values(session, rebuilt.run_id)) == 52


def test_calculation_failure_keeps_failed_attempt_and_previous_current(session, monkeypatch):
    instrument, _, _, dates = seed_history(session, 2)
    service = VolumeSmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    def fail(*args, **kwargs):
        raise RuntimeError('sensitive provider error must not be persisted')
    monkeypatch.setattr('app.services.indicators.volume_calculation_service.compute_volume_sma50', fail)
    with pytest.raises(VolumeCalculationError) as raised:
        service.calculate(instrument_id=instrument.id, trade_dates=dates[:1], policy=_policy())
    failed = session.get(IndicatorCalculationRun, raised.value.run_id)
    assert failed.status == 'failed' and failed.completed_at is None
    assert failed.failure_reason == 'RuntimeError'
    assert session.get(IndicatorGeneration, failed.generation_id).status == 'failed'
    assert session.get(IndicatorGeneration, first.generation_id).status == 'current'
    assert run_values(session, failed.id) == ()
    session.commit()
    assert session.get(IndicatorCalculationRun, failed.id).status == 'failed'


def test_running_attempt_blocks_duplicate_worker_and_database_insert(session):
    instrument, _, _, dates = seed_history(session, 2)
    service = VolumeSmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:1], policy=_policy())
    generation = session.get(IndicatorGeneration, first.generation_id)
    running = service.repository.create_run(generation=generation, run_kind='incremental', input_cutoff=_policy().observation_cutoff)
    with pytest.raises(ValueError, match='running'):
        service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    with pytest.raises(IntegrityError), session.begin_nested():
        service.repository.create_run(generation=generation, run_kind='incremental', input_cutoff=_policy().observation_cutoff)
    assert session.get(IndicatorCalculationRun, running.id).status == 'running'


def test_empty_history_rejected_without_artifacts(session):
    with pytest.raises(ValueError, match='trade date'):
        VolumeSmaCalculationService(session).calculate(instrument_id=1, trade_dates=(), policy=_policy())
    assert session.scalar(select(func.count()).select_from(IndicatorSeries)) == 0


def test_incremental_values_hash_and_prefixes_equal_the_full_calculator_suffix(session):
    instrument, _, _, dates = seed_history(session)
    service = VolumeSmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:49], policy=_policy())
    extension = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    expected = compute_volume_sma50(service.selector.select_rows(
        instrument_id=instrument.id, trade_dates=dates, policy=_policy()))
    suffix = expected.values[49:]
    stored = run_values(session, extension.run_id)
    assert tuple((row.value, row.status, row.reason_code, row.available_observations) for row in stored) == tuple(
        (value.value, value.status.value, value.reason_code, value.available_observations) for value in suffix)
    assert session.get(IndicatorCalculationRun, extension.run_id).result_hash == sha256(
        canonical_json([value.material() for value in suffix]).encode()).hexdigest()
    assert stored[0].value == Decimal('24.5')  # zero participates in day 50
    assert stored[1].status == 'data_unavailable'
    assert stored[-2].status == 'warming_up' and stored[-1].status == 'available'
    full = service.calculate(instrument_id=instrument.id, trade_dates=dates[:-1], policy=_policy())
    full_values = run_values(session, full.run_id)
    assert tuple(row.input_prefix_hash for row in run_values(session, first.run_id) + stored[:-1]) == tuple(
        row.input_prefix_hash for row in full_values)


@pytest.mark.parametrize('mode', ['initial', 'incremental', 'rebuild'])
def test_partial_storage_failure_keeps_failure_and_rolls_back_all_output(session, monkeypatch, mode):
    instrument, _, _, dates = seed_history(session, 3)
    service = VolumeSmaCalculationService(session)
    first = None
    if mode != 'initial':
        first = service.calculate(instrument_id=instrument.id, trade_dates=dates[:2], policy=_policy())
    selected_dates = dates[:1] if mode == 'rebuild' else dates
    original = service.repository.complete_volume_run

    def fail_after_writing(**kwargs):
        original(**kwargs)
        # This also verifies rollback of a completed status flushed inside the savepoint.
        raise RuntimeError('private detail')

    monkeypatch.setattr(service.repository, 'complete_volume_run', fail_after_writing)
    with pytest.raises(VolumeCalculationError) as raised:
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
    monkeypatch.setattr(service.repository, 'complete_volume_run', original)
    retried = service.calculate(instrument_id=instrument.id, trade_dates=selected_dates, policy=_policy())
    assert not retried.reused
    assert session.get(IndicatorCalculationRun, retried.run_id).status == 'completed'


def test_shared_policy_normalizes_versions_and_completed_run_is_immutable(session):
    instrument, _, _, dates = seed_history(session, 1)
    service = VolumeSmaCalculationService(session)
    base = _policy()
    duplicate_versions = type(base)(base.provider, base.adjustment_type,
                                   base.allowed_parser_versions * 2, base.observation_cutoff)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=duplicate_versions)
    again = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=base)
    assert again.reused and again.series_id == first.series_id
    assert session.scalar(select(func.count()).select_from(IndicatorInputPolicy)) == 1
    assert session.scalar(select(func.count()).select_from(IndicatorInputEvidence)) == 1
    with pytest.raises(ValueError, match='immutable'):
        service.repository.complete_volume_run(run=session.get(IndicatorCalculationRun, first.run_id),
                                               evidence=(), prefix_hashes=(), result=compute_volume_sma50(()))


def test_correction_and_validation_revision_copy_selection_evidence(session):
    instrument, symbol, _, dates = seed_history(session, 1)
    service = VolumeSmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    correction = OhlcCorrection(symbol_id=symbol.id, trade_date=dates[0], field_name='close',
                               original_value='100', corrected_value='105', reason_code='test', status='APPROVED')
    validation = ValidationRun(validator_version='test', mode='report_only')
    session.add_all((correction, validation))
    session.flush()
    case = ValidationCase(validation_run_id=validation.id, subject_type='daily_price', symbol_id=symbol.id,
                          trade_date=dates[0], rule_id='test', severity='warning', reason_code='test',
                          case_status='open', validator_version='test')
    session.add(case)
    session.flush()
    rebuilt = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert rebuilt.run_kind == 'rebuild' and rebuilt.generation_id != first.generation_id
    copied = service.repository.completed_evidence(rebuilt.generation_id)[0]
    assert copied.close == Decimal('105') and copied.volume == 0
    assert copied.correction_ids == [correction.id]
    assert copied.validation_evidence == [{'case_id': case.id, 'case_status': 'open', 'decision': None}]
    value = run_values(session, rebuilt.run_id)[0]
    assert (value.status, value.reason_code, value.value) == ('data_unavailable', 'open_validation_case', None)
    assert session.get(IndicatorCalculationRun, first.run_id).input_hash != session.get(
        IndicatorCalculationRun, rebuilt.run_id).input_hash


def test_evidence_lookup_and_insert_savepoints_are_bounded_for_whole_request(session):
    instrument, _, _, dates = seed_history(session)
    service = VolumeSmaCalculationService(session)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(session.bind, 'before_cursor_execute', capture)
    try:
        service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        lookup_count = sum(statement.startswith('SELECT') and 'FROM indicator_input_evidence' in statement
                           and 'JOIN' not in statement for statement in statements)
        assert lookup_count == 1
        assert sum(statement.startswith('SAVEPOINT') for statement in statements) <= 6
        statements.clear()
        outcome = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
        assert outcome.reused
        assert sum(statement.startswith('SELECT') and 'FROM indicator_input_evidence' in statement
                   and 'JOIN' not in statement for statement in statements) == 1
        assert not any(statement.startswith('INSERT INTO indicator_input_evidence') for statement in statements)
    finally:
        event.remove(session.bind, 'before_cursor_execute', capture)
