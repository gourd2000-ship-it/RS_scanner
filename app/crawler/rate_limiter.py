import random
import time


class RateLimiter:
    def __init__(self, min_delay_ms: int, max_delay_ms: int) -> None:
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms

    def sleep(self) -> None:
        delay_ms = random.randint(self.min_delay_ms, self.max_delay_ms)
        time.sleep(delay_ms / 1000)
