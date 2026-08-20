from app.core.config import Settings
from app.crawler.kiwoom_client import KiwoomRestClient


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.content = str(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self):
        self.calls = []
        self.responses = [
            FakeResponse(
                {
                    "token": "token-1",
                    "token_type": "Bearer",
                    "expires_dt": "20991231235959",
                }
            ),
            FakeResponse(
                {
                    "return_code": 0,
                    "stk_dt_pole_chart_qry": [],
                },
                headers={"cont-yn": "Y", "next-key": "next-1"},
            ),
        ]

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class UnauthorizedOnceHttpClient(FakeHttpClient):
    def __init__(self):
        self.calls = []
        self.responses = [
            FakeResponse(
                {
                    "token": "token-1",
                    "token_type": "Bearer",
                    "expires_dt": "20991231235959",
                }
            ),
            FakeResponse({}, status_code=401),
            FakeResponse(
                {
                    "token": "token-2",
                    "token_type": "Bearer",
                    "expires_dt": "20991231235959",
                }
            ),
            FakeResponse({"return_code": 0, "rows": []}),
        ]


def make_settings() -> Settings:
    return Settings(
        KIWOOM_APP_KEY="app-key",
        KIWOOM_SECRET_KEY="secret-key",
        KIWOOM_REQUESTS_PER_SECOND=5,
        KIWOOM_MAX_RETRIES=0,
    )


def test_kiwoom_client_authenticates_and_requests_chart_without_order_api():
    http = FakeHttpClient()
    client = KiwoomRestClient(client=http, settings=make_settings())

    response = client.fetch_daily_chart_page("005930")

    assert response.continuation is True
    assert response.next_key == "next-1"
    assert http.calls[0][0].endswith("/oauth2/token")
    assert http.calls[0][1]["json"] == {
        "grant_type": "client_credentials",
        "appkey": "app-key",
        "secretkey": "secret-key",
    }
    chart_url, chart_kwargs = http.calls[1]
    assert chart_url.endswith("/api/dostk/chart")
    assert chart_kwargs["headers"]["api-id"] == "ka10081"
    assert chart_kwargs["headers"]["authorization"] == "Bearer token-1"
    assert chart_kwargs["json"]["stk_cd"] == "005930"
    assert chart_kwargs["json"]["upd_stkpc_tp"] == "1"
    assert "ord" not in chart_kwargs["headers"]["api-id"].lower()


def test_kiwoom_client_reuses_token_for_second_chart_request():
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"return_code": 0, "rows": []}))
    client = KiwoomRestClient(client=http, settings=make_settings())

    client.fetch_daily_chart_page("005930")
    client.fetch_daily_chart_page("000660")

    assert len([url for url, _kwargs in http.calls if url.endswith("/oauth2/token")]) == 1


def test_kiwoom_client_refreshes_expired_token_even_without_retry_budget():
    http = UnauthorizedOnceHttpClient()
    client = KiwoomRestClient(client=http, settings=make_settings())

    response = client.fetch_daily_chart_page("005930")

    assert response.status_code == 200
    assert [url for url, _kwargs in http.calls if url.endswith("/oauth2/token")] == [
        "https://api.kiwoom.com/oauth2/token",
        "https://api.kiwoom.com/oauth2/token",
    ]
