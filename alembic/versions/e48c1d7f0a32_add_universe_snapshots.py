"""Add symbol universe snapshots and last-seen fields.

Revision ID: e48c1d7f0a32
Revises: d31b0f6e7a21
Create Date: 2026-08-11 00:00:00
"""

from typing import Sequence, Union

from alembic import context
from alembic import op
import sqlalchemy as sa


revision: str = "e48c1d7f0a32"
down_revision: Union[str, Sequence[str], None] = "d31b0f6e7a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector() -> sa.Inspector | None:
    if context.is_offline_mode():
        return None
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    inspector = _inspector()
    return False if inspector is None else inspector.has_table(name)


def _has_column(table: str, column: str) -> bool:
    inspector = _inspector()
    if inspector is None:
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    inspector = _inspector()
    if inspector is None:
        return False
    return name in {item["name"] for item in inspector.get_indexes(table)}


def _has_foreign_key(table: str, name: str) -> bool:
    inspector = _inspector()
    if inspector is None:
        return False
    return name in {item.get("name") for item in inspector.get_foreign_keys(table)}


def upgrade() -> None:
    if not _has_table("symbol_universe_snapshots"):
        op.create_table(
            "symbol_universe_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("pages_total", sa.Integer(), nullable=False),
            sa.Column("pages_succeeded", sa.Integer(), nullable=False),
            sa.Column("symbols_seen", sa.Integer(), nullable=False),
            sa.Column("symbols_valid", sa.Integer(), nullable=False),
            sa.Column("duplicate_count", sa.Integer(), nullable=False),
            sa.Column("invalid_count", sa.Integer(), nullable=False),
            sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("symbol_universe_snapshots", "ix_symbol_universe_snapshots_job_id"):
        op.create_index(op.f("ix_symbol_universe_snapshots_job_id"), "symbol_universe_snapshots", ["job_id"], unique=False)
    if not _has_index("symbol_universe_snapshots", "ix_universe_snapshots_market_started"):
        op.create_index("ix_universe_snapshots_market_started", "symbol_universe_snapshots", ["market", "started_at"], unique=False)
    if not _has_index("symbol_universe_snapshots", "ix_universe_snapshots_status"):
        op.create_index("ix_universe_snapshots_status", "symbol_universe_snapshots", ["status"], unique=False)

    if not _has_column("symbols", "last_seen_at"):
        op.add_column("symbols", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    if not _has_column("symbols", "last_snapshot_id"):
        op.add_column("symbols", sa.Column("last_snapshot_id", sa.Integer(), nullable=True))
    if not _has_index("symbols", "ix_symbols_last_snapshot_id"):
        op.create_index(op.f("ix_symbols_last_snapshot_id"), "symbols", ["last_snapshot_id"], unique=False)
    if not _has_foreign_key("symbols", "fk_symbols_last_snapshot_id"):
        op.create_foreign_key("fk_symbols_last_snapshot_id", "symbols", "symbol_universe_snapshots", ["last_snapshot_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_symbols_last_snapshot_id", "symbols", type_="foreignkey")
    op.drop_index(op.f("ix_symbols_last_snapshot_id"), table_name="symbols")
    op.drop_column("symbols", "last_snapshot_id")
    op.drop_column("symbols", "last_seen_at")
    op.drop_index("ix_universe_snapshots_status", table_name="symbol_universe_snapshots")
    op.drop_index("ix_universe_snapshots_market_started", table_name="symbol_universe_snapshots")
    op.drop_index(op.f("ix_symbol_universe_snapshots_job_id"), table_name="symbol_universe_snapshots")
    op.drop_table("symbol_universe_snapshots")
