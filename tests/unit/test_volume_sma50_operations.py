"""Operator approval, bounded plans and recoverable Volume MA50 writes."""
from datetime import UTC, date, datetime
import json
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import event, func, select

from app.models.indicator import IndicatorCalculationRun, IndicatorGeneration, IndicatorSeries
from scripts.volume_sma50_operations import (
    VolumeStorageRequest, apply_manifest, build_manifest, canonical_document,
    load_manifest, write_document,
)
from tests.unit.test_indicator_calculation_service import session, _seed, _observation, _policy
from tests.unit.test_volume_calculation_service import sqlite_generated_keys


def seeded_plan(session):
    instrument, symbol, mapping = _seed(session)
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=date(2024, 1, 2), close='100', observed_at=datetime(2024, 1, 2, tzinfo=UTC))
    session.commit()
    request = VolumeStorageRequest(date(2024, 1, 2), date(2024, 1, 3), _policy())
    return instrument, symbol, mapping, build_manifest(session, request)


def test_plan_contains_evidence_counts_policy_and_canonical_hash_without_write_sql(session):
    instrument, symbol, mapping = _seed(session)
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=date(2024, 1, 2), close='100', observed_at=datetime(2024, 1, 2, tzinfo=UTC))
    session.commit()
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', capture)
    try:
        request = VolumeStorageRequest(date(2024, 1, 2), date(2024, 1, 3), _policy())
        manifest = build_manifest(session, request)
        assert manifest == build_manifest(session, request)
    finally:
        event.remove(session.bind, 'before_cursor_execute', capture)
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE')) for sql in statements)
    assert manifest['expected_input_rows'] == manifest['expected_result_rows'] == 2
    assert manifest['targets'][0]['data_unavailable_rows'] == 1
    assert manifest['estimated_storage_bytes'] > 0
    assert len(manifest['definition_fingerprint']) == len(manifest['policy_fingerprint']) == 64
    assert json.loads(canonical_document(manifest)) == manifest


def test_delisted_unknown_identity_and_missing_requested_targets_are_explicit_exclusions(session):
    instrument, _, _, manifest = seeded_plan(session)
    instrument.listing_status = 'delisted'
    session.commit()
    request = VolumeStorageRequest(date(2024, 1, 2), date(2024, 1, 3), _policy(), (instrument.id, 999))
    result = build_manifest(session, request)
    assert result['targets'] == []
    assert {row['reason_code'] for row in result['exclusions']} == {'delisted_lifecycle', 'instrument_not_found'}


def test_manifest_file_hash_and_definition_are_verified_before_database_access(session, tmp_path):
    _, _, _, manifest = seeded_plan(session)
    path = tmp_path / 'plan.json'
    write_document(path, manifest)
    assert load_manifest(path, manifest['manifest_hash']) == manifest
    with pytest.raises(ValueError, match='hash'):
        load_manifest(path, '0' * 64)
    manifest['targets'][0]['instrument_id'] = 999
    write_document(path, manifest)
    with pytest.raises(ValueError, match='hash'):
        load_manifest(path, manifest['manifest_hash'])


def test_apply_reuses_same_evidence_and_checkpoint_can_resume(session, tmp_path):
    instrument, _, _, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    first = apply_manifest(session, manifest, checkpoint_path=checkpoint)
    assert first['created'] == 1 and first['failed'] == 0
    second = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert second['reused'] == 1 and second['created'] == 0
    assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1
    state = json.loads(checkpoint.read_text())
    assert state['manifest_hash'] == manifest['manifest_hash']
    assert state['instruments'][str(instrument.id)]['status'] == 'completed'


def test_initial_apply_rejects_selection_drift_and_resume_records_rebuild(session, tmp_path):
    instrument, symbol, mapping, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    first = apply_manifest(session, manifest, checkpoint_path=checkpoint)
    old_generation = first['outcomes'][0]['generation_id']
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=date(2024, 1, 2), close='101', observed_at=datetime(2024, 2, 1, tzinfo=UTC))
    session.commit()
    with pytest.raises(ValueError, match='evidence'):
        apply_manifest(session, manifest, checkpoint_path=tmp_path / 'fresh.json')
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['rebuilt'] == 1 and report['outcomes'][0]['selection_changed'] is True
    assert report['outcomes'][0]['generation_id'] != old_generation
    assert session.get(IndicatorGeneration, old_generation).status == 'superseded'


def test_failed_attempt_is_committed_checkpointed_and_resumable(session, tmp_path, monkeypatch):
    _, _, _, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    import app.services.indicators.volume_calculation_service as calculation
    original = calculation.compute_volume_sma50
    def fail(*args):
        raise RuntimeError('must not leak private details')
    monkeypatch.setattr(calculation, 'compute_volume_sma50', fail)
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint)
    assert report['failed'] == 1
    run = session.scalar(select(IndicatorCalculationRun))
    assert run.status == 'failed'
    assert 'private' not in checkpoint.read_text()
    monkeypatch.setattr(calculation, 'compute_volume_sma50', original)
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['created'] == 1 and report['failed'] == 0


def test_target_lifecycle_drift_aborts_before_any_write(session, tmp_path):
    instrument, _, _, manifest = seeded_plan(session)
    instrument.listing_status = 'delisted'
    session.commit()
    with pytest.raises(ValueError, match='target'):
        apply_manifest(session, manifest, checkpoint_path=tmp_path / 'checkpoint.json')
    assert session.scalar(select(func.count()).select_from(IndicatorSeries)) == 0


def test_failed_rebuild_can_resume_using_the_last_completed_checkpoint(session, tmp_path, monkeypatch):
    instrument, symbol, mapping, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    apply_manifest(session, manifest, checkpoint_path=checkpoint)
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=date(2024, 1, 2), close='101', observed_at=datetime(2024, 2, 1, tzinfo=UTC))
    session.commit()
    import app.services.indicators.volume_calculation_service as calculation
    original = calculation.compute_volume_sma50
    def fail(*args):
        raise RuntimeError('private')
    monkeypatch.setattr(calculation, 'compute_volume_sma50', fail)
    assert apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)['failed'] == 1
    monkeypatch.setattr(calculation, 'compute_volume_sma50', original)
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['failed'] == 0 and report['rebuilt'] == 1


def test_cli_requires_apply_and_valid_manifest_before_opening_database(tmp_path, monkeypatch):
    from scripts import backfill_volume_sma50 as cli
    def forbidden():
        raise AssertionError('must not open database')
    monkeypatch.setattr(cli, 'SessionLocal', forbidden)
    args = cli.build_parser().parse_args(['--manifest', str(tmp_path / 'missing.json'),
        '--manifest-hash', '0' * 64, '--checkpoint', str(tmp_path / 'checkpoint.json')])
    with pytest.raises(ValueError, match='--apply'):
        cli.execute(args)
    args.apply = True
    (tmp_path / 'missing.json').write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        cli.execute(args)


def test_committed_instrument_recovers_if_checkpoint_write_is_interrupted(session, tmp_path, monkeypatch):
    from scripts import volume_sma50_operations as operations
    _, _, _, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    original = operations._save_checkpoint
    def interrupted(path, state):
        if state['instruments']:
            raise OSError('simulated local disk interruption')
        original(path, state)
    monkeypatch.setattr(operations, '_save_checkpoint', interrupted)
    with pytest.raises(OSError):
        apply_manifest(session, manifest, checkpoint_path=checkpoint)
    monkeypatch.setattr(operations, '_save_checkpoint', original)
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['reused'] == 1
    assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1


@pytest.mark.parametrize('initial_run', ['backfill', 'incremental'])
def test_committed_run_recovers_before_rebuilding_revision_after_checkpoint_interruption(session, tmp_path, monkeypatch, initial_run):
    from scripts import volume_sma50_operations as operations
    from app.services.indicators.volume_calculation_service import VolumeSmaCalculationService
    instrument, symbol, mapping, manifest = seeded_plan(session)
    if initial_run == 'incremental':
        VolumeSmaCalculationService(session).calculate(
            instrument_id=instrument.id, trade_dates=(date(2024, 1, 2),), policy=_policy())
        session.commit()
    checkpoint = tmp_path / 'checkpoint.json'
    original = operations._save_checkpoint
    def interrupted(path, state):
        if state['instruments']:
            raise OSError('simulated checkpoint interruption after DB commit')
        original(path, state)
    monkeypatch.setattr(operations, '_save_checkpoint', interrupted)
    with pytest.raises(OSError):
        apply_manifest(session, manifest, checkpoint_path=checkpoint)
    committed = session.scalar(select(IndicatorCalculationRun).order_by(IndicatorCalculationRun.id.desc()))
    assert committed.status == 'completed' and committed.run_kind == initial_run
    assert json.loads(checkpoint.read_text())['instruments'] == {}
    _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                 trade_date=date(2024, 1, 2), close='101', observed_at=datetime(2024, 2, 1, tzinfo=UTC))
    session.commit()
    monkeypatch.setattr(operations, '_save_checkpoint', original)
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['failed'] == 0 and report['rebuilt'] == 1
    outcome = report['outcomes'][0]
    assert outcome['recovered_completed_run_id'] == committed.id
    assert outcome['previous_evidence_sequence_hash'] == manifest['targets'][0]['evidence_sequence_hash']
    assert outcome['selection_changed'] is True
    assert outcome['generation_id'] != committed.generation_id
    assert session.get(IndicatorGeneration, committed.generation_id).status == 'superseded'
    assert json.loads(checkpoint.read_text())['instruments'][str(instrument.id)]['status'] == 'completed'


@pytest.mark.parametrize('mismatch', ['policy', 'range', 'evidence'])
def test_database_recovery_rejects_completed_history_outside_approved_manifest(session, tmp_path, mismatch):
    from dataclasses import replace
    from scripts import volume_sma50_operations as operations
    from app.services.indicators.volume_calculation_service import VolumeSmaCalculationService
    instrument, symbol, mapping, manifest = seeded_plan(session)
    checkpoint = tmp_path / 'checkpoint.json'
    operations._save_checkpoint(checkpoint, {'schema_version': 1, 'run_id': 'interrupted',
        'manifest_hash': manifest['manifest_hash'], 'instruments': {}})
    def revise():
        _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                     trade_date=date(2024, 1, 2), close='101', observed_at=datetime(2024, 2, 1, tzinfo=UTC))
        session.commit()
    if mismatch == 'evidence':
        revise()
    VolumeSmaCalculationService(session).calculate(instrument_id=instrument.id,
        trade_dates=(date(2024, 1, 2),) if mismatch == 'range' else (date(2024, 1, 2), date(2024, 1, 3)),
        policy=replace(_policy(), observation_cutoff=datetime(2026, 1, 1, tzinfo=UTC)) if mismatch == 'policy' else _policy())
    session.commit()
    if mismatch != 'evidence':
        revise()
    report = apply_manifest(session, manifest, checkpoint_path=checkpoint, resume=True)
    assert report['failed'] == 1 and report['created'] == 0
    assert report['outcomes'][0]['failure_reason'] == 'manifest_evidence_changed_without_completed_checkpoint'
    assert 'recovered_completed_run_id' not in report['outcomes'][0]
    assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1


@pytest.mark.parametrize('script', ['plan_volume_sma50_storage.py', 'backfill_volume_sma50.py'])
def test_operator_scripts_run_directly_from_checkout(script):
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run([sys.executable, str(root / 'scripts' / script), '--help'],
                               cwd=root, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert '--output' in completed.stdout
