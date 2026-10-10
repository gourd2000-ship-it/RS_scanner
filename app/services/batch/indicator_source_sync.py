"""Bounded Kiwoom observation append for the existing indicator universe.

Canonical Naver prices are not rewritten. Each new observation captures the
dated provider mapping at ingestion, and an overlapping price must match the
previous source before a new adjustment base can extend the history.
"""

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import logging

from sqlalchemy import func, select

from app.core.market_calendar import krx_market_day_status
from app.models.data_quality import PriceObservation
from app.models.indicator import IndicatorSeries, PriceObservationIdentitySnapshot
from app.models.instrument import ProviderSymbol
from app.models.listing_event import ListingEvent
from app.services.validation.market_data import validate_prices


logger = logging.getLogger(__name__)
FIELDS = ('open', 'high', 'low', 'close', 'volume')
PARSER = 'kiwoom-history-v1'


def _fingerprint(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _dates(start, end, closed_dates=''):
    while start <= end:
        if krx_market_day_status(start, configured_closed_dates=closed_dates).is_open:
            yield start
        start += timedelta(days=1)


def _same(left, right):
    return all(getattr(left, field) == getattr(right, field) for field in FIELDS)


def _mapping(session, target):
    rows = list(session.scalars(select(ProviderSymbol).where(
        ProviderSymbol.provider == 'kiwoom',
        ProviderSymbol.provider_symbol == target['code'],
        ProviderSymbol.mapping_status == 'matched',
        ProviderSymbol.valid_from <= date.fromisoformat(target['start']),
        (ProviderSymbol.valid_to.is_(None) | (ProviderSymbol.valid_to > date.fromisoformat(target['end']))),
    )))
    if len(rows) != 1 or rows[0].instrument_id != target['instrument_id']:
        return None
    return rows[0]


def plan_indicator_source(session, *, target_date, closed_dates=''):
    """Read only; scope is existing proven Kiwoom indicator series."""
    ids = list(session.scalars(select(IndicatorSeries.instrument_id).where(
        IndicatorSeries.source_provider == 'kiwoom', IndicatorSeries.adjustment_policy == '1',
    ).distinct().order_by(IndicatorSeries.instrument_id)))
    delisted = set(session.scalars(select(ListingEvent.instrument_id).where(
        ListingEvent.event_type == 'delisted', ListingEvent.effective_from <= target_date,
    )))
    # Group once: ORDER BY observation_id LIMIT 1 per instrument can make
    # PostgreSQL scan millions of unrelated identity rows backwards.
    latest_identity_refs = dict(session.execute(select(
        PriceObservationIdentitySnapshot.instrument_id,
        func.max(PriceObservationIdentitySnapshot.price_observation_id),
    ).where(
        PriceObservationIdentitySnapshot.instrument_id.in_(ids),
        PriceObservationIdentitySnapshot.mapping_status == 'matched',
        PriceObservationIdentitySnapshot.provider == 'kiwoom',
    ).group_by(PriceObservationIdentitySnapshot.instrument_id)).all())
    targets, excluded = [], []
    already_current = 0
    for instrument_id in ids:
        if instrument_id in delisted:
            excluded.append({'instrument_id': instrument_id, 'reason': 'delisted_lifecycle'})
            continue
        known_identity = session.scalar(select(PriceObservationIdentitySnapshot).where(
            PriceObservationIdentitySnapshot.price_observation_id == latest_identity_refs.get(instrument_id),
        )) if instrument_id in latest_identity_refs else None
        owner = session.get(PriceObservation, known_identity.price_observation_id) if known_identity else None
        observation = session.scalar(select(PriceObservation).where(
            PriceObservation.symbol_id == owner.symbol_id,
            PriceObservation.provider == 'kiwoom', PriceObservation.adjustment_type == '1',
            PriceObservation.parser_version == PARSER, PriceObservation.trade_date <= target_date,
        ).order_by(PriceObservation.trade_date.desc(), PriceObservation.id.desc()).limit(1)) if owner else None
        identity = session.scalar(select(PriceObservationIdentitySnapshot).where(
            PriceObservationIdentitySnapshot.price_observation_id == observation.id,
        )) if observation else None
        if identity is None or identity.instrument_id != instrument_id or identity.mapping_status != 'matched':
            excluded.append({'instrument_id': instrument_id, 'reason': 'source_identity_missing'})
            continue
        if observation.trade_date == target_date:
            already_current += 1
            continue
        target = {
            'instrument_id': instrument_id, 'symbol_id': observation.symbol_id,
            'code': identity.provider_symbol, 'baseline_observation_id': observation.id,
            'start': observation.trade_date.isoformat(), 'end': target_date.isoformat(),
            'expected_dates': [d.isoformat() for d in _dates(observation.trade_date + timedelta(days=1), target_date, closed_dates)],
        }
        mapping = _mapping(session, target)
        if mapping is None:
            excluded.append({'instrument_id': instrument_id, 'reason': 'identity_mapping_unavailable'})
            continue
        target['mapping_id'] = mapping.id
        target['mapping_valid_from'] = mapping.valid_from.isoformat()
        target['mapping_valid_to'] = mapping.valid_to.isoformat() if mapping.valid_to else None
        targets.append(target)
    document = {
        'version': 'daily-kiwoom-indicator-source-v1', 'target_date': target_date.isoformat(),
        'provider': 'kiwoom', 'adjustment_type': '1', 'parser_version': PARSER,
        'base_date': target_date.strftime('%Y%m%d'), 'targets': targets, 'excluded': excluded,
        'already_current': already_current, 'series_instruments': len(ids),
        'expected_new_rows': sum(len(t['expected_dates']) for t in targets),
        'request_budget': len(targets) * 2,
    }
    document['manifest_hash'] = _fingerprint(document)
    return document


def sync_indicator_source(session, plan, *, page_factory):
    """Append validated observations and identity atomically per instrument.

The manifest plus observation metadata is the resume record. Replaying the
same manifest checks existing values and never duplicates matching dates.
"""
    material = {k: v for k, v in plan.items() if k != 'manifest_hash'}
    if _fingerprint(material) != plan['manifest_hash']:
        raise ValueError('indicator source manifest hash mismatch')
    report = {'manifest_hash': plan['manifest_hash'], 'target_date': plan['target_date'],
              'observations_created': 0, 'processed': 0, 'failed': 0, 'failures': []}
    for target in plan['targets']:
        created = 0
        try:
            mapping = _mapping(session, target)
            if (mapping is None or mapping.id != target['mapping_id']
                or mapping.valid_from.isoformat() != target['mapping_valid_from']
                or (mapping.valid_to.isoformat() if mapping.valid_to else None) != target['mapping_valid_to']):
                raise ValueError('identity_mapping_changed')
            baseline = session.get(PriceObservation, target['baseline_observation_id'])
            if baseline is None or baseline.symbol_id != target['symbol_id']:
                raise ValueError('source_baseline_missing')
            existing = {row.trade_date: row for row in session.scalars(select(PriceObservation).where(
                PriceObservation.symbol_id == target['symbol_id'], PriceObservation.provider == 'kiwoom',
                PriceObservation.adjustment_type == '1', PriceObservation.parser_version == PARSER,
                PriceObservation.trade_date >= date.fromisoformat(target['start']),
                PriceObservation.trade_date <= date.fromisoformat(target['end']),
            ).order_by(PriceObservation.id))}
            received = {}
            for page in page_factory(target):
                for row in page.rows:
                    if date.fromisoformat(target['start']) <= row.trade_date <= date.fromisoformat(target['end']):
                        if row.trade_date in received:
                            raise ValueError('duplicate_source_date')
                        received[row.trade_date] = (row, page.source_payload_hash)
            overlap = received.get(baseline.trade_date)
            if overlap is None:
                raise ValueError('source_overlap_missing')
            if not _same(baseline, overlap[0]):
                raise ValueError('source_revision_requires_review')
            validate_prices([row for row, _ in received.values()])
            for day, (row, _) in received.items():
                if day in existing and not _same(existing[day], row):
                    raise ValueError('source_revision_requires_review')
            now = datetime.now(UTC)
            new_observations = []
            for day, (row, payload_hash) in sorted(received.items()):
                if day <= baseline.trade_date or day in existing:
                    continue
                observation = PriceObservation(
                    symbol_id=target['symbol_id'], trade_date=day,
                    **{field: getattr(row, field) for field in FIELDS}, change_rate=row.change_rate,
                    provider='kiwoom', adjustment_type='1', parser_version=PARSER,
                    payload_hash=payload_hash, observed_at=now,
                    observation_metadata={'source_sync_manifest_hash': plan['manifest_hash'],
                                          'base_date': plan['base_date'], 'canonical_disposition': 'observation_only'},
                )
                session.add(observation)
                new_observations.append(observation)
            session.flush()
            for observation in new_observations:
                session.add(PriceObservationIdentitySnapshot(
                    price_observation_id=observation.id, instrument_id=target['instrument_id'],
                    provider_symbol_mapping_id=mapping.id, provider='kiwoom', provider_symbol=target['code'],
                    mapping_status='matched', mapping_valid_from=mapping.valid_from, mapping_valid_to=mapping.valid_to,
                    resolver_version='dated-provider-mapping-v1', resolved_at=now,
                ))
            session.commit()
            created = len(new_observations)
            report['observations_created'] += created
            report['processed'] += 1
            missing = set(target['expected_dates']) - {d.isoformat() for d in set(received) | set(existing)}
            if missing:
                report['failed'] += 1
                report['failures'].append({'instrument_id': target['instrument_id'],
                    'reason': 'expected_source_dates_missing', 'missing_dates': sorted(missing)})
        except Exception as exc:
            session.rollback()
            known = {'identity_mapping_changed', 'source_baseline_missing', 'source_overlap_missing',
                     'source_revision_requires_review', 'duplicate_source_date'}
            reason = str(exc) if type(exc) is ValueError and str(exc) in known else type(exc).__name__
            report['failed'] += 1
            report['failures'].append({'instrument_id': target['instrument_id'], 'reason': reason})
        logger.info('indicator source instrument=%s created=%s processed=%s failed=%s total=%s',
                    target['instrument_id'], created, report['processed'], report['failed'], len(plan['targets']))
    return report
