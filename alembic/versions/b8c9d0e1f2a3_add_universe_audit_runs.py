"""Add approved universe audit runs and legacy symbol metadata.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "universe_audit_runs" not in tables:
        op.create_table(
            "universe_audit_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("snapshot_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("requested_by", sa.String(length=100), nullable=False),
            sa.Column("approved_by", sa.String(length=100), nullable=True),
            sa.Column("applied_by", sa.String(length=100), nullable=True),
            sa.Column("report", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["snapshot_id"], ["symbol_universe_snapshots.id"]),
        )
        op.create_index("ix_universe_audit_runs_snapshot_id", "universe_audit_runs", ["snapshot_id"])
        op.create_index("ix_universe_audit_runs_status", "universe_audit_runs", ["status"])
        op.create_index("ix_universe_audit_runs_status_created", "universe_audit_runs", ["status", "created_at"])

    if "universe_audit_decisions" not in tables:
        op.create_table(
            "universe_audit_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("symbol_id", sa.Integer(), nullable=True),
            sa.Column("original_code", sa.String(length=20), nullable=False),
            sa.Column("replacement_code", sa.String(length=20), nullable=True),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("action", sa.String(length=30), nullable=False, server_default="deactivate"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("approved_by", sa.String(length=100), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["universe_audit_runs.id"]),
            sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
            sa.UniqueConstraint("run_id", "symbol_id", name="uq_universe_audit_decision_run_symbol"),
        )
        op.create_index("ix_universe_audit_decisions_run_id", "universe_audit_decisions", ["run_id"])
        op.create_index("ix_universe_audit_decisions_symbol_id", "universe_audit_decisions", ["symbol_id"])
        op.create_index("ix_universe_audit_decisions_original_code", "universe_audit_decisions", ["original_code"])
        op.create_index("ix_universe_audit_decisions_status", "universe_audit_decisions", ["status"])
        op.create_index("ix_universe_audit_decisions_run_status", "universe_audit_decisions", ["run_id", "status"])

    symbol_columns = {column["name"] for column in inspector.get_columns("symbols")}
    if "legacy_state" not in symbol_columns:
        op.add_column("symbols", sa.Column("legacy_state", sa.String(length=30), nullable=True))
        op.create_index("ix_symbols_legacy_state", "symbols", ["legacy_state"])
    if "legacy_reason" not in symbol_columns:
        op.add_column("symbols", sa.Column("legacy_reason", sa.Text(), nullable=True))
    if "legacy_audit_run_id" not in symbol_columns:
        op.add_column("symbols", sa.Column("legacy_audit_run_id", sa.Integer(), nullable=True))
        op.create_index("ix_symbols_legacy_audit_run_id", "symbols", ["legacy_audit_run_id"])
        op.create_foreign_key(
            "fk_symbols_legacy_audit_run_id",
            "symbols",
            "universe_audit_runs",
            ["legacy_audit_run_id"],
            ["id"],
        )


def downgrade() -> None:
    op.drop_constraint("fk_symbols_legacy_audit_run_id", "symbols", type_="foreignkey")
    op.drop_index("ix_symbols_legacy_audit_run_id", table_name="symbols")
    op.drop_column("symbols", "legacy_audit_run_id")
    op.drop_column("symbols", "legacy_reason")
    op.drop_index("ix_symbols_legacy_state", table_name="symbols")
    op.drop_column("symbols", "legacy_state")
    op.drop_table("universe_audit_decisions")
    op.drop_table("universe_audit_runs")
