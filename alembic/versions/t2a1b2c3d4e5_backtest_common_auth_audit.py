"""Add CSRF state and credential-safe backtest operator audit events.

Revision ID: t2a1b2c3d4e5
Revises: s2c3d4e5f6a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t2a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "s2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing installations have no browser sessions before this feature;
    # the temporary default is removed immediately after backfill.
    with op.batch_alter_table("backtest_operator_sessions") as batch:
        batch.add_column(sa.Column("csrf_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("is_operator", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE backtest_operator_sessions SET csrf_token_hash = session_token_hash WHERE csrf_token_hash IS NULL")
    with op.batch_alter_table("backtest_operator_sessions") as batch:
        batch.alter_column("csrf_token_hash", nullable=False)
        batch.alter_column("is_operator", server_default=None)
    op.create_table(
        "backtest_operator_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_backtest_operator_audit_events_subject_hash", "backtest_operator_audit_events", ["subject_hash"])
    op.create_index("ix_backtest_operator_audit_subject_time", "backtest_operator_audit_events", ["subject_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_backtest_operator_audit_subject_time", table_name="backtest_operator_audit_events")
    op.drop_index("ix_backtest_operator_audit_events_subject_hash", table_name="backtest_operator_audit_events")
    op.drop_table("backtest_operator_audit_events")
    with op.batch_alter_table("backtest_operator_sessions") as batch:
        batch.drop_column("is_operator")
        batch.drop_column("csrf_token_hash")
