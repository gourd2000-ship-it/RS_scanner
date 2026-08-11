import httpx
from time import perf_counter

from app.core.config import get_settings
from app.core.metrics import record_provider_request
from app.crawler.rate_limiter import RateLimiter
from app.crawler.retry import retryable_http_error, with_retry


class NaverHttpClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = httpx.Client(
            timeout=settings.naver_request_timeout,
            headers={"User-Agent": settings.naver_user_agent},
            follow_redirects=True,
        )
        self._rate_limiter = RateLimiter(
            min_delay_ms=settings.naver_min_delay_ms,
            max_delay_ms=settings.naver_max_delay_ms,
        )
        self._max_retries = settings.naver_max_retries
        self.max_concurrency = settings.naver_max_concurrency

    def get(self, url: str) -> str:
        def _request() -> str:
            started = perf_counter()
            try:
                self._rate_limiter.sleep()
                response = self._client.get(url)
                response.raise_for_status()
                record_provider_request(
                    "naver",
                    elapsed_seconds=perf_counter() - started,
                    success=True,
                )
                return response.text
            except Exception:
                record_provider_request(
                    "naver",
                    elapsed_seconds=perf_counter() - started,
                    success=False,
                )
                raise

        return with_retry(
            _request,
            max_retries=self._max_retries,
            retryable=retryable_http_error,
        )
