import json
from datetime import date
from pathlib import Path

import pytest

from app.crawler.parsers.krx import KrxUniverseParseError, parse_krx_stock_membership


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "krx"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_parser_preserves_leading_zero_code_and_zero_trade_membership():
    payload = load_fixture("ksq_bydd_trd_success.json")

    members = parse_krx_stock_membership(
        payload,
        expected_market="KOSDAQ",
        expected_as_of_date=date(2020, 4, 14),
    )

    assert [(member.code, member.name) for member in members] == [
        ("950170", "JTC"),
        ("900100", "뉴프라이드"),
    ]
    assert members[1].listing_status == "listed_observed"
    assert members[1].trading_status == "unknown"
    assert members[1].raw_fields["ACC_TRDVOL"] == "0"


def test_parser_rejects_market_or_as_of_date_mismatch():
    payload = load_fixture("stk_bydd_trd_success.json")

    with pytest.raises(KrxUniverseParseError, match="기준일"):
        parse_krx_stock_membership(
            payload,
            expected_market="KOSPI",
            expected_as_of_date=date(2020, 4, 15),
        )

    with pytest.raises(KrxUniverseParseError, match="시장"):
        parse_krx_stock_membership(
            payload,
            expected_market="KOSDAQ",
            expected_as_of_date=date(2020, 4, 14),
        )


def test_parser_rejects_empty_or_duplicate_code_response():
    with pytest.raises(KrxUniverseParseError, match="비어"):
        parse_krx_stock_membership(
            {"OutBlock_1": []},
            expected_market="KOSPI",
            expected_as_of_date=date(2020, 4, 14),
        )

    duplicate_payload = {
        "OutBlock_1": [
            {
                "BAS_DD": "20200414",
                "ISU_CD": "005930",
                "ISU_NM": "삼성전자",
                "MKT_NM": "KOSPI",
            },
            {
                "BAS_DD": "20200414",
                "ISU_CD": "005930",
                "ISU_NM": "삼성전자",
                "MKT_NM": "KOSPI",
            },
        ]
    }

    with pytest.raises(KrxUniverseParseError, match="중복"):
        parse_krx_stock_membership(
            duplicate_payload,
            expected_market="KOSPI",
            expected_as_of_date=date(2020, 4, 14),
        )
