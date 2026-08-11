"""Hermes Agent API client with bounded retry policy."""

from collections.abc import Callable
import time
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings


class HermesAdapterError(RuntimeError):
    """Base error raised by the Hermes adapter."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class HermesAuthError(HermesAdapterError):
    """Hermes rejected the service token."""


class HermesRateLimitError(HermesAdapterError):
    """Hermes rate-limited the request after retries were exhausted."""

    def __init__(self, message: str, *, status_code: int | None = None, retry_after: str | None = None):
        super().__init__(message, status_code=status_code, retryable=True)
        self.retry_after = retry_after


class HermesUpstreamError(HermesAdapterError):
    """Hermes or its transport failed after retries were exhausted."""


class HermesAdapter:
    """Small, provider-independent client for the Hermes agent facade."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = get_settings()
        configured_base_url = base_url if base_url is not None else settings.hermes_api_base_url
        self.base_url = configured_base_url.rstrip("/") + "/"
        self.token = token if token is not None else settings.hermes_service_token
        self.timeout = timeout if timeout is not None else settings.hermes_request_timeout
        self.max_retries = max_retries if max_retries is not None else settings.hermes_max_retries
        self._client = client or httpx.Client(timeout=self.timeout)
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def get_data_status(self) -> dict:
        return self._get("status")

    def get_rs_briefing(self, *, size: int = 10) -> dict:
        return self._get("briefing", params={"size": size})

    def get_stock_snapshot(self, code: str) -> dict:
        return self._get(f"stocks/{code}")

    def get_stock_history(self, code: str, *, limit: int = 90) -> dict:
        return self._get(f"stocks/{code}/history", params={"limit": limit})

    def _get(self, path: str, *, params: dict[str, object] | None = None) -> dict:
        if not self.base_url.strip("/"):
            raise HermesAdapterError("HERMES_API_BASE_URL is not configured")
        if not self.token:
            raise HermesAuthError("HERMES_SERVICE_TOKEN is not configured")

        url = urljoin(self.base_url, path.lstrip("/"))
        headers = {"Authorization": f"Bearer {self.token}"}

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    self._sleep(2**attempt)
                    continue
                raise HermesUpstreamError("Hermes transport request failed", retryable=True) from exc

            if response.status_code in {401, 403}:
                raise HermesAuthError("Hermes authentication failed", status_code=response.status_code)

            if response.status_code == 429:
                if attempt < self.max_retries:
                    self._sleep(self._retry_delay(response, attempt))
                    continue
                raise HermesRateLimitError(
                    "Hermes rate limit exceeded",
                    status_code=response.status_code,
                    retry_after=response.headers.get("Retry-After"),
                )

            if response.status_code >= 500:
                if attempt < self.max_retries:
                    self._sleep(2**attempt)
                    continue
                raise HermesUpstreamError(
                    "Hermes upstream request failed",
                    status_code=response.status_code,
                    retryable=True,
                )

            if response.status_code >= 400:
                raise HermesAdapterError(
                    "Hermes request failed",
                    status_code=response.status_code,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise HermesUpstreamError("Hermes returned invalid JSON", retryable=False) from exc
            if not isinstance(payload, dict):
                raise HermesUpstreamError("Hermes returned an unexpected payload", retryable=False)
            return payload

        raise HermesUpstreamError("Hermes request failed", retryable=True)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return float(2**attempt)
