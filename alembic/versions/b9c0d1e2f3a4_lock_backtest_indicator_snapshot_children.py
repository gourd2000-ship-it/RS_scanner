"""Serialize snapshot completion with child insertion.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE OR REPLACE FUNCTION backtest_indicator_snapshot_child_guard() RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members are immutable';
            END IF;
            SELECT status INTO parent_status
            FROM backtest_dataset_indicator_snapshots
            WHERE id = NEW.snapshot_id FOR UPDATE;
            IF parent_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members can only be inserted while building';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE OR REPLACE FUNCTION backtest_indicator_snapshot_child_guard() RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members are immutable';
            END IF;
            SELECT status INTO parent_status
            FROM backtest_dataset_indicator_snapshots
            WHERE id = NEW.snapshot_id FOR KEY SHARE;
            IF parent_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members can only be inserted while building';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
