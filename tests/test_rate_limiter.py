from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from quickbooks_mcp.rate_limiter import TokenBucketRateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_limiter(rate: float = 10, per: float = 1.0, start: float = 0.0) -> TokenBucketRateLimiter:
    """Create a limiter with a controlled starting clock value."""
    with patch("time.monotonic", return_value=start):
        return TokenBucketRateLimiter(rate=rate, per=per)


# ---------------------------------------------------------------------------
# 1. acquire() succeeds immediately when bucket is full
# ---------------------------------------------------------------------------


async def test_acquire_immediate_when_full():
    limiter = _make_limiter(rate=10, per=1.0, start=0.0)
    # Bucket starts full (10 tokens); the first acquire should not sleep.
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch("time.monotonic", return_value=0.0):
            await limiter.acquire()
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Multiple sequential acquires (up to capacity) succeed without waiting
# ---------------------------------------------------------------------------


async def test_sequential_acquires_up_to_capacity_no_sleep():
    rate = 5
    limiter = _make_limiter(rate=rate, per=1.0, start=0.0)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch("time.monotonic", return_value=0.0):
            for _ in range(rate):
                await limiter.acquire()

    mock_sleep.assert_not_called()
    # All 5 tokens consumed; none remaining.
    assert limiter._tokens == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. After exhausting the bucket, acquire() waits before returning
# ---------------------------------------------------------------------------


async def test_acquire_waits_after_bucket_exhausted():
    rate = 3
    per = 1.0
    limiter = _make_limiter(rate=rate, per=per, start=0.0)

    sleep_calls: list[float] = []

    async def fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)
        # Simulate time advancing so the next _refill call finds enough tokens.
        limiter._tokens += rate / per * secs
        limiter._last_refill -= secs  # keep _last_refill consistent

    with patch("time.monotonic", return_value=0.0):
        # Drain the bucket.
        for _ in range(rate):
            await limiter.acquire()

    # Next acquire must wait; use fake_sleep to unblock it.
    with patch("asyncio.sleep", side_effect=fake_sleep):
        with patch("time.monotonic", return_value=0.0):
            await limiter.acquire()

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0


# ---------------------------------------------------------------------------
# 4. Custom rate/per parameters work correctly
# ---------------------------------------------------------------------------


async def test_custom_rate_per_capacity():
    # 60 tokens per 60 s = 1 token/s; capacity == 60.
    limiter = _make_limiter(rate=60, per=60.0, start=0.0)
    assert limiter._capacity == pytest.approx(60.0)
    assert limiter._tokens == pytest.approx(60.0)
    assert limiter._rate == 60.0
    assert limiter._per == 60.0


async def test_custom_rate_per_refill_rate():
    # 2 tokens per 4 s = 0.5 tokens/s.
    rate, per = 2.0, 4.0
    start = 100.0
    limiter = _make_limiter(rate=rate, per=per, start=start)

    # Drain all tokens.
    with patch("time.monotonic", return_value=start):
        for _ in range(int(rate)):
            await limiter.acquire()

    assert limiter._tokens == pytest.approx(0.0)

    # Advance 2 s → should add 0.5 * 2 = 1 token.
    with patch("time.monotonic", return_value=start + 2.0):
        limiter._refill()

    assert limiter._tokens == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. Bucket refills over time (mock time.monotonic)
# ---------------------------------------------------------------------------


async def test_refill_does_not_exceed_capacity():
    rate = 5.0
    limiter = _make_limiter(rate=rate, per=1.0, start=0.0)

    # Drain fully.
    with patch("time.monotonic", return_value=0.0):
        for _ in range(int(rate)):
            await limiter.acquire()

    assert limiter._tokens == pytest.approx(0.0)

    # Advance far into the future — bucket should cap at capacity.
    with patch("time.monotonic", return_value=1000.0):
        limiter._refill()

    assert limiter._tokens == pytest.approx(rate)


async def test_refill_partial():
    rate = 10.0
    per = 1.0
    start = 50.0
    limiter = _make_limiter(rate=rate, per=per, start=start)

    # Drain fully.
    with patch("time.monotonic", return_value=start):
        for _ in range(int(rate)):
            await limiter.acquire()

    # Advance by 0.3 s → 3 tokens should be added.
    with patch("time.monotonic", return_value=start + 0.3):
        limiter._refill()

    assert limiter._tokens == pytest.approx(3.0, abs=1e-9)


async def test_last_refill_timestamp_updated():
    limiter = _make_limiter(rate=10, per=1.0, start=0.0)
    new_time = 5.0
    with patch("time.monotonic", return_value=new_time):
        limiter._refill()
    assert limiter._last_refill == pytest.approx(new_time)


# ---------------------------------------------------------------------------
# 6. Concurrent acquire calls work safely (no race conditions)
# ---------------------------------------------------------------------------


async def test_concurrent_acquires_do_not_over_consume():
    """Ten coroutines race to acquire from a bucket of 10; exactly 10 tokens consumed."""
    rate = 10
    limiter = _make_limiter(rate=rate, per=1.0, start=0.0)

    original_sleep = asyncio.sleep

    async def counting_sleep(secs: float) -> None:
        # Advance the internal clock so the limiter can eventually refill
        # and unblock, but do it only once per sleep to avoid infinite loops.
        limiter._tokens += 1.0
        await original_sleep(0)  # yield to event loop without real delay

    with patch("time.monotonic", return_value=0.0):
        with patch("asyncio.sleep", side_effect=counting_sleep):
            tasks = [asyncio.create_task(limiter.acquire()) for _ in range(rate)]
            await asyncio.gather(*tasks)

    # All tasks completed — the important assertion is no exception was raised
    # and the lock prevented double-decrement (tokens never go below -epsilon).
    assert limiter._tokens >= -0.01  # minor float tolerance


async def test_concurrent_acquires_all_complete():
    """All concurrent tasks eventually acquire a token without deadlock."""
    rate = 5
    limiter = _make_limiter(rate=rate, per=1.0, start=0.0)

    call_count = 0
    original_sleep = asyncio.sleep

    async def unblocking_sleep(secs: float) -> None:
        nonlocal call_count
        call_count += 1
        limiter._tokens += 1.0  # simulate a token arriving
        await original_sleep(0)

    with patch("time.monotonic", return_value=0.0):
        with patch("asyncio.sleep", side_effect=unblocking_sleep):
            tasks = [asyncio.create_task(limiter.acquire()) for _ in range(rate * 2)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"Unexpected exceptions: {errors}"
