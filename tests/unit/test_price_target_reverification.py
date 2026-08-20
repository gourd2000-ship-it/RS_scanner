from types import SimpleNamespace

from app.services.price_target_reverification import (
    build_price_target_result_verification,
)


def target(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


def test_reverification_uses_price_results_and_confirms_target_count():
    report = build_price_target_result_verification(
        job_id=42,
        job_status="completed",
        recorded_target_count=3,
        price_results=[target("fetched"), target("no_new_data"), target("failed")],
        eod_results=[target("fetched")],
    )

    assert report.result_step == "prices"
    assert report.result_count == 3
    assert report.target_count_matches_results is True
    assert report.status_counts == {
        "failed": 1,
        "fetched": 1,
        "no_new_data": 1,
    }


def test_reverification_falls_back_to_eod_and_reports_count_mismatch():
    report = build_price_target_result_verification(
        job_id=43,
        job_status="completed_with_errors",
        recorded_target_count=4,
        price_results=[],
        eod_results=[target("fetched"), target("partial")],
    )

    assert report.result_step == "eod"
    assert report.result_count == 2
    assert report.target_count_matches_results is False
    assert report.to_dict()["verifiable"] is True
