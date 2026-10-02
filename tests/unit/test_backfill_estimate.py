"""BT12 실행 추정은 probe의 실측값과 요청 상한을 명시적으로 보존한다."""

from datetime import date

from app.services.backfill_estimate import BackfillProbe, estimate_backfill
from app.services.historical_backfill import HistoricalBackfillPlan, HistoricalBackfillTarget, plan_from_serialized


def _plan() -> HistoricalBackfillPlan:
    return HistoricalBackfillPlan(
        start=date(2020, 1, 1), end=date(2020, 12, 31), provider="kiwoom",
        adjustment_type="1", base_date="20261231", request_budget=3,
        targets=(
            HistoricalBackfillTarget(1, "000001", 1, "KOSPI", tuple(date(2020, 1, day) for day in range(1, 11))),
            HistoricalBackfillTarget(2, "000002", 2, "KOSDAQ", tuple(date(2020, 2, day) for day in range(1, 11))),
        ),
    )


def test_estimate_scales_measured_probe_and_requires_multiple_runs_when_budget_is_too_small():
    estimate = estimate_backfill(
        _plan(),
        BackfillProbe(
            expected_rows=5, request_count=2, retry_count=1,
            fetch_seconds=4.0, store_seconds=1.0, validation_seconds=2.0,
            rs_seconds=3.0, response_bytes=1_000, database_bytes=2_000,
        ),
    )

    assert estimate.expected_rows == 20
    assert estimate.projected_requests == 8
    assert estimate.projected_fetch_seconds == 16.0
    assert estimate.projected_database_bytes == 8_000
    assert estimate.minimum_runs == 3
    assert estimate.within_request_budget is False
    assert estimate.retry_rate == 0.5


def test_plan_from_serialized_restores_the_exact_frozen_manifest():
    plan = HistoricalBackfillPlan(
        start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom", adjustment_type="1",
        base_date="20260103", request_budget=500,
        targets=(HistoricalBackfillTarget(7, "005930", 11, "KOSPI", (date(2020, 1, 2), date(2020, 1, 3))),),
    )

    restored = plan_from_serialized(plan.serialized())

    assert restored.serialized() == plan.serialized()
    assert restored.manifest_hash == plan.manifest_hash
