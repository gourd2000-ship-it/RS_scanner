"""Add ATR14 storage and high/low to new shared evidence without rewriting history.

Revision ID: z7d8e9f0a1b2
Revises: y6c7d8e9f0a1
"""
from alembic import op
import sqlalchemy as sa

revision = "z7d8e9f0a1b2"
down_revision = "y6c7d8e9f0a1"
branch_labels = None
depends_on = None

SERIES_BEFORE = (
    "(indicator_kind = 'ema' AND input_field = 'close' AND periods = '5,20,50,200' AND formula_version = "
    "'ema-close-seed-v1' AND ((input_policy_version = 'validated-observation-close-v3' AND input_policy_id IS "
    "NULL) OR (input_policy_version = 'validated-observation-ohlcv-v1' AND input_policy_id IS NOT NULL))) OR "
    "(indicator_kind = 'volume_sma' AND input_field = 'volume' AND periods = '50' AND formula_version = "
    "'volume-sma-v1' AND input_policy_version = 'validated-observation-ohlcv-v1' AND input_policy_id IS NOT NULL)"
)
SERIES_AFTER = SERIES_BEFORE + (
    " OR (indicator_kind = 'atr' AND input_field = 'high-low-close' AND periods = '14' "
    "AND formula_version = 'wilder-atr-14-v1' AND input_policy_version = 'validated-observation-ohlcv-v1' "
    "AND input_policy_id IS NOT NULL)"
)
VALUE_DEFINITION_BEFORE = (
    "indicator_kind = 'ema' OR (indicator_kind = 'volume_sma' AND period = 50)"
)
VALUE_DEFINITION_AFTER = (
    "(indicator_kind = 'ema' AND period IN (5, 20, 50, 200)) OR (indicator_kind = 'volume_sma' AND period = 50) "
    "OR (indicator_kind = 'atr' AND period = 14)"
)
VALUE_SHAPE_BEFORE = (
    "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) OR (status = 'warming_up' AND "
    "reason_code IS NOT NULL AND reason_code = 'warming_up' AND ((indicator_kind = 'ema' AND value IS NOT NULL) "
    "OR (indicator_kind = 'volume_sma' AND value IS NULL))) OR (status = 'data_unavailable' AND value IS NULL AND "
    "reason_code IS NOT NULL AND (indicator_kind = 'ema' OR reason_code <> 'warming_up'))"
)
VALUE_SHAPE_AFTER = VALUE_SHAPE_BEFORE.replace(
    "indicator_kind = 'volume_sma' AND value IS NULL",
    "indicator_kind IN ('volume_sma', 'atr') AND value IS NULL",
)


def _definitions(atr):
    with op.batch_alter_table("indicator_series") as batch:
        batch.drop_constraint("ck_indicator_series_definition", type_="check")
        batch.create_check_constraint("ck_indicator_series_definition", SERIES_AFTER if atr else SERIES_BEFORE)
    with op.batch_alter_table("indicator_values") as batch:
        for name, expression in (
            ("ck_indicator_values_definition", VALUE_DEFINITION_AFTER if atr else VALUE_DEFINITION_BEFORE),
            ("ck_indicator_values_status_shape", VALUE_SHAPE_AFTER if atr else VALUE_SHAPE_BEFORE),
            ("ck_indicator_values_period", "period IN (5, 14, 20, 50, 200)" if atr else "period IN (5, 20, 50, 200)"),
        ):
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, expression)


def upgrade():
    # Nullable columns preserve every existing fact and evidence key. Never backfill.
    op.add_column("indicator_input_evidence", sa.Column("high", sa.Numeric(), nullable=True))
    op.add_column("indicator_input_evidence", sa.Column("low", sa.Numeric(), nullable=True))
    _definitions(True)
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_contracts(True)


def downgrade():
    bind = op.get_bind()
    # Serialize preflight with writers so no OHLC/ATR facts appear before DDL.
    if bind.dialect.name == "postgresql":
        op.execute("LOCK TABLE indicator_input_evidence, indicator_series, indicator_values, "
                   "indicator_calculation_runs IN ACCESS EXCLUSIVE MODE")
    # Refuse before DDL if rollback could discard any immutable OHLC/ATR history.
    if bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM indicator_input_evidence)
            OR EXISTS (SELECT 1 FROM indicator_series WHERE indicator_kind = 'atr')
            OR EXISTS (SELECT 1 FROM indicator_values WHERE indicator_kind = 'atr')
            OR EXISTS (SELECT 1 FROM indicator_calculation_runs WHERE status = 'completed')
    """)).scalar():
        raise RuntimeError("cannot downgrade immutable indicator history; preserve it and roll forward")
    if bind.dialect.name == "postgresql":
        _postgresql_contracts(False)
    _definitions(False)
    op.drop_column("indicator_input_evidence", "low")
    op.drop_column("indicator_input_evidence", "high")


def _postgresql_contracts(atr):
    ohlc_normalization = "NEW.high := trim_scale(NEW.high); NEW.low := trim_scale(NEW.low);" if atr else ""
    legacy_fields = "" if atr else " - ARRAY['high', 'low']"
    op.execute(f"""
        CREATE OR REPLACE FUNCTION indicator_common_fingerprint() RETURNS trigger
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
                {ohlc_normalization}
                payload := to_jsonb(NEW) - ARRAY['id', 'created_at', 'evidence_key']{legacy_fields};
                NEW.evidence_key := encode(sha256(convert_to(payload::text, 'UTF8')), 'hex');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    period_definition = (
        "CASE series.indicator_kind WHEN 'ema' THEN ARRAY[5,20,50,200] "
        "WHEN 'volume_sma' THEN ARRAY[50] WHEN 'atr' THEN ARRAY[14] END"
        if atr else "CASE WHEN series.indicator_kind = 'ema' THEN ARRAY[5,20,50,200] ELSE ARRAY[50] END"
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION indicator_require_complete_run_values(target_run_id integer) RETURNS void AS $$
        DECLARE series indicator_series; expected_periods integer[]; bad_date date;
        BEGIN
            SELECT s.* INTO series FROM indicator_series s JOIN indicator_calculation_runs r
                ON r.series_id = s.id WHERE r.id = target_run_id;
            expected_periods := {period_definition};
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
