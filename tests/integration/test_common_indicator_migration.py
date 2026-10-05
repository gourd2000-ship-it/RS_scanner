"""Execute append-only upgrades inside a rolled-back PostgreSQL schema."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

VERSIONS = Path(__file__).parents[2] / 'alembic' / 'versions'


def migration(prefix, connection):
    path = next(VERSIONS.glob(prefix + '_*.py'))
    spec = importlib.util.spec_from_file_location(prefix, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


@pytest.fixture
def connection():
    engine = create_engine(os.getenv('TEST_DATABASE_URL', 'postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test'))
    try:
        conn = engine.connect()
    except SQLAlchemyError as exc:
        pytest.skip(f'isolated PostgreSQL unavailable: {type(exc).__name__}')
    with conn:
        transaction = conn.begin()
        schema = 'indicator_test_' + uuid4().hex
        conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
        conn.exec_driver_sql(f'SET LOCAL search_path TO {schema}')
        for table in ('instruments', 'symbols', 'provider_symbols', 'price_observations'):
            conn.exec_driver_sql(f'CREATE TABLE {table} (id integer PRIMARY KEY)')
        conn.exec_driver_sql('INSERT INTO instruments VALUES (1), (2)')
        migration('w4a5b6c7d8e9', conn).upgrade()
        migration('x5b6c7d8e9f0', conn).upgrade()
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def rejected(conn, sql, params=None):
    with conn.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            conn.execute(text(sql), params or {})
        savepoint.rollback()


def policy(conn, cutoff='2024-02-01', versions='["v2", "v1", "v2"]'):
    return conn.execute(text('''INSERT INTO indicator_input_policies
        (provider, adjustment_type, allowed_parser_versions, observation_cutoff, selector_version, validation_version, correction_version)
        VALUES ('kiwoom', '1', CAST(:versions AS jsonb), :cutoff, 'selector-v1', 'validation-v1', 'correction-v1') RETURNING id'''),
        dict(versions=versions, cutoff=cutoff)).scalar_one()


def series(conn, pid, kind='volume_sma', instrument=1):
    return conn.execute(text('''INSERT INTO indicator_series
        (instrument_id, indicator_kind, input_field, periods, input_policy_version, formula_version,
         source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff, input_policy_id)
        SELECT :instrument, :kind, :field, :periods, version, :formula, provider, adjustment_type,
               allowed_parser_versions, observation_cutoff, id FROM indicator_input_policies WHERE id = :pid RETURNING id'''),
        dict(instrument=instrument, kind=kind, field='close' if kind == 'ema' else 'volume', periods='5,20,50,200' if kind == 'ema' else '50',
             formula='ema-close-seed-v1' if kind == 'ema' else 'volume-sma-v1', pid=pid)).scalar_one()


def run(conn, sid, generation=1):
    gid = conn.execute(text('INSERT INTO indicator_generations (series_id, generation) VALUES (:sid, :generation) RETURNING id'), dict(sid=sid, generation=generation)).scalar_one()
    rid = conn.execute(text("INSERT INTO indicator_calculation_runs (generation_id, series_id, run_kind, input_cutoff) VALUES (:gid, :sid, 'backfill', '2024-02-01') RETURNING id"), dict(gid=gid, sid=sid)).scalar_one()
    return rid, gid


def evidence(conn, pid, instrument=1, correction='[]', trade_date='2024-01-02', close=None, volume=None, validation='[]'):
    return conn.execute(text('''INSERT INTO indicator_input_evidence
        (input_policy_id, instrument_id, trade_date, provider, provider_symbol, close, volume, correction_ids, validation_evidence, input_status, reason_code)
        VALUES (:pid, :instrument, :date, 'kiwoom', 'TEST', :close, :volume, CAST(:correction AS json), CAST(:validation AS json), 'missing', 'missing_selected_source') RETURNING id'''),
        dict(pid=pid, instrument=instrument, correction=correction, date=trade_date, close=close, volume=volume, validation=validation)).scalar_one()


def ref(conn, rid, eid, ordinal=0):
    conn.execute(text('INSERT INTO indicator_run_inputs (calculation_run_id, evidence_id, ordinal, prefix_hash) VALUES (:rid, :eid, :ordinal, :hash)'), dict(rid=rid, eid=eid, ordinal=ordinal, hash='a'*64))


def value(conn, rid, gid, period=50, kind='volume_sma', status='warming_up', number=None, reason='warming_up'):
    conn.execute(text('''INSERT INTO indicator_values
        (calculation_run_id, generation_id, indicator_kind, period, trade_date, value, status, reason_code, available_observations, input_prefix_hash)
        VALUES (:rid, :gid, :kind, :period, '2024-01-02', :number, :status, :reason, 1, :hash)'''),
        dict(rid=rid, gid=gid, period=period, kind=kind, number=number, status=status, reason=reason, hash='a'*64))


COMPLETE = "UPDATE indicator_calculation_runs SET status='completed', input_hash='input', result_hash='result', completed_at=now() WHERE id=:rid"


def test_empty_upgrade_and_empty_downgrade(connection):
    module = migration('y6c7d8e9f0a1', connection)
    module.upgrade()
    module.downgrade()
    module.upgrade()


def test_existing_completed_ema_history_is_unchanged(connection):
    c = connection
    sid = c.execute(text('''INSERT INTO indicator_series (instrument_id, source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff)
        VALUES (1, 'kiwoom', '1', '["v1"]', '2024-02-01') RETURNING id''')).scalar_one()
    rid, gid = run(c, sid)
    c.execute(text('''INSERT INTO indicator_input_snapshots
        (calculation_run_id, generation_id, trade_date, instrument_id, provider, provider_symbol, correction_ids, validation_evidence, input_status, row_hash, prefix_hash)
        VALUES (:rid, :gid, '2024-01-02', 1, 'kiwoom', 'TEST', '[]', '[]', 'eligible', 'row', 'prefix')'''), dict(rid=rid, gid=gid))
    for period in (5,20,50,200):
        c.execute(text('''INSERT INTO indicator_values
            (calculation_run_id, generation_id, period, trade_date, value, status, reason_code, available_observations, input_prefix_hash)
            VALUES (:rid, :gid, :period, '2024-01-02', 100, 'warming_up', 'warming_up', 1, 'prefix')'''), dict(rid=rid, gid=gid, period=period))
    c.execute(text(COMPLETE), dict(rid=rid))
    tables = ('indicator_series', 'indicator_generations', 'indicator_calculation_runs', 'indicator_input_snapshots', 'indicator_values')
    before = {table:list(c.execute(text(f'SELECT * FROM {table} ORDER BY id')).mappings()) for table in tables}
    module = migration('y6c7d8e9f0a1', c)
    module.upgrade()
    for table in tables:
        columns = ','.join(before[table][0].keys())
        assert list(c.execute(text(f'SELECT {columns} FROM {table} ORDER BY id')).mappings()) == before[table]
    rejected(c, 'UPDATE indicator_values SET value=200 WHERE calculation_run_id=:rid', dict(rid=rid))
    rejected(c, 'DELETE FROM indicator_input_snapshots WHERE calculation_run_id=:rid', dict(rid=rid))
    with pytest.raises(RuntimeError, match='cannot downgrade'):
        module.downgrade()


def test_policy_fingerprint_and_null_observation_evidence_are_deduplicated(connection):
    c = connection
    migration('y6c7d8e9f0a1', c).upgrade()
    pid = policy(c)
    row = c.execute(text('SELECT * FROM indicator_input_policies')).mappings().one()
    assert row['allowed_parser_versions'] == ['v1','v2']
    assert len(row['fingerprint']) == 64
    with c.begin_nested() as sp:
        with pytest.raises(DBAPIError):
            policy(c, versions='["v1", "v2"]')
        sp.rollback()
    eid = evidence(c, pid)
    with c.begin_nested() as sp:
        with pytest.raises(DBAPIError):
            evidence(c, pid)
        sp.rollback()
    assert evidence(c, pid, correction='[9]') != eid
    rejected(c, 'UPDATE indicator_input_policies SET selector_version=:version WHERE id=:id', dict(version='new', id=pid))
    rejected(c, 'DELETE FROM indicator_input_evidence WHERE id=:id', dict(id=eid))


def test_run_input_scope_order_reuse_and_volume_completion(connection):
    c = connection
    module = migration('y6c7d8e9f0a1', c)
    module.upgrade()
    pid = policy(c)
    sid = series(c, pid)
    rid, gid = run(c, sid)
    eid = evidence(c, pid)
    wrong_instrument = evidence(c, pid, instrument=2)
    wrong_policy = evidence(c, policy(c, cutoff='2024-02-02'))
    for bad in (wrong_instrument, wrong_policy):
        rejected(c, "INSERT INTO indicator_run_inputs (calculation_run_id,evidence_id,ordinal,prefix_hash) VALUES (:rid,:eid,0,'p')", dict(rid=rid,eid=bad))
    ref(c, rid, eid)
    rejected(c, "INSERT INTO indicator_run_inputs (calculation_run_id,evidence_id,ordinal,prefix_hash) VALUES (:rid,:eid,1,'p')", dict(rid=rid,eid=eid))
    other_date = evidence(c, pid, trade_date='2024-01-03')
    rejected(c, "INSERT INTO indicator_run_inputs (calculation_run_id,evidence_id,ordinal,prefix_hash) VALUES (:rid,:eid,0,'p')", dict(rid=rid,eid=other_date))
    revised = evidence(c, pid, correction='[5]')
    rejected(c, "INSERT INTO indicator_run_inputs (calculation_run_id,evidence_id,ordinal,prefix_hash) VALUES (:rid,:eid,1,'p')", dict(rid=rid,eid=revised))
    rejected(c, COMPLETE, dict(rid=rid))
    value(c,rid,gid)
    c.execute(text(COMPLETE),dict(rid=rid))
    c.execute(text("UPDATE indicator_generations SET status='current' WHERE id=:gid"),dict(gid=gid))
    rejected(c, 'DELETE FROM indicator_run_inputs WHERE calculation_run_id=:rid', dict(rid=rid))
    rejected(c, 'UPDATE indicator_series SET instrument_id=2 WHERE id=:sid', dict(sid=sid))
    rid2,gid2=run(c,sid,generation=2)
    ref(c,rid2,eid)
    value(c,rid2,gid2,status='data_unavailable',reason='missing_selected_source')
    c.execute(text(COMPLETE),dict(rid=rid2))
    with pytest.raises(RuntimeError, match='cannot downgrade'):
        module.downgrade()


@pytest.mark.parametrize('kind,period,number,status,reason', [
    ('volume_sma',5,None,'warming_up','warming_up'),
    ('volume_sma',50,100,'warming_up','warming_up'),
    ('volume_sma',50,None,'warming_up',None),
    ('volume_sma',50,None,'available',None),
    ('volume_sma',50,None,'data_unavailable','warming_up'),
    ('ema',50,None,'warming_up','warming_up'),
])
def test_invalid_value_shapes_rejected(connection,kind,period,number,status,reason):
    c=connection
    migration('y6c7d8e9f0a1',c).upgrade()
    rid,gid=run(c,series(c,policy(c),kind=kind))
    with c.begin_nested() as sp:
        with pytest.raises(DBAPIError):
            value(c,rid,gid,period,kind,status,number,reason)
        sp.rollback()


def test_common_ema_requires_each_exact_period(connection):
    c=connection
    migration('y6c7d8e9f0a1',c).upgrade()
    pid=policy(c)
    rid,gid=run(c,series(c,pid,kind='ema'))
    ref(c,rid,evidence(c,pid))
    for period in (5,20,50):
        value(c,rid,gid,period=period,kind='ema',number=100)
    rejected(c,COMPLETE,dict(rid=rid))
    value(c,rid,gid,period=200,kind='ema',number=100)
    c.execute(text(COMPLETE),dict(rid=rid))


def test_full_alembic_chain_on_empty_postgresql_schema(connection):
    """Exercise the entire deployment path, not only the three indicator revisions."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.environment import EnvironmentContext

    c = connection
    schema = 'indicator_full_' + uuid4().hex
    c.exec_driver_sql(f'CREATE SCHEMA {schema}')
    c.exec_driver_sql(f'SET LOCAL search_path TO {schema}')
    config = Config(str(VERSIONS.parents[1] / 'alembic.ini'))
    config.set_main_option('script_location', str(VERSIONS.parent))
    scripts = ScriptDirectory.from_config(config)
    with EnvironmentContext(config, scripts) as env:
        env.configure(connection=c)
        for revision in reversed(list(scripts.walk_revisions())):
            module = revision.module
            module.op = Operations(MigrationContext.configure(c))
            module.upgrade()
    assert c.execute(text("SELECT to_regclass('indicator_input_evidence')")).scalar_one() is not None


def test_rule_version_change_gets_distinct_policy_and_series(connection):
    c=connection
    migration('y6c7d8e9f0a1',c).upgrade()
    pid=policy(c)
    sid=series(c,pid)
    newer=c.execute(text("""INSERT INTO indicator_input_policies
        (version, provider, adjustment_type, allowed_parser_versions, observation_cutoff, selector_version, validation_version, correction_version)
        SELECT version, provider, adjustment_type, allowed_parser_versions, observation_cutoff, 'selector-v2', validation_version, correction_version
        FROM indicator_input_policies WHERE id=:pid RETURNING id"""),dict(pid=pid)).scalar_one()
    assert series(c,newer) != sid
    with c.begin_nested() as sp:
        with pytest.raises(DBAPIError):
            series(c,pid)
        sp.rollback()


def test_evidence_key_normalizes_numeric_scale_but_retains_changed_facts(connection):
    c=connection
    migration('y6c7d8e9f0a1',c).upgrade()
    pid=policy(c)
    first=evidence(c,pid,close='100.00',volume=1000)
    with c.begin_nested() as sp:
        with pytest.raises(DBAPIError):
            evidence(c,pid,close='100',volume=1000)
        sp.rollback()
    assert evidence(c,pid,close='100',volume=2000) != first
    assert evidence(c,pid,close='100',volume=1000,validation='[{"id": 1, "status": "open"}]') != first


def test_orm_receives_database_generated_fingerprints(connection):
    from datetime import UTC, datetime
    from sqlalchemy.orm import Session
    from app.models.indicator import IndicatorInputPolicy

    c=connection
    migration('y6c7d8e9f0a1',c).upgrade()
    with Session(bind=c, join_transaction_mode='create_savepoint') as session:
        item=IndicatorInputPolicy(provider='kiwoom',adjustment_type='1',allowed_parser_versions=['v2','v1'],
            observation_cutoff=datetime(2024,2,1,tzinfo=UTC),selector_version='selector-v1',
            validation_version='validation-v1',correction_version='correction-v1')
        session.add(item)
        session.flush()
        assert len(item.fingerprint)==64
