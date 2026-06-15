#!/usr/bin/env python3
"""
BoutyHunter — Rate Limit Handling

Global rate-limit tracker that pauses all requests to a platform when any one
of them gets 429'd.  Also provides a retry helper with exponential backoff
that respects ``Retry-After`` headers.

Usage:
    from rate_limiter import wait_for_platform, retry_request

    # Before making a request — blocks if platform is in cooldown
    wait_for_platform("hackerone")

    # Make the request with automatic retries on 429/5xx
    resp = retry_request(session.get, url, timeout=30)

    # If you get a 429 yourself (e.g. outside retry_request), set cooldown:
    from rate_limiter import set_cooldown
    set_cooldown("hackerone", delay=60)
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Callable

import requests

logger = logging.getLogger("boutyhunter.rate_limit")

# ─── Retry Policy ──────────────────────────────────────────────────────

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 2.0       # seconds between retries (doubles each attempt)
_MAX_DELAY = 60         # cap backoff at 1 minute

# ─── Global Per-Platform Cooldown State ────────────────────────────────

_lock = threading.Lock()
_cooldowns: dict[str, float] = {}   # platform_key → unix timestamp


def set_cooldown(platform: str, delay: float) -> None:
    """Set a global cooldown for *platform* lasting *delay* seconds from now."""
    until = time.time() + delay
    with _lock:
        old_until = _cooldowns.get(platform, 0.0)
        if until > old_until:
            _cooldowns[platform] = until
            logger.warning(
                "Rate limit hit — pausing all %s requests for %.1fs", platform, delay
            )


def wait_for_platform(platform: str) -> None:
    """Block until any global cooldown for *platform* has expired.

    No-op if the platform isn't in cooldown or the cooldown already passed.
    """
    while True:
        with _lock:
            until = _cooldowns.get(platform, 0.0)
        if time.time() >= until:
            break
        remaining = max(0, until - time.time())
        logger.debug("Platform %s in cooldown — waiting %.1fs", platform, remaining)
        time.sleep(min(remaining, 1.0))   # poll every second


def get_remaining_cooldown(platform: str) -> float:
    """Return seconds remaining on the global cooldown for *platform*, or 0."""
    with _lock:
        until = _cooldowns.get(platform, 0.0)
    return max(0.0, until - time.time())


# ─── Retry Helper ──────────────────────────────────────────────────────

def retry_request(
    func: Callable[..., requests.Response],
    *args: Any,
    platform: str | None = None,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    **kwargs: Any,
) -> requests.Response:
    """Call an HTTP function with exponential backoff on rate-limit / server errors.

    - Retries on 429, 5xx and transient ``requests`` exceptions.
    - Respects ``Retry-After`` headers when present.
    - If a 429 is received, sets a **global platform cooldown** so other
      requests to the same platform pause automatically via ``wait_for_platform()``.
    - Raises the original exception after exhausting retries.

    Args:
        func: A callable that returns a ``requests.Response`` (e.g. ``session.get``).
        *args, **kwargs: Passed through to *func*.
        platform: Platform key for global cooldown tracking (e.g. ``"hackerone"``).
        max_retries: Number of retries before giving up.
        base_delay: Initial delay in seconds between retries.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        # Wait for any global cooldown before firing the request
        if platform:
            wait_for_platform(platform)

        try:
            resp = func(*args, **kwargs)

            if resp.status_code not in _RETRYABLE_STATUS_CODES:
                return resp  # success or non-retryable error — caller handles it

            # ── Rate-limited or server error — set global cooldown on 429 ──
            delay = base_delay * (2 ** attempt)

            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass  # non-numeric Retry-After, ignore

            delay = min(delay, _MAX_DELAY)

            if resp.status_code == 429 and platform:
                set_cooldown(platform, delay * 1.5)  # extra buffer for global cooldown

            logger.warning(
                "Rate limited / server error (%s) on attempt %d/%d — retrying in %.1fs",
                resp.status_code,
                attempt + 1,
                max_retries + 1,
                delay,
            )
            time.sleep(delay)
            continue

        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), _MAX_DELAY)
                logger.warning(
                    "Request failed (%s) on attempt %d/%d — retrying in %.1fs",
                    type(e).__name__,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                )
                time.sleep(delay)
            continue

    # Exhausted retries — return last response or raise
    if last_exc is not None:
        raise last_exc
    return resp  # type: ignore[possibly-undefined]
