import pytest

from app.crawler.krx_client import KrxHttpClient, KrxUniverseFetchError


class FakeResponse:
    status_code = 200
    content = b'{"OutBlock_1": []}'

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str], params: dict[str, str]):
        self.calls.append((url, headers, params))
        return self.response


def test_krx_client_sends_auth_key_only_as_header_and_preserves_bas_dd_parameter():
    http_client = FakeHttpClient(FakeResponse({"OutBlock_1": []}))
    client = KrxHttpClient(
        auth_key="test-secret",
        base_url="https://krx.test/svc/sample/apis/sto",
        http_client=http_client,
    )

    assert client.get_json("stk_bydd_trd", params={"basDd": "20200414"}) == {
        "OutBlock_1": []
    }
    assert http_client.calls == [
        (
            "https://krx.test/svc/sample/apis/sto/stk_bydd_trd.json",
            {"AUTH_KEY": "test-secret"},
            {"basDd": "20200414"},
        )
    ]


def test_krx_client_rejects_missing_auth_key_before_request():
    http_client = FakeHttpClient(FakeResponse({"OutBlock_1": []}))
    client = KrxHttpClient(
        auth_key=None,
        base_url="https://krx.test/svc/sample/apis/sto",
        http_client=http_client,
    )

    with pytest.raises(KrxUniverseFetchError, match="KRX_AUTH_KEY"):
        client.get_json("stk_bydd_trd", params={"basDd": "20200414"})

    assert http_client.calls == []


def test_krx_client_rejects_missing_base_url_before_request():
    http_client = FakeHttpClient(FakeResponse({"OutBlock_1": []}))
    client = KrxHttpClient(
        auth_key="test-secret",
        base_url=None,
        http_client=http_client,
    )

    with pytest.raises(KrxUniverseFetchError, match="KRX_API_BASE_URL"):
        client.get_json("stk_bydd_trd", params={"basDd": "20200414"})

    assert http_client.calls == []


def test_krx_client_uses_configured_full_endpoint_for_etp_feed():
    http_client = FakeHttpClient(FakeResponse({"OutBlock_1": []}))
    client = KrxHttpClient(
        auth_key="test-secret",
        base_url="https://krx.test/svc/apis/sto",
        endpoint_urls={"etf_bydd_trd": "https://krx.test/svc/apis/etp/etf_bydd_trd"},
        http_client=http_client,
    )

    client.get_json("etf_bydd_trd", params={"basDd": "20200414"})

    assert http_client.calls[0][0] == "https://krx.test/svc/apis/etp/etf_bydd_trd.json"
