import random
import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def with_retry(
    func: Callable[[], T],
    *,
    max_retries: int,
    base_delay_seconds: float = 1.0,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            if attempt >= max_retries or (retryable and not retryable(exc)):
                # Preserve the number of retries for crawl observability without
                # changing the exception type expected by existing callers.
                try:
                    exc.retry_count = attempt  # type: ignore[attr-defined]
                except Exception:
                    pass
                raise

            delay = base_delay_seconds * (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)

    raise RuntimeError("unreachable")


def retryable_http_error(error: Exception) -> bool:
    """Retry transient HTTP/transport failures only.

    Provider clients should not spend the request budget retrying permanent
    4xx responses such as an invalid symbol.  The helper deliberately uses
    duck typing so it also works with httpx-compatible test doubles.
    """
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        return status_code in {408, 425, 429} or status_code >= 500

    # httpx.TimeoutException and transport errors expose these class names;
    # importing httpx here would make the retry utility harder to reuse.
    return type(error).__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "TimeoutException",
        "WriteError",
        "WriteTimeout",
    }
