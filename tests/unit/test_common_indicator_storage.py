"""Common evidence does not duplicate immutable source facts per indicator."""
from sqlalchemy import inspect
from app.models.indicator import IndicatorInputPolicy, IndicatorInputEvidence, IndicatorRunInput


def test_common_evidence_is_independent_of_runs_and_requires_nonnull_key():
    columns = inspect(IndicatorInputEvidence).columns
    assert not columns.evidence_key.nullable
    assert 'calculation_run_id' not in columns
    assert 'close' in columns and 'volume' in columns
    assert not inspect(IndicatorInputPolicy).columns.fingerprint.nullable
    assert not inspect(IndicatorRunInput).columns.ordinal.nullable


def test_common_evidence_copies_high_low_without_extending_legacy_snapshot():
    from app.models.indicator import IndicatorInputSnapshot
    assert {'high', 'low'} <= set(inspect(IndicatorInputEvidence).columns.keys())
    assert not {'high', 'low'} & set(inspect(IndicatorInputSnapshot).columns.keys())
