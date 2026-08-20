"""Small, read-only Kiwoom REST client used by the price fallback source."""

from dataclasses import dataclass
from datetime import datetime
import time
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import KiwoomApiError, PriceFetchError
from app.core.metrics import increment_metric
from app.crawler.rate_limiter import CallsPerSecondLimiter
from app.crawler.retry import retryable_http_error


@dataclass(frozen=True)
class KiwoomChartResponse:
    payload: dict[str, Any]
    response_bytes: int
    status_code: int
    continuation: bool
    next_key: str | None
    retry_count: int = 0


class KiwoomRestClient:
    """OAuth client for Kiwoom chart TRs.

    The client intentionally exposes only a chart request; no order or account
    methods are included in the fallback integration.
    """

    def __init__(
        self,
        *,
        client: httpx.Client | Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            timeout=self.settings.kiwoom_request_timeout,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            follow_redirects=True,
        )
        self._limiter = CallsPerSecondLimiter(self.settings.kiwoom_requests_per_second)
        self.max_concurrency = self.settings.kiwoom_max_concurrency
        self._token: str | None = None
        self._token_type = "Bearer"
        self._token_expires_at = 0.0
        self._token_lock = Lock()

    @property
    def chart_url(self) -> str:
        return self.settings.kiwoom_api_base_url.rstrip("/") + "/api/dostk/chart"

    @property
    def token_url(self) -> str:
        return self.settings.kiwoom_api_base_url.rstrip("/") + "/oauth2/token"

    def _response_bytes(self, response: Any) -> int:
        content = getattr(response, "content", b"")
        if content:
            return len(content)
        text = getattr(response, "text", "")
        return len(text.encode("utf-8")) if text else 0

    def _raise_http_error(self, response: Any, *, url: str, attempt: int) -> None:
        status_code = getattr(response, "status_code", None)
        if status_code is None or status_code < 400:
            return
        if status_code == 429:
            increment_metric("kiwoom_rate_limit_errors")
        error = PriceFetchError(
            "kiwoom HTTP request failed",
            url=url,
            http_status=status_code,
            retry_count=attempt,
            response_bytes=self._response_bytes(response),
        )
        error.response = response  # type: ignore[attr-defined]
        raise error

    def _parse_json(self, response: Any, *, url: str, attempt: int) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise PriceFetchError(
                "kiwoom response is not valid JSON",
                url=url,
                http_status=getattr(response, "status_code", None),
                retry_count=attempt,
                response_bytes=self._response_bytes(response),
            ) from exc
        if not isinstance(payload, dict):
            raise PriceFetchError(
                "kiwoom response JSON must be an object",
                url=url,
                http_status=getattr(response, "status_code", None),
                retry_count=attempt,
                response_bytes=self._response_bytes(response),
            )
        return payload

    def _token_valid(self) -> bool:
        return bool(self._token) and time.time() < self._token_expires_at

    def _get_token(self, *, force_refresh: bool = False) -> str:
        with self._token_lock:
            if not force_refresh and self._token_valid():
                return self._token  # type: ignore[return-value]

            if not self.settings.kiwoom_app_key or not self.settings.kiwoom_secret_key:
                raise PriceFetchError(
                    "kiwoom credentials are not configured",
                    url=self.token_url,
                )

            self._limiter.wait()
            response = self._client.post(
                self.token_url,
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.settings.kiwoom_app_key,
                    "secretkey": self.settings.kiwoom_secret_key,
                },
            )
            self._raise_http_error(response, url=self.token_url, attempt=0)
            payload = self._parse_json(response, url=self.token_url, attempt=0)
            token = payload.get("token")
            if not token:
                raise KiwoomApiError(
                    str(payload.get("return_msg") or "kiwoom token was not returned"),
                    url=self.token_url,
                    api_code=payload.get("return_code"),
                    response_bytes=self._response_bytes(response),
                )

            self._token = str(token)
            self._token_type = str(payload.get("token_type") or "Bearer")
            self._token_expires_at = self._token_expiry(payload.get("expires_dt"))
            return self._token

    def _token_expiry(self, value: Any) -> float:
        now = time.time()
        if value:
            text = str(value).strip()
            try:
                parsed = datetime.strptime(text, "%Y%m%d%H%M%S").replace(
                    tzinfo=ZoneInfo("Asia/Seoul")
                )
                return max(now + 30, parsed.timestamp() - self.settings.kiwoom_token_refresh_margin_seconds)
            except ValueError:
                pass
        # Kiwoom returns an expiry timestamp in normal operation.  A bounded
        # fallback keeps a malformed expiry from causing a token request per TR.
        return now + 30 * 60

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        status_code = getattr(error, "http_status", None)
        if status_code is not None:
            return status_code == 429 or status_code >= 500
        return retryable_http_error(error)

    def fetch_daily_chart_page(
        self,
        code: str,
        *,
        base_date: str = "00000000",
        continuation: bool = False,
        next_key: str | None = None,
    ) -> KiwoomChartResponse:
        """Fetch one ``ka10081`` page and return continuation metadata."""
        last_error: Exception | None = None
        refreshed_after_unauthorized = False
        retry_count = 0
        while True:
            try:
                token = self._get_token()
                self._limiter.wait()
                headers = {
                    "authorization": f"{self._token_type} {token}",
                    "api-id": "ka10081",
                    "cont-yn": "Y" if continuation else "N",
                    "next-key": next_key or "",
                    "Content-Type": "application/json;charset=UTF-8",
                }
                response = self._client.post(
                    self.chart_url,
                    headers=headers,
                    json={
                        "stk_cd": code,
                        "base_dt": base_date,
                        "upd_stkpc_tp": self.settings.kiwoom_adjusted_price_type,
                    },
                )
                status_code = getattr(response, "status_code", None)
                if status_code == 401 and not refreshed_after_unauthorized:
                    with self._token_lock:
                        self._token = None
                        self._token_expires_at = 0.0
                    refreshed_after_unauthorized = True
                    continue

                self._raise_http_error(
                    response,
                    url=self.chart_url,
                    attempt=retry_count,
                )
                payload = self._parse_json(
                    response,
                    url=self.chart_url,
                    attempt=retry_count,
                )
                return_code = payload.get("return_code")
                if return_code not in (None, 0, "0"):
                    raise KiwoomApiError(
                        str(payload.get("return_msg") or "kiwoom chart request failed"),
                        url=self.chart_url,
                        api_code=return_code,
                        http_status=status_code,
                        retry_count=retry_count,
                        response_bytes=self._response_bytes(response),
                    )

                response_headers = getattr(response, "headers", {}) or {}
                cont_value = response_headers.get("cont-yn", payload.get("cont-yn", "N"))
                next_value = response_headers.get("next-key", payload.get("next-key"))
                return KiwoomChartResponse(
                    payload=payload,
                    response_bytes=self._response_bytes(response),
                    status_code=status_code or 200,
                    continuation=str(cont_value).upper() == "Y",
                    next_key=str(next_value) if next_value else None,
                    retry_count=retry_count,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if (
                    retry_count >= self.settings.kiwoom_max_retries
                    or not self._is_retryable(exc)
                ):
                    try:
                        exc.retry_count = retry_count  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    raise
                time.sleep(min(2**retry_count, 8))
                retry_count += 1

        raise last_error or RuntimeError("kiwoom chart request failed")
