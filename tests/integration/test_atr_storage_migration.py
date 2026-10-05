"""ATR definition and OHLC evidence extend existing immutable history."""
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from tests.integration.test_common_indicator_migration import (
    COMPLETE, connection, evidence, migration, policy, ref, rejected, run, series, value,
)

REVISION = 'z7d8e9f0a1b2'


def atr_series(conn, pid):
    return conn.execute(text('''INSERT INTO indicator_series
        (instrument_id, indicator_kind, input_field, periods, input_policy_version, formula_version,
         source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff, input_policy_id)
        SELECT 1, 'atr', 'high-low-close', '14', version, 'wilder-atr-14-v1', provider,
               adjustment_type, allowed_parser_versions, observation_cutoff, id
        FROM indicator_input_policies WHERE id=:pid RETURNING id'''), dict(pid=pid)).scalar_one()


def upgrade(conn):
    migration('y6c7d8e9f0a1', conn).upgrade()
    module = migration(REVISION, conn)
    module.upgrade()
    return module


def test_atr_empty_upgrade_downgrade_restores_previous_definitions(connection):
    module = upgrade(connection)
    assert {'high', 'low'} <= {col['name'] for col in inspect(connection).get_columns('indicator_input_evidence')}
    module.downgrade()
    module.upgrade()
    module.downgrade()
    assert not {'high', 'low'} & {col['name'] for col in inspect(connection).get_columns('indicator_input_evidence')}
    pid = policy(connection)
    with connection.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            atr_series(connection, pid)
        savepoint.rollback()
    rid, gid = run(connection, series(connection, pid))
    ref(connection, rid, evidence(connection, pid))
    value(connection, rid, gid)
    connection.execute(text(COMPLETE), dict(rid=rid))


def test_atr_upgrade_preserves_completed_ema_volume_and_legacy_evidence(connection):
    c = connection
    legacy_sid = c.execute(text("""INSERT INTO indicator_series
        (instrument_id, source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff)
        VALUES (1, 'kiwoom', '1', '["v1"]', '2024-02-01') RETURNING id""")).scalar_one()
    legacy_rid, legacy_gid = run(c, legacy_sid)
    c.execute(text("""INSERT INTO indicator_input_snapshots
        (calculation_run_id, generation_id, trade_date, instrument_id, provider, provider_symbol,
         correction_ids, validation_evidence, input_status, row_hash, prefix_hash)
        VALUES (:rid, :gid, '2024-01-02', 1, 'kiwoom', 'TEST', '[]', '[]', 'eligible', 'row', 'prefix')"""),
        dict(rid=legacy_rid, gid=legacy_gid))
    for period in (5, 20, 50, 200):
        c.execute(text("""INSERT INTO indicator_values
            (calculation_run_id, generation_id, period, trade_date, value, status, reason_code,
             available_observations, input_prefix_hash)
            VALUES (:rid, :gid, :period, '2024-01-02', 100, 'warming_up', 'warming_up', 1, 'prefix')"""),
            dict(rid=legacy_rid, gid=legacy_gid, period=period))
    c.execute(text(COMPLETE), dict(rid=legacy_rid))
    migration('y6c7d8e9f0a1', c).upgrade()
    pid = policy(c)
    eid = evidence(c, pid, close='100', volume=10)
    for kind in ('ema', 'volume_sma'):
        rid, gid = run(c, series(c, pid, kind=kind))
        ref(c, rid, eid)
        for period in ((5, 20, 50, 200) if kind == 'ema' else (50,)):
            value(c, rid, gid, period=period, kind=kind, number=100 if kind == 'ema' else None)
        c.execute(text(COMPLETE), dict(rid=rid))
    tables = ('indicator_series', 'indicator_generations', 'indicator_calculation_runs',
              'indicator_input_evidence', 'indicator_run_inputs', 'indicator_values', 'indicator_input_snapshots',
              'indicator_input_policies')
    before = {table: list(c.execute(text(f'SELECT * FROM {table} ORDER BY id')).mappings()) for table in tables}
    module = migration(REVISION, c)
    module.upgrade()
    for table in tables:
        columns = ','.join(before[table][0])
        assert list(c.execute(text(f'SELECT {columns} FROM {table} ORDER BY id')).mappings()) == before[table]
    assert c.execute(text('SELECT high,low FROM indicator_input_evidence WHERE id=:id'), dict(id=eid)).one() == (None, None)
    rejected(c, 'UPDATE indicator_input_evidence SET high=101 WHERE id=:id', dict(id=eid))
    rejected(c, 'DELETE FROM indicator_input_snapshots WHERE calculation_run_id=:rid', dict(rid=legacy_rid))
    rejected(c, 'UPDATE indicator_values SET value=200 WHERE calculation_run_id=:rid', dict(rid=rid))
    rejected(c, 'DELETE FROM indicator_run_inputs WHERE calculation_run_id=:rid', dict(rid=rid))
    with pytest.raises(RuntimeError, match='cannot downgrade'):
        module.downgrade()
    assert {'high', 'low'} <= {col['name'] for col in inspect(c).get_columns('indicator_input_evidence')}


def ohlc_evidence(c, pid, high, low):
    return c.execute(text('''INSERT INTO indicator_input_evidence
        (input_policy_id,instrument_id,trade_date,provider,provider_symbol,high,low,close,volume,
         correction_ids,validation_evidence,input_status,reason_code)
        VALUES (:pid,1,'2024-01-02','kiwoom','TEST',:high,:low,100,0,'[]','[]','eligible',NULL)
        RETURNING id'''), dict(pid=pid, high=high, low=low)).scalar_one()


def test_fresh_evidence_hash_includes_high_low_and_normalizes_numeric_scale(connection):
    c = connection
    module = upgrade(c)
    pid = policy(c)
    eid = ohlc_evidence(c, pid, '101.00', '99.00')
    with c.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            ohlc_evidence(c, pid, '101', '99')
        savepoint.rollback()
    assert ohlc_evidence(c, pid, '102', '99') != eid
    assert ohlc_evidence(c, pid, '101', '98') != eid
    assert c.execute(text('SELECT high,low,close FROM indicator_input_evidence WHERE id=:id'), dict(id=eid)).one() == (
        Decimal(101), Decimal(99), Decimal(100))
    with pytest.raises(RuntimeError, match='cannot downgrade'):
        module.downgrade()


@pytest.mark.parametrize('status,number,reason', [
    ('available', '2.5', None), ('warming_up', None, 'warming_up'),
    ('data_unavailable', None, 'invalid_ohlcv'),
])
def test_atr_run_requires_exactly_one_period14_per_input_date(connection, status, number, reason):
    c = connection
    upgrade(c)
    pid = policy(c)
    rid, gid = run(c, atr_series(c, pid))
    ref(c, rid, ohlc_evidence(c, pid, 101, 99))
    rejected(c, COMPLETE, dict(rid=rid))
    value(c, rid, gid, period=14, kind='atr', status=status, number=number, reason=reason)
    rejected(c, '''INSERT INTO indicator_values
        (calculation_run_id,generation_id,indicator_kind,period,trade_date,value,status,reason_code,available_observations,input_prefix_hash)
        VALUES (:rid,:gid,'atr',14,'2024-01-02',NULL,'warming_up','warming_up',1,'p')''', dict(rid=rid, gid=gid))
    c.execute(text(COMPLETE), dict(rid=rid))
    rejected(c, 'DELETE FROM indicator_values WHERE calculation_run_id=:rid', dict(rid=rid))
    rejected(c, 'UPDATE indicator_calculation_runs SET result_hash=:hash WHERE id=:rid', dict(hash='changed', rid=rid))


@pytest.mark.parametrize('kind,period,status,number,reason', [
    ('atr', 50, 'warming_up', None, 'warming_up'),
    ('ema', 14, 'available', 100, None),
    ('volume_sma', 14, 'available', 100, None),
    ('atr', 14, 'available', None, None),
    ('atr', 14, 'available', 2, 'invalid_ohlcv'),
    ('atr', 14, 'warming_up', 2, 'warming_up'),
    ('atr', 14, 'warming_up', None, None),
    ('atr', 14, 'data_unavailable', 2, 'invalid_ohlcv'),
    ('atr', 14, 'data_unavailable', None, 'warming_up'),
    ('atr', 14, 'data_unavailable', None, None),
])
def test_atr_rejects_wrong_period_kind_and_invalid_value_shapes(connection, kind, period, status, number, reason):
    c = connection
    upgrade(c)
    rid, gid = run(c, atr_series(c, policy(c)))
    with c.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            value(c, rid, gid, kind=kind, period=period, status=status, number=number, reason=reason)
        savepoint.rollback()


def test_atr_completion_rejects_values_without_input_dates(connection):
    c = connection
    upgrade(c)
    rid, gid = run(c, atr_series(c, policy(c)))
    value(c, rid, gid, period=14, kind='atr')
    rejected(c, COMPLETE, dict(rid=rid))


@pytest.mark.parametrize('field,replacement', [
    ('input_field', 'close'), ('periods', '50'), ('formula_version', 'atr-v1'),
    ('input_policy_version', 'validated-observation-close-v3'), ('input_policy_id', None),
])
def test_atr_series_rejects_unsupported_definition(connection, field, replacement):
    c = connection
    upgrade(c)
    sid = atr_series(c, policy(c))
    # Insert a fresh series with a changed definition; existing series cannot be updated.
    with c.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            c.execute(text(f"""INSERT INTO indicator_series
                (instrument_id, indicator_kind, input_field, periods, input_policy_version, formula_version,
                 source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff, input_policy_id)
                SELECT 2, indicator_kind,
                    {':replacement' if field == 'input_field' else 'input_field'},
                    {':replacement' if field == 'periods' else 'periods'},
                    {':replacement' if field == 'input_policy_version' else 'input_policy_version'},
                    {':replacement' if field == 'formula_version' else 'formula_version'},
                    source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff,
                    {':replacement' if field == 'input_policy_id' else 'input_policy_id'}
                FROM indicator_series WHERE id=:sid"""), dict(sid=sid, replacement=replacement))
        savepoint.rollback()


def test_downgrade_rejects_unfinished_atr_series_before_ddl(connection):
    module = upgrade(connection)
    sid = atr_series(connection, policy(connection))
    with pytest.raises(RuntimeError, match='cannot downgrade'):
        module.downgrade()
    assert connection.execute(text('SELECT indicator_kind FROM indicator_series WHERE id=:sid'), dict(sid=sid)).scalar_one() == 'atr'
    assert {'high', 'low'} <= {col['name'] for col in inspect(connection).get_columns('indicator_input_evidence')}
