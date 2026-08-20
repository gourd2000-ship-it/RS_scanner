import json
from datetime import date
from pathlib import Path

from app.crawler.sources.krx import KrxUniverseSource


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "krx"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class FixtureKrxClient:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, api_id: str, *, params: dict[str, str]) -> dict:
        self.calls.append((api_id, params))
        payload = self.payloads[api_id]
        if isinstance(payload, Exception):
            raise payload
        return payload


class DateAwareKrxClient:
    def __init__(self, payloads: dict[tuple[str, str], dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, api_id: str, *, params: dict[str, str]) -> dict:
        self.calls.append((api_id, params))
        return self.payloads[(api_id, params["basDd"])]


def test_source_fetches_both_stock_markets_as_one_complete_membership_result():
    client = FixtureKrxClient(
        {
            "stk_bydd_trd": load_fixture("stk_bydd_trd_success.json"),
            "ksq_bydd_trd": load_fixture("ksq_bydd_trd_success.json"),
        }
    )

    result = KrxUniverseSource(client).fetch_stock_membership(date(2020, 4, 14))

    assert result.complete is True
    assert result.as_of_date == date(2020, 4, 14)
    assert {member.market for member in result.members} == {"KOSPI", "KOSDAQ"}
    assert client.calls == [
        ("stk_bydd_trd", {"basDd": "20200414"}),
        ("ksq_bydd_trd", {"basDd": "20200414"}),
    ]


def test_source_returns_incomplete_result_when_one_market_response_is_invalid():
    client = FixtureKrxClient(
        {
            "stk_bydd_trd": load_fixture("stk_bydd_trd_success.json"),
            "ksq_bydd_trd": {"OutBlock_1": []},
        }
    )

    result = KrxUniverseSource(client).fetch_stock_membership(date(2020, 4, 14))

    assert result.complete is False
    assert {member.security_type for member in result.members} == {"stock"}
    assert all(member.market == "KOSPI" for member in result.members)
    assert "KOSDAQ" in (result.error_message or "")


def test_source_uses_previous_open_day_when_both_current_day_feeds_are_not_published():
    client = DateAwareKrxClient(
        {
            ("stk_bydd_trd", "20200415"): {"OutBlock_1": []},
            ("ksq_bydd_trd", "20200415"): {"OutBlock_1": []},
            ("stk_bydd_trd", "20200414"): load_fixture("stk_bydd_trd_success.json"),
            ("ksq_bydd_trd", "20200414"): load_fixture("ksq_bydd_trd_success.json"),
        }
    )

    result = KrxUniverseSource(client).fetch_latest_stock_membership(date(2020, 4, 15))

    assert result.complete is True
    assert result.as_of_date == date(2020, 4, 14)
    assert client.calls == [
        ("stk_bydd_trd", {"basDd": "20200415"}),
        ("ksq_bydd_trd", {"basDd": "20200415"}),
        ("stk_bydd_trd", {"basDd": "20200414"}),
        ("ksq_bydd_trd", {"basDd": "20200414"}),
    ]


def test_source_collects_etf_and_etn_as_separate_shadow_observations():
    client = FixtureKrxClient(
        {
            "stk_bydd_trd": load_fixture("stk_bydd_trd_success.json"),
            "ksq_bydd_trd": load_fixture("ksq_bydd_trd_success.json"),
            "etf_bydd_trd": load_fixture("etf_bydd_trd_success.json"),
            "etn_bydd_trd": load_fixture("etn_bydd_trd_success.json"),
        }
    )

    result = KrxUniverseSource(client).fetch_etp_observations(date(2020, 4, 14))

    assert result.complete is True
    assert {member.security_type for member in result.members} == {"etf", "etn"}
    assert {member.code for member in result.members} >= {"253150", "500052"}
    assert [api_id for api_id, _ in client.calls] == [
        "etf_bydd_trd",
        "etn_bydd_trd",
    ]
