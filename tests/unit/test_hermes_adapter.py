import httpx
import pytest

from app.integrations.hermes_adapter import (
    HermesAdapter,
    HermesAuthError,
    HermesRateLimitError,
    HermesUpstreamError,
)


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = httpx.Headers(headers or {})

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, params=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self):
        return None


def make_adapter(client, sleeps=None, **kwargs):
    sleeps = [] if sleeps is None else sleeps
    return HermesAdapter(
        base_url="https://scanner.example/api/v1/agent/v1",
        token="service-token",
        client=client,
        sleep=sleeps.append,
        **kwargs,
    )


def test_adapter_exposes_versioned_endpoints_and_auth_header():
    client = FakeClient([FakeResponse(200, {"ok": True}) for _ in range(4)])
    adapter = make_adapter(client)

    assert adapter.get_data_status() == {"ok": True}
    adapter.get_rs_briefing(size=5)
    adapter.get_stock_snapshot("005930")
    adapter.get_stock_history("005930", limit=30)

    assert [call["url"] for call in client.calls] == [
        "https://scanner.example/api/v1/agent/v1/status",
        "https://scanner.example/api/v1/agent/v1/briefing",
        "https://scanner.example/api/v1/agent/v1/stocks/005930",
        "https://scanner.example/api/v1/agent/v1/stocks/005930/history",
    ]
    assert client.calls[0]["headers"] == {"Authorization": "Bearer service-token"}
    assert client.calls[1]["params"] == {"size": 5}
    assert client.calls[3]["params"] == {"limit": 30}


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_are_not_retried(status_code):
    client = FakeClient([FakeResponse(status_code, {"detail": "denied"})])
    adapter = make_adapter(client, max_retries=2)

    with pytest.raises(HermesAuthError) as error:
        adapter.get_data_status()

    assert error.value.status_code == status_code
    assert len(client.calls) == 1


def test_rate_limit_retries_with_retry_after_then_returns_payload():
    client = FakeClient([
        FakeResponse(429, {"detail": "slow down"}, {"Retry-After": "0"}),
        FakeResponse(200, {"data_status": "complete"}),
    ])
    sleeps = []
    adapter = make_adapter(client, sleeps=sleeps, max_retries=1)

    assert adapter.get_data_status() == {"data_status": "complete"}
    assert len(client.calls) == 2
    assert sleeps == [0.0]


def test_upstream_and_transport_failures_are_retried():
    client = FakeClient([
        FakeResponse(503, {"detail": "unavailable"}),
        httpx.ConnectError("connection reset"),
        FakeResponse(200, {"data_status": "complete"}),
    ])
    sleeps = []
    adapter = make_adapter(client, sleeps=sleeps, max_retries=2)

    assert adapter.get_data_status() == {"data_status": "complete"}
    assert len(client.calls) == 3
    assert sleeps == [1, 2]


def test_exhausted_rate_limit_and_upstream_errors_are_typed():
    rate_client = FakeClient([FakeResponse(429, {}, {"Retry-After": "3"})])
    with pytest.raises(HermesRateLimitError) as rate_error:
        make_adapter(rate_client, max_retries=0).get_data_status()
    assert rate_error.value.retry_after == "3"

    upstream_client = FakeClient([FakeResponse(502, {})])
    with pytest.raises(HermesUpstreamError) as upstream_error:
        make_adapter(upstream_client, max_retries=0).get_data_status()
    assert upstream_error.value.status_code == 502
