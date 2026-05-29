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
                raise

            delay = base_delay_seconds * (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)

    raise RuntimeError("unreachable")
