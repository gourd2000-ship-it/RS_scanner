"""Audit a finished ATR14 backfill and repair checkpoint-only failures.

The original apply report is the completion marker. This script never writes to
the database; --apply only replaces a verified checkpoint atomically.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.indicator import (
    IndicatorCalculationRun, IndicatorGeneration, IndicatorRunInput, IndicatorValue,
)
from app.services.indicators.atr import AtrValue
from app.services.indicators.contracts import EmaStatus, canonical_json
from scripts.atr14_operations import (
    _hash, _recover_completed_checkpoint, _save_checkpoint, begin_snapshot,
    load_manifest, request_from_manifest, trading_dates, validate_manifest, write_document,
)


def reconcile_checkpoint(
    session: Session, manifest: dict, checkpoint_path: Path, apply_report_path: Path,
    *, apply: bool = False,
) -> dict:
    """Prove every approved DB result before changing any checkpoint entry."""
    request = validate_manifest(manifest)
    checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
    if (checkpoint.get('manifest_hash') != manifest['manifest_hash']
            or checkpoint.get('checkpoint_hash') != _hash({
                key: value for key, value in checkpoint.items() if key != 'checkpoint_hash'
            })):
        raise ValueError('checkpoint hash or manifest mismatch')
    original_report = json.loads(apply_report_path.read_text(encoding='utf-8'))
    if (original_report.get('manifest_hash') != manifest['manifest_hash']
            or original_report.get('run_id') != checkpoint.get('run_id')
            or original_report.get('application_hash') != _hash({
                key: value for key, value in original_report.items() if key != 'application_hash'
            })):
        raise ValueError('completed apply report hash or run mismatch')
    targets = manifest['targets']
    target_ids = [target['instrument_id'] for target in targets]
    if ([item.get('instrument_id') for item in original_report.get('outcomes', [])] != target_ids
            or set(checkpoint['instruments']) != {str(instrument_id) for instrument_id in target_ids}):
        raise ValueError('apply report or checkpoint target coverage mismatch')

    repaired = dict(checkpoint)
    repaired['instruments'] = dict(checkpoint['instruments'])
    recovered_failures = []
    status_counts = Counter()
    dates = trading_dates(request)
    session.rollback()
    try:
        begin_snapshot(session, readonly=True)
        for target in targets:
            instrument_id = target['instrument_id']
            current = checkpoint['instruments'][str(instrument_id)]
            recovered = _recover_completed_checkpoint(session, target, request, dates)
            if recovered is None:
                raise ValueError(f'approved completed run missing for instrument {instrument_id}')
            run = session.get(IndicatorCalculationRun, recovered['run_id'])
            generation = session.get(IndicatorGeneration, recovered['generation_id'])
            if (run is None or generation is None or generation.status != 'current'
                    or run.status != 'completed' or run.result_hash != target['result_hash']
                    or run.input_count != target['expected_input_rows']
                    or run.result_count != target['expected_result_rows']
                    or run.excluded_count != target['data_unavailable_rows']):
                raise ValueError(f'completed run metadata or result hash mismatch for instrument {instrument_id}')
            input_count = session.scalar(select(func.count()).select_from(IndicatorRunInput)
                .where(IndicatorRunInput.calculation_run_id == run.id))
            last_prefix = session.scalar(select(IndicatorRunInput.prefix_hash)
                .where(IndicatorRunInput.calculation_run_id == run.id)
                .order_by(IndicatorRunInput.ordinal.desc()).limit(1))
            if input_count != target['expected_input_rows'] or last_prefix != run.input_hash:
                raise ValueError(f'persisted input mismatch for instrument {instrument_id}')
            values = session.execute(select(IndicatorValue).where(
                IndicatorValue.calculation_run_id == run.id,
                IndicatorValue.indicator_kind == 'atr', IndicatorValue.period == 14,
            ).order_by(IndicatorValue.trade_date)).scalars()
            materials = []
            counts = Counter()
            for value in values:
                counts[value.status] += 1
                materials.append(AtrValue(value.trade_date, value.value, EmaStatus(value.status),
                    value.reason_code, value.available_observations).material())
            digest = sha256(canonical_json(materials).encode('utf-8')).hexdigest()
            if (len(materials) != target['expected_result_rows'] or digest != run.result_hash
                    or any(counts[status] != target[f'{status}_rows'] for status in
                           ('available', 'warming_up', 'data_unavailable'))):
                raise ValueError(f'persisted result hash or status mismatch for instrument {instrument_id}')
            status_counts.update(counts)
            if current['status'] == 'failed':
                recovered_failures.append(instrument_id)
                repaired['instruments'][str(instrument_id)] = {
                    **recovered,
                    'reconciled_failure_reason': current.get('failure_reason'),
                    'reconciled_attempt': current.get('attempt'),
                }
            elif (current['status'] != 'completed'
                  or current.get('run_id') != run.id
                  or current.get('result_hash') != run.result_hash):
                raise ValueError(f'checkpoint completed run mismatch for instrument {instrument_id}')
    finally:
        session.rollback()
    normalized_counts = {status: status_counts[status] for status in
        ('available', 'warming_up', 'data_unavailable')}
    if (sum(status_counts.values()) != manifest['expected_result_rows']
            or normalized_counts != manifest['status_counts']):
        raise ValueError('manifest aggregate status counts mismatch')
    report = {
        'schema_version': 1, 'mode': 'atr14_checkpoint_reconciliation',
        'run_id': checkpoint['run_id'], 'manifest_hash': manifest['manifest_hash'],
        'original_application_hash': original_report['application_hash'],
        'verified_targets': len(targets), 'verified_input_rows': manifest['expected_input_rows'],
        'verified_result_rows': sum(status_counts.values()),
        'status_counts': normalized_counts, 'recovered_failures': recovered_failures,
        'checkpoint_repaired': apply,
    }
    report['reconciliation_hash'] = _hash(report)
    if apply:
        _save_checkpoint(checkpoint_path, repaired)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-hash', required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--completed-apply-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='repair checkpoint after full read-only audit')
    args = parser.parse_args(argv)
    if len({path.resolve() for path in (args.manifest, args.checkpoint,
            args.completed_apply_report, args.output)}) != 4:
        parser.error('manifest, checkpoint, apply report and output paths must differ')
    manifest = load_manifest(args.manifest, args.manifest_hash)
    lock_path = args.checkpoint.with_suffix(args.checkpoint.suffix + '.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            parser.error('checkpoint is in use by another operator process')
        with SessionLocal() as session:
            report = reconcile_checkpoint(session, manifest, args.checkpoint,
                args.completed_apply_report, apply=args.apply)
        write_document(args.output, report)
    print(f"ATR14 reconciliation: targets={report['verified_targets']} "
          f"values={report['verified_result_rows']} recovered={len(report['recovered_failures'])} "
          f"report={args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
