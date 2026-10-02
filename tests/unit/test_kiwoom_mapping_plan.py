from datetime import date

from app.services.kiwoom_mapping_materialization import (
    CurrentMappingCandidate,
    plan_kiwoom_current_mappings,
)


def test_plan_adds_kiwoom_mapping_only_when_current_symbol_and_naver_code_are_exact():
    plan = plan_kiwoom_current_mappings([
        CurrentMappingCandidate(7, "005930", "KOSPI", date(1975, 6, 11), "listed", "005930", "KOSPI", "005930", False),
        CurrentMappingCandidate(8, "123456", "KOSDAQ", date(2020, 1, 1), "listed", "123456", "KOSDAQ", "654321", False),
    ])

    assert [(row.instrument_id, row.provider_symbol, row.valid_from) for row in plan.creates] == [
        (7, "005930", date(1975, 6, 11)),
    ]
    assert plan.unresolved == [{"instrument_id": 8, "reason": "non_exact_current_evidence"}]
