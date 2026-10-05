"""Add shared immutable OHLCV evidence and Volume MA50 storage.

Revision ID: y6c7d8e9f0a1
Revises: x5b6c7d8e9f0

No legacy series, generation, run, snapshot or value is rewritten.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "y6c7d8e9f0a1"
down_revision = "x5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('indicator_input_policies',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('version', sa.String(length=100), nullable=False, server_default="validated-observation-ohlcv-v1"),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('adjustment_type', sa.String(length=100), nullable=False),
        sa.Column('allowed_parser_versions', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column('observation_cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.Column('selector_version', sa.String(length=100), nullable=False),
        sa.Column('validation_version', sa.String(length=100), nullable=False),
        sa.Column('correction_version', sa.String(length=100), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("version = 'validated-observation-ohlcv-v1'", name='ck_indicator_input_policy_version'),
        sa.UniqueConstraint('fingerprint', name='uq_indicator_input_policy_fingerprint'),
    )
    op.create_table('indicator_input_evidence',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('input_policy_id', sa.Integer(), nullable=False),
        sa.Column('evidence_key', sa.String(length=64), nullable=False),
        sa.Column('trade_date', sa.Date(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('source_symbol_id', sa.Integer(), nullable=True),
        sa.Column('price_observation_id', sa.Integer(), nullable=True),
        sa.Column('price_observation_identity_snapshot_id', sa.Integer(), nullable=True),
        sa.Column('provider_symbol_mapping_id', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('provider_symbol', sa.String(length=50), nullable=False),
        sa.Column('adjustment_type', sa.String(length=100), nullable=True),
        sa.Column('parser_version', sa.String(length=100), nullable=True),
        sa.Column('close', sa.Numeric(), nullable=True),
        sa.Column('volume', sa.Integer(), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=True),
        sa.Column('mapping_status', sa.String(length=30), nullable=True),
        sa.Column('mapping_valid_from', sa.Date(), nullable=True),
        sa.Column('mapping_valid_to', sa.Date(), nullable=True),
        sa.Column('resolver_version', sa.String(length=100), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correction_ids', sa.JSON(), nullable=False),
        sa.Column('validation_evidence', sa.JSON(), nullable=False),
        sa.Column('input_status', sa.String(length=30), nullable=False),
        sa.Column('reason_code', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['source_symbol_id'], ['symbols.id'], name=None),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], name=None),
        sa.ForeignKeyConstraint(['input_policy_id'], ['indicator_input_policies.id'], name=None),
        sa.ForeignKeyConstraint(['price_observation_id'], ['price_observations.id'], name=None),
        sa.ForeignKeyConstraint(['provider_symbol_mapping_id'], ['provider_symbols.id'], name=None),
        sa.CheckConstraint('price_observation_identity_snapshot_id IS NULL OR price_observation_id IS NOT NULL', name='ck_indicator_evidence_identity_observation'),
        sa.CheckConstraint('mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to', name='ck_indicator_evidence_mapping_range'),
        sa.CheckConstraint("mapping_status IS NULL OR mapping_status IN ('matched', 'unmatched', 'ambiguous', 'invalid_legacy')", name='ck_indicator_evidence_mapping_status'),
        sa.CheckConstraint("reason_code IS NULL OR reason_code IN ('warming_up', 'missing_selected_source', 'identity_unavailable', 'ambiguous_identity_mapping', 'conflicting_observations', 'approved_exclusion', 'approved_validation_exclusion', 'open_validation_case', 'invalid_approved_correction', 'invalid_ohlcv', 'provider_or_adjustment_discontinuity', 'confirmed_trading_halt')", name='ck_indicator_evidence_reason'),
        sa.CheckConstraint("input_status IN ('eligible', 'missing', 'invalid', 'review_required', 'confirmed_trading_halt')", name='ck_indicator_evidence_status'),
        sa.ForeignKeyConstraint(['price_observation_identity_snapshot_id', 'price_observation_id'], ['price_observation_identity_snapshots.id', 'price_observation_identity_snapshots.price_observation_id'], name='fk_indicator_evidence_identity_observation'),
        sa.UniqueConstraint('evidence_key', name='uq_indicator_input_evidence_key'),
    )
    op.create_index('ix_indicator_evidence_policy_instrument_date', 'indicator_input_evidence', ['input_policy_id', 'instrument_id', 'trade_date'])
    op.create_table('indicator_run_inputs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('calculation_run_id', sa.Integer(), nullable=False),
        sa.Column('evidence_id', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('prefix_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['calculation_run_id'], ['indicator_calculation_runs.id'], name=None),
        sa.ForeignKeyConstraint(['evidence_id'], ['indicator_input_evidence.id'], name=None),
        sa.CheckConstraint('ordinal >= 0', name='ck_indicator_run_input_ordinal'),
        sa.UniqueConstraint('calculation_run_id', 'evidence_id', name='uq_indicator_run_input_evidence'),
        sa.UniqueConstraint('calculation_run_id', 'ordinal', name='uq_indicator_run_input_ordinal'),
    )
    with op.batch_alter_table("indicator_series") as batch:
        batch.add_column(sa.Column("input_policy_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_indicator_series_input_policy", "indicator_input_policies", ["input_policy_id"], ["id"])
        for name in ("ck_indicator_series_kind_ema", "ck_indicator_series_input_close", "ck_indicator_series_periods", "ck_indicator_series_input_policy_version", "ck_indicator_series_formula_version"):
            batch.drop_constraint(name, type_="check")
        batch.drop_constraint("uq_indicator_series_policy", type_="unique")
        batch.create_unique_constraint("uq_indicator_series_common_policy", ["instrument_id", "indicator_kind", "input_policy_id"])
        batch.create_check_constraint('ck_indicator_series_definition', "(indicator_kind = 'ema' AND input_field = 'close' AND periods = '5,20,50,200' AND formula_version = 'ema-close-seed-v1' AND ((input_policy_version = 'validated-observation-close-v3' AND input_policy_id IS NULL) OR (input_policy_version = 'validated-observation-ohlcv-v1' AND input_policy_id IS NOT NULL))) OR (indicator_kind = 'volume_sma' AND input_field = 'volume' AND periods = '50' AND formula_version = 'volume-sma-v1' AND input_policy_version = 'validated-observation-ohlcv-v1' AND input_policy_id IS NOT NULL)")
    op.create_index("uq_indicator_series_policy", "indicator_series",
                    ["instrument_id", "indicator_kind", "input_field", "periods", "input_policy_version", "formula_version", "source_provider", "adjustment_policy", "allowed_parser_versions", "observation_cutoff"],
                    unique=True, postgresql_where=sa.text("input_policy_id IS NULL"), sqlite_where=sa.text("input_policy_id IS NULL"))
    with op.batch_alter_table("indicator_values") as batch:
        batch.add_column(sa.Column("indicator_kind", sa.String(20), nullable=False, server_default="ema"))
        batch.drop_constraint("ck_indicator_values_status_shape", type_="check")
        batch.create_check_constraint('ck_indicator_values_status_shape', "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) OR (status = 'warming_up' AND reason_code = 'warming_up' AND ((indicator_kind = 'ema' AND value IS NOT NULL) OR (indicator_kind = 'volume_sma' AND value IS NULL))) OR (status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL AND (indicator_kind = 'ema' OR reason_code <> 'warming_up'))")
        batch.create_check_constraint('ck_indicator_values_definition', "indicator_kind = 'ema' OR (indicator_kind = 'volume_sma' AND period = 50)")
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_contracts()


def _postgresql_contracts():
    # PostgreSQL's JSONB text is deterministic (including object-key order).
    # Explicit UTC pins timestamptz representation independently of the client.
    op.execute("""
        CREATE FUNCTION indicator_common_fingerprint() RETURNS trigger
        SET timezone = 'UTC' AS $$
        DECLARE payload jsonb;
        BEGIN
            IF TG_TABLE_NAME = 'indicator_input_policies' THEN
                IF jsonb_typeof(NEW.allowed_parser_versions) <> 'array'
                   OR jsonb_array_length(NEW.allowed_parser_versions) = 0
                   OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.allowed_parser_versions) x
                              WHERE jsonb_typeof(x) <> 'string' OR x = '\"\"'::jsonb)
                   OR NEW.provider = '' OR NEW.adjustment_type = ''
                   OR NEW.selector_version = '' OR NEW.validation_version = '' OR NEW.correction_version = '' THEN
                    RAISE EXCEPTION 'invalid common input policy';
                END IF;
                SELECT jsonb_agg(v ORDER BY v COLLATE "C") INTO NEW.allowed_parser_versions
                FROM (SELECT DISTINCT jsonb_array_elements_text(NEW.allowed_parser_versions) v) versions;
                payload := to_jsonb(NEW) - ARRAY['id', 'created_at', 'fingerprint'];
                NEW.fingerprint := encode(sha256(convert_to(payload::text, 'UTF8')), 'hex');
            ELSE
                NEW.close := trim_scale(NEW.close);
                payload := to_jsonb(NEW) - ARRAY['id', 'created_at', 'evidence_key'];
                NEW.evidence_key := encode(sha256(convert_to(payload::text, 'UTF8')), 'hex');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_indicator_input_policy_fingerprint BEFORE INSERT ON indicator_input_policies
        FOR EACH ROW EXECUTE FUNCTION indicator_common_fingerprint();
        CREATE TRIGGER trg_indicator_input_evidence_key BEFORE INSERT ON indicator_input_evidence
        FOR EACH ROW EXECUTE FUNCTION indicator_common_fingerprint();
        CREATE TRIGGER trg_indicator_input_policy_immutable BEFORE UPDATE OR DELETE ON indicator_input_policies
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_identity_snapshot_mutation();
        CREATE TRIGGER trg_indicator_input_evidence_immutable BEFORE UPDATE OR DELETE ON indicator_input_evidence
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_identity_snapshot_mutation();
        CREATE TRIGGER trg_indicator_series_immutable BEFORE UPDATE OR DELETE ON indicator_series
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_identity_snapshot_mutation();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION indicator_prevent_completed_child_mutation() RETURNS trigger AS $$
        DECLARE run_id integer; old_run_id integer; new_run_id integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN old_run_id := OLD.calculation_run_id; END IF;
            IF TG_OP <> 'DELETE' THEN new_run_id := NEW.calculation_run_id; END IF;
            FOR run_id IN SELECT id FROM indicator_calculation_runs
                          WHERE id IN (old_run_id, new_run_id) ORDER BY id FOR UPDATE LOOP
                IF EXISTS (SELECT 1 FROM indicator_calculation_runs WHERE id = run_id AND status = 'completed') THEN
                    RAISE EXCEPTION 'completed indicator calculation run children are immutable';
                END IF;
            END LOOP;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE FUNCTION indicator_check_common_series() RETURNS trigger AS $$
        BEGIN
            IF NEW.input_policy_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM indicator_input_policies p WHERE p.id = NEW.input_policy_id
                  AND p.version = NEW.input_policy_version AND p.provider = NEW.source_provider
                  AND p.adjustment_type = NEW.adjustment_policy
                  AND p.allowed_parser_versions = NEW.allowed_parser_versions
                  AND p.observation_cutoff = NEW.observation_cutoff
            ) THEN
                RAISE EXCEPTION 'series source fields must match immutable input policy';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_indicator_series_common_policy BEFORE INSERT ON indicator_series
        FOR EACH ROW EXECUTE FUNCTION indicator_check_common_series();

        CREATE FUNCTION indicator_check_run_input() RETURNS trigger AS $$
        DECLARE series indicator_series; evidence indicator_input_evidence;
        BEGIN
            -- Serialize child inserts with completion and other references.
            PERFORM 1 FROM indicator_calculation_runs WHERE id = NEW.calculation_run_id FOR UPDATE;
            SELECT s.* INTO series FROM indicator_series s JOIN indicator_calculation_runs r
                ON r.series_id = s.id WHERE r.id = NEW.calculation_run_id;
            SELECT * INTO evidence FROM indicator_input_evidence WHERE id = NEW.evidence_id;
            IF series.input_policy_id IS NULL OR evidence.id IS NULL
               OR series.instrument_id IS DISTINCT FROM evidence.instrument_id
               OR series.input_policy_id IS DISTINCT FROM evidence.input_policy_id THEN
                RAISE EXCEPTION 'run input must match historical instrument and input policy';
            END IF;
            IF EXISTS (SELECT 1 FROM indicator_run_inputs i JOIN indicator_input_evidence e ON e.id = i.evidence_id
                       WHERE i.calculation_run_id = NEW.calculation_run_id AND e.trade_date = evidence.trade_date
                         AND i.id <> NEW.id) THEN
                RAISE EXCEPTION 'run input date must be unique';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_indicator_run_input_contract BEFORE INSERT OR UPDATE ON indicator_run_inputs
        FOR EACH ROW EXECUTE FUNCTION indicator_check_run_input();
        CREATE TRIGGER trg_indicator_run_inputs_completed_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON indicator_run_inputs
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_child_mutation();

        CREATE FUNCTION indicator_check_value_definition() RETURNS trigger AS $$
        DECLARE kind text;
        BEGIN
            PERFORM 1 FROM indicator_calculation_runs WHERE id = NEW.calculation_run_id FOR UPDATE;
            SELECT s.indicator_kind INTO kind FROM indicator_series s JOIN indicator_calculation_runs r
                ON r.series_id = s.id WHERE r.id = NEW.calculation_run_id;
            IF NEW.indicator_kind IS DISTINCT FROM kind THEN
                RAISE EXCEPTION 'value definition must match its run series';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_indicator_value_definition BEFORE INSERT OR UPDATE ON indicator_values
        FOR EACH ROW EXECUTE FUNCTION indicator_check_value_definition();

        CREATE FUNCTION indicator_prevent_lineage_reparenting() RETURNS trigger AS $$
        BEGIN
            IF TG_TABLE_NAME = 'indicator_calculation_runs' THEN
                IF EXISTS (
                    SELECT 1 FROM indicator_series s WHERE s.id = NEW.series_id AND s.input_policy_id IS NOT NULL
                    AND s.observation_cutoff IS DISTINCT FROM NEW.input_cutoff
                ) THEN
                    RAISE EXCEPTION 'run cutoff must match immutable input policy';
                END IF;
            END IF;
            IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
            IF NEW.series_id IS DISTINCT FROM OLD.series_id THEN
                RAISE EXCEPTION 'indicator lineage cannot change series';
            END IF;
            IF TG_TABLE_NAME = 'indicator_calculation_runs' AND
               (to_jsonb(NEW)->'generation_id') IS DISTINCT FROM (to_jsonb(OLD)->'generation_id') THEN
                RAISE EXCEPTION 'indicator run cannot change generation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_indicator_run_lineage BEFORE INSERT OR UPDATE ON indicator_calculation_runs
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_lineage_reparenting();
        CREATE TRIGGER trg_indicator_generation_lineage BEFORE UPDATE ON indicator_generations
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_lineage_reparenting();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION indicator_require_complete_run_values(target_run_id integer) RETURNS void AS $$
        DECLARE series indicator_series; expected_periods integer[]; bad_date date;
        BEGIN
            SELECT s.* INTO series FROM indicator_series s JOIN indicator_calculation_runs r
                ON r.series_id = s.id WHERE r.id = target_run_id;
            expected_periods := CASE WHEN series.indicator_kind = 'ema' THEN ARRAY[5,20,50,200] ELSE ARRAY[50] END;
            IF series.input_policy_id IS NULL THEN
                IF EXISTS (SELECT 1 FROM indicator_run_inputs WHERE calculation_run_id = target_run_id) THEN
                    RAISE EXCEPTION 'legacy EMA runs require legacy snapshots';
                END IF;
            ELSE
                IF EXISTS (SELECT 1 FROM indicator_input_snapshots WHERE calculation_run_id = target_run_id) THEN
                    RAISE EXCEPTION 'common policy runs require shared evidence';
                END IF;
            END IF;
            WITH inputs AS (
                SELECT trade_date FROM indicator_input_snapshots
                WHERE calculation_run_id = target_run_id AND series.input_policy_id IS NULL
                UNION ALL
                SELECT e.trade_date FROM indicator_run_inputs i JOIN indicator_input_evidence e ON e.id = i.evidence_id
                WHERE i.calculation_run_id = target_run_id AND series.input_policy_id IS NOT NULL
            )
            SELECT i.trade_date INTO bad_date FROM inputs i WHERE
                (SELECT array_agg(v.period ORDER BY v.period) FROM indicator_values v
                 WHERE v.calculation_run_id = target_run_id AND v.trade_date = i.trade_date)
                IS DISTINCT FROM expected_periods LIMIT 1;
            IF bad_date IS NOT NULL THEN
                RAISE EXCEPTION 'completed indicator run % has missing or extra periods for %', target_run_id, bad_date;
            END IF;
            IF EXISTS (
                SELECT 1 FROM indicator_values v WHERE v.calculation_run_id = target_run_id AND NOT EXISTS (
                    SELECT 1 FROM indicator_input_snapshots i WHERE i.calculation_run_id = target_run_id
                        AND i.trade_date = v.trade_date AND series.input_policy_id IS NULL
                    UNION ALL
                    SELECT 1 FROM indicator_run_inputs i JOIN indicator_input_evidence e ON e.id = i.evidence_id
                    WHERE i.calculation_run_id = target_run_id AND e.trade_date = v.trade_date AND series.input_policy_id IS NOT NULL
                )
            ) THEN
                RAISE EXCEPTION 'completed indicator run % has values without input evidence', target_run_id;
            END IF;
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade():
    bind = op.get_bind()
    # Refuse before any DDL. Never silently discard completed history/evidence.
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM indicator_calculation_runs WHERE status = 'completed') OR EXISTS (SELECT 1 FROM indicator_input_policies) OR EXISTS (SELECT 1 FROM indicator_input_evidence) OR EXISTS (SELECT 1 FROM indicator_run_inputs)")).scalar():
        raise RuntimeError("cannot downgrade immutable indicator history; preserve it and roll forward")
    if bind.dialect.name == "postgresql":
        for table, trigger in (
            ("indicator_series", "trg_indicator_series_immutable"),
            ("indicator_series", "trg_indicator_series_common_policy"),
            ("indicator_values", "trg_indicator_value_definition"),
            ("indicator_calculation_runs", "trg_indicator_run_lineage"),
            ("indicator_generations", "trg_indicator_generation_lineage"),
        ):
            op.execute(f"DROP TRIGGER {trigger} ON {table}")
        # Restore the prior exact EMA completion contract after shared tables go.
        op.execute("""
            CREATE OR REPLACE FUNCTION indicator_require_complete_run_values(target_run_id integer) RETURNS void AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM indicator_input_snapshots i WHERE i.calculation_run_id = target_run_id AND
                    (SELECT array_agg(v.period ORDER BY v.period) FROM indicator_values v
                     WHERE v.calculation_run_id = target_run_id AND v.trade_date = i.trade_date)
                    IS DISTINCT FROM ARRAY[5,20,50,200]
                ) OR EXISTS (
                    SELECT 1 FROM indicator_values v WHERE v.calculation_run_id = target_run_id AND NOT EXISTS (
                        SELECT 1 FROM indicator_input_snapshots i WHERE i.calculation_run_id = target_run_id AND i.trade_date = v.trade_date)
                ) THEN RAISE EXCEPTION 'completed EMA run has incomplete values'; END IF;
            END;
            $$ LANGUAGE plpgsql
        """)
    with op.batch_alter_table("indicator_values") as batch:
        batch.drop_constraint("ck_indicator_values_definition", type_="check")
        batch.drop_constraint("ck_indicator_values_status_shape", type_="check")
        batch.drop_column("indicator_kind")
        batch.create_check_constraint("ck_indicator_values_status_shape", "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) OR (status = 'warming_up' AND value IS NOT NULL AND reason_code = 'warming_up') OR (status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL)")
    op.drop_index("uq_indicator_series_policy", table_name="indicator_series")
    with op.batch_alter_table("indicator_series") as batch:
        batch.create_unique_constraint("uq_indicator_series_policy", ["instrument_id", "indicator_kind", "input_field", "periods", "input_policy_version", "formula_version", "source_provider", "adjustment_policy", "allowed_parser_versions", "observation_cutoff"])
        batch.drop_constraint("ck_indicator_series_definition", type_="check")
        batch.drop_constraint("uq_indicator_series_common_policy", type_="unique")
        batch.drop_constraint("fk_indicator_series_input_policy", type_="foreignkey")
        batch.drop_column("input_policy_id")
        for name, expression in (
            ("ck_indicator_series_kind_ema", "indicator_kind = 'ema'"),
            ("ck_indicator_series_input_close", "input_field = 'close'"),
            ("ck_indicator_series_periods", "periods = '5,20,50,200'"),
            ("ck_indicator_series_input_policy_version", "input_policy_version = 'validated-observation-close-v3'"),
            ("ck_indicator_series_formula_version", "formula_version = 'ema-close-seed-v1'"),
        ):
            batch.create_check_constraint(name, expression)
    op.drop_table("indicator_run_inputs")
    op.drop_table("indicator_input_evidence")
    op.drop_table("indicator_input_policies")
    if bind.dialect.name == "postgresql":
        for function in ("indicator_common_fingerprint", "indicator_check_common_series", "indicator_check_run_input", "indicator_check_value_definition", "indicator_prevent_lineage_reparenting"):
            op.execute(f"DROP FUNCTION {function}()")
