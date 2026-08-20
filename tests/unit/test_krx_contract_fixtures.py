import json
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "krx"


@pytest.mark.parametrize(
    ("fixture_name", "required_fields"),
    [
        (
            "kospi_isu_base_info_success.json",
            {"ISU_CD", "ISU_SRT_CD", "ISU_NM", "LIST_DD", "MKT_TP_NM"},
        ),
        (
            "kosdaq_isu_base_info_success.json",
            {"ISU_CD", "ISU_SRT_CD", "ISU_NM", "LIST_DD", "MKT_TP_NM"},
        ),
        (
            "etf_bydd_trd_success.json",
            {"BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC"},
        ),
        (
            "etn_bydd_trd_success.json",
            {"BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "PER1SECU_INDIC_VAL"},
        ),
        (
            "stk_bydd_trd_success.json",
            {"BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "TDD_CLSPRC"},
        ),
        (
            "ksq_bydd_trd_success.json",
            {"BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "TDD_CLSPRC"},
        ),
    ],
)
def test_krx_success_fixtures_preserve_the_approved_response_contract(
    fixture_name: str,
    required_fields: set[str],
):
    payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))

    assert isinstance(payload["OutBlock_1"], list)
    assert payload["OutBlock_1"]
    assert required_fields <= set(payload["OutBlock_1"][0])
    assert "AUTH_KEY" not in json.dumps(payload)


def test_krx_non_success_fixtures_are_redacted_and_explicitly_synthetic():
    for fixture_name in ("empty_response.json", "unauthorized_response.json", "as_of_date_mismatch.json"):
        payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        assert payload["fixture_kind"] in {"empty", "unauthorized", "as_of_date_mismatch"}
        assert "AUTH_KEY" not in json.dumps(payload)
