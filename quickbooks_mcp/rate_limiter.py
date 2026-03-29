from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    def __init__(self, rate: float = 500, per: float = 60) -> None:
        """rate tokens per `per` seconds."""
        self._rate = rate
        self._per = per
        self._capacity = rate
        self._tokens = rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * (self._rate / self._per)
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / (self._rate / self._per)

            await asyncio.sleep(wait_time)
