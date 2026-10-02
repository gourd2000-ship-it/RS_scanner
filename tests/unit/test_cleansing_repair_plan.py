"""감사 결측으로부터 요청 예산이 있는 복구 후보만 만든다."""

import csv
import json

from app.services.validation.cleansing_repair import build_repair_plan


def test_repair_plan_keeps_delisted_excluded_and_respects_zero_budget(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"end": "2020-01-03"}))
    with (tmp_path / "gaps.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "trade_date", "reason"))
        writer.writerow((1, "000001", "2020-01-02", "price_missing"))
        writer.writerow((1, "000001", "2020-01-03", "price_missing"))
        writer.writerow((2, "000002", "2020-01-02", "price_missing"))
    with (tmp_path / "excluded_universe.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "reason"))
        writer.writerow((2, "000002", "delisted_by_selection_date"))
    plan = build_repair_plan(tmp_path, request_budget=0)
    assert plan.targets == ()
    assert plan.pending_instrument_count == 1
    assert plan.excluded_delisted_count == 1
    approved_budget = build_repair_plan(tmp_path, request_budget=1)
    assert [(item.instrument_id, item.dates) for item in approved_budget.targets] == [
        (1, ("2020-01-02", "2020-01-03"))
    ]
    assert approved_budget.manifest_hash == build_repair_plan(tmp_path, request_budget=1).manifest_hash


def test_repair_budget_counts_pagination_back_to_oldest_gap(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"end": "2026-09-04"}))
    with (tmp_path / "gaps.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "trade_date", "reason"))
        writer.writerow((1, "000001", "2013-01-02", "price_missing"))
    with (tmp_path / "excluded_universe.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "reason"))
    assert build_repair_plan(tmp_path, request_budget=1).targets == ()
    assert build_repair_plan(tmp_path, request_budget=10).targets[0].estimated_requests > 1
