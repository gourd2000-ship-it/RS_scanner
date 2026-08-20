import random
import time
from threading import Lock


class RateLimiter:
    def __init__(self, min_delay_ms: int, max_delay_ms: int) -> None:
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms

    def sleep(self) -> None:
        delay_ms = random.randint(self.min_delay_ms, self.max_delay_ms)
        time.sleep(delay_ms / 1000)


class CallsPerSecondLimiter:
    """Serialize calls to a provider at a fixed maximum rate.

    Unlike the Naver jitter limiter, this limiter is intended for APIs whose
    quota is expressed as calls per second.  A single instance must be shared
    by all worker threads for the same provider credential.
    """

    def __init__(self, calls_per_second: float) -> None:
        if calls_per_second <= 0:
            raise ValueError("calls_per_second must be positive")
        self.interval = 1.0 / calls_per_second
        self._next_allowed_at = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next_allowed_at - now)
            scheduled = max(now, self._next_allowed_at) + self.interval
            self._next_allowed_at = scheduled
        if wait_for:
            time.sleep(wait_for)
