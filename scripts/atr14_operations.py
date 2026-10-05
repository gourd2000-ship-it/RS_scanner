"""File approval and instrument-sized transactions for ATR14 operators.

Only compact summaries survive each instrument calculation. Selection hashes
are portable review evidence, distinct from PostgreSQL's durable evidence keys.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.market_calendar import krx_market_day_status
from app.models.data_quality import PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun, IndicatorInputEvidence, IndicatorInputPolicy,
    IndicatorRunInput, IndicatorSeries, PriceObservationIdentitySnapshot,
)
from app.models.instrument import Instrument
from app.repositories.volume_indicator_repository import (
    COMMON_INPUT_POLICY_VERSION, CORRECTION_VERSION, SELECTOR_VERSION, VALIDATION_VERSION,
)
from app.services.indicators.contracts import (
    EmaInputRow, EmaSourcePolicy, IdentitySnapshot, ValidationCaseEvidence,
    canonical_json, prefix_hash,
)
from app.services.indicators.input_selector import EmaInputSelector
from app.services.indicators.atr_calculation_service import AtrCalculationError, AtrCalculationService
from app.services.indicators.atr import ATR_FORMULA_VERSION, AtrInput, compute_atr14


DEFINITION = {
    'indicator_kind': 'atr', 'input_field': 'high-low-close', 'period': 14,
    'formula_version': 'wilder-atr-14-v1', 'calculator_version': ATR_FORMULA_VERSION,
    'true_range': 'first_bar_high_minus_low_then_wilder_previous_close', 'unavailable_input': 'reset_window',
    'initial_window': 'requested_start_without_implicit_prehistory',
}
STORAGE_ESTIMATE = {'input_evidence_bytes': 1024, 'run_input_bytes': 160, 'value_bytes': 192,
                    'per_target_metadata_bytes': 4096,
                    'basis': 'conservative row and index estimate; excludes WAL/backups; assumes no evidence reuse'}


class AtrApprovalDrift(ValueError):
    """A safe, fixed reason code for an instrument which no longer matches approval."""


def _hash(material) -> str:
    return sha256(canonical_json(material).encode('utf-8')).hexdigest()


def canonical_document(material) -> str:
    return canonical_json(material) + '\n'


def write_document(path: Path, material) -> None:
    """Replace atomically after fsync; a torn checkpoint never appears valid."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(canonical_document(material))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class AtrStorageRequest:
    start: date
    end: date
    policy: EmaSourcePolicy
    instrument_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError('end must not be earlier than start')
        ids = tuple(sorted(set(self.instrument_ids)))
        if any(type(value) is not int or value <= 0 for value in ids):
            raise ValueError('instrument IDs must be positive integers')
        object.__setattr__(self, 'instrument_ids', ids)

    def material(self):
        return {'start': self.start, 'end': self.end, 'policy': self.policy.fingerprint_material(),
                'instrument_ids': self.instrument_ids,
                'universe_policy': 'listed KOSPI/KOSDAQ stocks with immutable matched policy evidence; exclude delisted/unknown'}


def _policy_material(policy):
    return {**policy.fingerprint_material(), 'storage_policy_version': COMMON_INPUT_POLICY_VERSION,
            'selector_version': SELECTOR_VERSION, 'validation_version': VALIDATION_VERSION,
            'correction_version': CORRECTION_VERSION}


def request_from_manifest(manifest) -> AtrStorageRequest:
    request = manifest['request']
    policy = request['policy']
    return AtrStorageRequest(date.fromisoformat(request['start']), date.fromisoformat(request['end']),
        EmaSourcePolicy(policy['provider'], policy['adjustment_type'], tuple(policy['allowed_parser_versions']),
                        datetime.fromisoformat(policy['observation_cutoff'].replace('Z', '+00:00')),
                        policy['version']), tuple(request['instrument_ids']))


def validate_manifest(manifest, expected_hash: str | None = None):
    if not isinstance(manifest, dict):
        raise ValueError('manifest must be a JSON object')
    digest = _hash({key: value for key, value in manifest.items() if key != 'manifest_hash'})
    if manifest.get('manifest_hash') != digest or (expected_hash is not None and digest != expected_hash):
        raise ValueError('manifest hash mismatch')
    try:
        request = request_from_manifest(manifest)
        if (manifest['schema_version'] != 1 or manifest['mode'] != 'read_only_storage_plan'
                or manifest['definition'] != DEFINITION
                or manifest['definition_fingerprint'] != _hash(DEFINITION)
                or manifest['policy_fingerprint'] != _hash(_policy_material(request.policy))
                or manifest['request'] != json.loads(canonical_json(request.material()))):
            raise ValueError('manifest definition or policy mismatch')
    except (KeyError, TypeError) as exc:
        raise ValueError('invalid manifest schema') from exc
    return request


def load_manifest(path: Path, expected_hash: str):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    validate_manifest(manifest, expected_hash)
    return manifest


def trading_dates(request):
    current = request.start
    dates = []
    while current <= request.end:
        if krx_market_day_status(current).is_open:
            dates.append(current)
        if current == request.end:
            break
        current += timedelta(days=1)
    if not dates:
        raise ValueError('range contains no KRX trading dates')
    return tuple(dates)


def _eligible_identity(instrument_id, request):
    policy = request.policy
    return select(PriceObservationIdentitySnapshot.id).join(PriceObservation,
        PriceObservation.id == PriceObservationIdentitySnapshot.price_observation_id).where(
        PriceObservationIdentitySnapshot.instrument_id == instrument_id,
        PriceObservationIdentitySnapshot.mapping_status == 'matched',
        PriceObservationIdentitySnapshot.provider == policy.provider,
        PriceObservationIdentitySnapshot.provider_symbol_mapping_id.is_not(None),
        PriceObservation.provider == policy.provider,
        PriceObservation.adjustment_type == policy.adjustment_type,
        PriceObservation.parser_version.in_(policy.allowed_parser_versions),
        PriceObservation.observed_at <= policy.observation_cutoff,
        PriceObservationIdentitySnapshot.resolved_at <= policy.observation_cutoff,
        or_(PriceObservationIdentitySnapshot.mapping_valid_from.is_(None),
            PriceObservationIdentitySnapshot.mapping_valid_from <= PriceObservation.trade_date),
        or_(PriceObservationIdentitySnapshot.mapping_valid_to.is_(None),
            PriceObservationIdentitySnapshot.mapping_valid_to > PriceObservation.trade_date),
        PriceObservation.trade_date >= request.start, PriceObservation.trade_date <= request.end,
    ).exists()


def _exclusion(session, instrument, request):
    if instrument.listing_status == 'delisted' or instrument.delisted_at is not None:
        return 'delisted_lifecycle'
    if instrument.listing_status != 'listed':
        return 'unconfirmed_lifecycle'
    if instrument.market not in ('KOSPI', 'KOSDAQ') or instrument.security_type != 'stock':
        return 'unsupported_market_or_security'
    if not session.scalar(select(_eligible_identity(instrument.id, request))):
        return 'policy_identity_unavailable'
    return None


def _universe(session, request):
    """Keyset pages avoid a market-wide ORM object/observation collection."""
    last_id = 0
    found = set()
    while True:
        query = select(Instrument).where(Instrument.id > last_id).order_by(Instrument.id).limit(100)
        if request.instrument_ids:
            query = query.where(Instrument.id.in_(request.instrument_ids))
        page = tuple(session.scalars(query))
        if not page:
            break
        for instrument in page:
            found.add(instrument.id)
            yield instrument.id, _exclusion(session, instrument, request)
        last_id = page[-1].id
    for instrument_id in sorted(set(request.instrument_ids) - found):
        yield instrument_id, 'instrument_not_found'


def _finite_material(value):
    # Invalid Decimal prices still have immutable selection evidence. Encode
    # their exact representation rather than dropping or repairing the fact.
    if isinstance(value, Decimal) and not value.is_finite():
        return {'nonfinite_decimal': str(value)}
    if isinstance(value, dict):
        return {key: _finite_material(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_material(item) for item in value]
    return value


def _target(session, instrument_id, dates, policy):
    rows = EmaInputSelector(session).select_rows(instrument_id=instrument_id, trade_dates=dates, policy=policy)
    sequence = _sequence_hash(rows)
    result = compute_atr14(_atr_inputs(rows))
    counts = Counter(value.status.value for value in result.values)
    return {'instrument_id': instrument_id, 'expected_input_rows': len(rows),
            'expected_result_rows': len(result.values), 'evidence_sequence_hash': sequence,
            'result_hash': result.result_hash,
            'first_available': next((value.trade_date.isoformat() for value in result.values
                                     if value.status.value == 'available'), None),
            **{f'{status}_rows': counts[status] for status in ('available', 'warming_up', 'data_unavailable')}}


def _sequence_hash(rows):
    sequence = None
    for row in rows:
        # Close-v3's fingerprint intentionally excludes high/low to preserve
        # legacy EMA hashes. ATR approval evidence must include all three OHLC
        # inputs, so a high/low revision invalidates its manifest as well.
        sequence = prefix_hash(sequence, _hash(_finite_material({
            **row.fingerprint_material(), "high": row.high, "low": row.low,
        })))
    return sequence


def _atr_inputs(rows):
    return tuple(AtrInput(
        row.trade_date, row.high, row.low, row.close,
        row.effective_reason().value if row.effective_reason() is not None else None,
    ) for row in rows)


def _utc_evidence(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _completed_rows_at_run(session, run, policy):
    """Rehydrate copied facts, including immutable unresolved identity snapshots.

    A generation may have later incremental runs. The candidate's run ID bounds
    its completed prefix; mutable observations/corrections are never consulted.
    """
    evidence = session.execute(select(IndicatorInputEvidence, PriceObservationIdentitySnapshot)
        .join(IndicatorRunInput, IndicatorRunInput.evidence_id == IndicatorInputEvidence.id)
        .join(IndicatorCalculationRun, IndicatorCalculationRun.id == IndicatorRunInput.calculation_run_id)
        .outerjoin(PriceObservationIdentitySnapshot,
            PriceObservationIdentitySnapshot.id == IndicatorInputEvidence.price_observation_identity_snapshot_id)
        .where(IndicatorCalculationRun.generation_id == run.generation_id,
               IndicatorCalculationRun.status == 'completed', IndicatorCalculationRun.id <= run.id)
        .order_by(IndicatorInputEvidence.trade_date))
    rows = []
    for copied, snapshot in evidence:
        identity = None if snapshot is None else IdentitySnapshot(
            snapshot.id, snapshot.instrument_id, snapshot.provider, snapshot.provider_symbol,
            snapshot.provider_symbol_mapping_id, snapshot.mapping_status, snapshot.mapping_valid_from,
            snapshot.mapping_valid_to, snapshot.resolver_version, _utc_evidence(snapshot.resolved_at))
        rows.append(EmaInputRow(
            trade_date=copied.trade_date, instrument_id=copied.instrument_id,
            symbol_id=copied.source_symbol_id, observation_id=copied.price_observation_id,
            identity=identity, provider=copied.provider, provider_symbol=copied.provider_symbol,
            adjustment_type=copied.adjustment_type, parser_version=copied.parser_version,
            high=copied.high, low=copied.low, close=copied.close, volume=copied.volume,
            observed_at=_utc_evidence(copied.observed_at),
            payload_hash=copied.payload_hash, correction_ids=tuple(copied.correction_ids),
            validation_cases=tuple(ValidationCaseEvidence(item['case_id'], item['case_status'], item.get('decision'))
                                   for item in copied.validation_evidence),
            input_status=copied.input_status, reason_code=copied.reason_code, source_policy=policy))
    return tuple(rows)


def _recover_completed_checkpoint(session, approved, request, dates):
    """Recover a lost file update only from the exact approved durable prefix."""
    policy = request.policy
    candidates = session.execute(select(IndicatorCalculationRun, IndicatorInputPolicy)
        .join(IndicatorSeries, IndicatorSeries.id == IndicatorCalculationRun.series_id)
        .join(IndicatorInputPolicy, IndicatorInputPolicy.id == IndicatorSeries.input_policy_id)
        .where(IndicatorSeries.instrument_id == approved['instrument_id'],
               IndicatorSeries.indicator_kind == DEFINITION['indicator_kind'],
               IndicatorSeries.input_field == DEFINITION['input_field'], IndicatorSeries.periods == '14',
               IndicatorSeries.formula_version == DEFINITION['formula_version'],
               IndicatorInputPolicy.version == COMMON_INPUT_POLICY_VERSION,
               IndicatorInputPolicy.provider == policy.provider,
               IndicatorInputPolicy.adjustment_type == policy.adjustment_type,
               IndicatorInputPolicy.observation_cutoff == policy.observation_cutoff,
               IndicatorInputPolicy.selector_version == SELECTOR_VERSION,
               IndicatorInputPolicy.validation_version == VALIDATION_VERSION,
               IndicatorInputPolicy.correction_version == CORRECTION_VERSION,
               IndicatorCalculationRun.status == 'completed',
               IndicatorCalculationRun.input_cutoff == policy.observation_cutoff,
               IndicatorCalculationRun.range_end == dates[-1])
        .order_by(IndicatorCalculationRun.id.desc()).execution_options(yield_per=100))
    for run, stored_policy in candidates:
        if stored_policy.allowed_parser_versions != sorted(set(policy.allowed_parser_versions)):
            continue
        rows = _completed_rows_at_run(session, run, policy)
        if (tuple(row.trade_date for row in rows) != dates
                or len(rows) != approved['expected_input_rows']
                or _sequence_hash(rows) != approved['evidence_sequence_hash']):
            continue
        result = compute_atr14(_atr_inputs(rows))
        if len(result.values) != approved['expected_result_rows'] or result.result_hash != approved['result_hash']:
            continue
        return {'instrument_id': approved['instrument_id'], 'status': 'completed',
                'run_id': run.id, 'series_id': run.series_id, 'generation_id': run.generation_id,
                'run_kind': run.run_kind, 'evidence_sequence_hash': approved['evidence_sequence_hash'],
                'input_hash': run.input_hash, 'result_hash': run.result_hash,
                'selected_result_hash': result.result_hash, 'recovered_from_database': True}
    return None


def build_manifest(session: Session, request: AtrStorageRequest):
    dates = trading_dates(request)
    targets, exclusions = [], []
    with session.no_autoflush:
        for instrument_id, reason in _universe(session, request):
            if reason:
                exclusions.append({'instrument_id': instrument_id, 'reason_code': reason})
            else:
                targets.append(_target(session, instrument_id, dates, request.policy))
    input_rows = sum(target['expected_input_rows'] for target in targets)
    result_rows = sum(target['expected_result_rows'] for target in targets)
    material = {'schema_version': 1, 'mode': 'read_only_storage_plan', 'definition': DEFINITION,
                'definition_fingerprint': _hash(DEFINITION),
                'policy_fingerprint': _hash(_policy_material(request.policy)),
                'request': request.material(), 'targets': targets, 'exclusions': exclusions,
                'expected_input_rows': input_rows, 'expected_result_rows': result_rows,
                'status_counts': {status: sum(target[f'{status}_rows'] for target in targets)
                                 for status in ('available', 'warming_up', 'data_unavailable')},
                'storage_estimate': STORAGE_ESTIMATE,
                'estimated_storage_bytes': input_rows * (1024 + 160) + result_rows * 192 + len(targets) * 4096}
    return json.loads(canonical_json({**material, 'manifest_hash': _hash(material)}))


def begin_snapshot(session, *, readonly):
    """CLI sessions own their transaction; PostgreSQL enforces read-only plans."""
    if session.bind.dialect.name == 'postgresql':
        session.connection(execution_options={'isolation_level': 'REPEATABLE READ',
                                              'postgresql_readonly': readonly})


def _save_checkpoint(path, checkpoint):
    checkpoint['checkpoint_hash'] = _hash({key: value for key, value in checkpoint.items()
                                          if key != 'checkpoint_hash'})
    write_document(path, checkpoint)


def apply_manifest(session: Session, manifest, *, checkpoint_path: Path, resume=False):
    """Run under a local checkpoint lock; the service additionally locks DB series."""
    validate_manifest(manifest)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.with_suffix(checkpoint_path.suffix + '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('checkpoint is in use by another operator process') from exc
        return _apply_manifest(session, manifest, checkpoint_path, resume)


def _apply_manifest(session, manifest, checkpoint_path, resume):
    request = validate_manifest(manifest)
    if session.new or session.dirty or session.deleted:
        raise ValueError('apply requires a session without unrelated pending writes')
    session.rollback()
    if checkpoint_path.exists():
        if not resume:
            raise ValueError('checkpoint exists; use --resume')
        checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        if (checkpoint.get('manifest_hash') != manifest['manifest_hash']
                or checkpoint.get('checkpoint_hash') != _hash({key: value for key, value in checkpoint.items()
                                                               if key != 'checkpoint_hash'})):
            raise ValueError('checkpoint manifest or hash mismatch')
    elif resume:
        raise ValueError('--resume requires an existing checkpoint')
    else:
        checkpoint = {'schema_version': 1, 'run_id': str(uuid4()), 'manifest_hash': manifest['manifest_hash'],
                      'instruments': {}}
    begin_snapshot(session, readonly=True)
    current = build_manifest(session, request)
    session.rollback()
    if ([row['instrument_id'] for row in current['targets']] != [row['instrument_id'] for row in manifest['targets']]
            or current['exclusions'] != manifest['exclusions']):
        raise ValueError('manifest target or lifecycle exclusions changed; create a new plan')
    if not resume and current != manifest:
        raise ValueError('manifest evidence changed; create a new plan before applying')
    _save_checkpoint(checkpoint_path, checkpoint)
    dates = trading_dates(request)
    report = {'schema_version': 1, 'mode': 'apply', 'run_id': checkpoint['run_id'],
              'manifest_hash': manifest['manifest_hash'], 'created': 0, 'reused': 0, 'rebuilt': 0,
              'failed': 0, 'outcomes': []}
    for approved in manifest['targets']:
        instrument_id = approved['instrument_id']
        prior = checkpoint['instruments'].get(str(instrument_id))
        last_completed = prior if prior and prior['status'] == 'completed' else (
            prior.get('last_completed') if prior else None)
        attempt = {'instrument_id': instrument_id, 'attempted_at': datetime.now(UTC).isoformat(),
                   'attempt': 1 + (prior.get('attempt', 0) if prior else 0)}
        try:
            begin_snapshot(session, readonly=False)
            instrument = session.get(Instrument, instrument_id)
            if instrument is None or _exclusion(session, instrument, request):
                raise AtrApprovalDrift('target_lifecycle_changed')
            selected = _target(session, instrument_id, dates, request.policy)
            changed = selected['evidence_sequence_hash'] != approved['evidence_sequence_hash']
            if resume and last_completed is None:
                last_completed = _recover_completed_checkpoint(session, approved, request, dates)
                if last_completed is not None:
                    checkpoint['instruments'][str(instrument_id)] = last_completed
                    _save_checkpoint(checkpoint_path, checkpoint)
                    attempt['recovered_completed_run_id'] = last_completed['run_id']
            attempt.update({'evidence_sequence_hash': selected['evidence_sequence_hash'],
                            'approved_evidence_sequence_hash': approved['evidence_sequence_hash'],
                            'selection_changed': changed,
                            'previous_evidence_sequence_hash': last_completed.get('evidence_sequence_hash') if last_completed else None})
            if changed and (not resume or last_completed is None):
                raise AtrApprovalDrift('manifest_evidence_changed_without_completed_checkpoint')
            outcome = AtrCalculationService(session).calculate(
                instrument_id=instrument_id, trade_dates=dates, policy=request.policy)
            persisted_run = session.get(IndicatorCalculationRun, outcome.run_id)
            attempt.update({'status': 'completed', 'run_id': outcome.run_id,
                            'series_id': outcome.series_id, 'generation_id': outcome.generation_id,
                            'run_kind': outcome.run_kind, 'reused': outcome.reused,
                            'input_hash': persisted_run.input_hash, 'result_hash': persisted_run.result_hash,
                            'selected_result_hash': selected['result_hash']})
            session.commit()
            report['reused' if outcome.reused else 'created'] += 1
            report['rebuilt'] += outcome.run_kind == 'rebuild'
        except AtrCalculationError as exc:
            session.commit()  # Preserve the service's failed run after its savepoint rollback.
            attempt.update({'status': 'failed', 'run_id': exc.run_id, 'failure_reason': 'AtrCalculationError'})
            report['failed'] += 1
        except AtrApprovalDrift as exc:
            session.rollback()
            attempt.update({'status': 'failed', 'failure_reason': str(exc)})
            report['failed'] += 1
        except Exception as exc:
            session.rollback()
            attempt.update({'status': 'failed', 'failure_reason': type(exc).__name__})
            report['failed'] += 1
        if attempt['status'] == 'failed' and last_completed:
            attempt['last_completed'] = last_completed
        checkpoint['instruments'][str(instrument_id)] = attempt
        checkpoint['last_instrument_id'] = instrument_id
        _save_checkpoint(checkpoint_path, checkpoint)
        report['outcomes'].append(attempt)
    report['application_hash'] = _hash(report)
    return report
