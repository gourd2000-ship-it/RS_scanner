"""Prove real PostgreSQL constraints for observation and identity ingestion."""

from datetime import date

from tests.integration.test_backtest_worker_postgres import postgres_sessions  # noqa: F401
from tests.unit.test_daily_indicator_source import (
    seed_source,
    test_plan_does_not_write_and_apply_appends_identity_without_canonical_prices as verify_append,
    test_changed_overlap_is_rejected_without_mixing_adjustment_bases as verify_revision,
)


def test_postgres_source_append_identity_reuse_and_revision_guard(postgres_sessions):
    with postgres_sessions() as session:
        seed_source(session)
        verify_revision(session)
        verify_append(session)
