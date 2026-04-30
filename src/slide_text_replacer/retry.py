"""
Module: retry
=============
Shared retry utility with exponential backoff, jitter, and server-directed
delay support.

Used by ocr.py, enrichment.py, and inpainting.py to standardise retry
behaviour across all API-calling modules.

Exports:
  - retry_call(fn, ...) -> T:  Call fn() with retries and exponential backoff.
  - RetryExhausted:            Raised after all attempts fail.
  - RateLimitedError:          Carries a retry_after hint; used by inpainting
                               for HTTP 429 responses.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class RetryExhausted(Exception):
    """All retry attempts failed.

    Attributes:
        last_error: The exception from the final attempt.
        attempts:   Total number of attempts made.
    """

    def __init__(self, last_error: Exception, attempts: int) -> None:
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(
            f"All {attempts} attempt(s) failed. Last error: {last_error}"
        )


class RateLimitedError(Exception):
    """Server indicated rate limiting; carries a retry_after hint.

    Attributes:
        retry_after: Seconds the server asked us to wait.
    """

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited — retry after {retry_after:.1f}s")


def retry_call(
    fn: Callable[[], T],
    *,
    max_attempts: int = 2,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: float = 0.0,
    retryable: Callable[[Exception], bool] | None = None,
    context: str = "",
) -> T:
    """Call *fn()* with retries, exponential backoff, and optional jitter.

    If the raised exception has a ``retry_after`` attribute (e.g.
    ``RateLimitedError``), its value is used as the sleep duration instead
    of the calculated backoff.

    Args:
        fn:             Zero-argument callable to invoke.
        max_attempts:   Total attempts (including the first). Must be >= 1.
        base_delay:     Initial delay in seconds before the first retry.
        backoff_factor: Multiplier applied to delay after each retry.
        max_delay:      Upper bound on calculated delay (before jitter).
        jitter:         Maximum random seconds added to each delay.
        retryable:      Predicate that receives the caught exception and
                        returns True if a retry should be attempted.  When
                        None, all exceptions are retryable.
        context:        Human-readable label included in log messages.

    Returns:
        The return value of *fn()* on the first successful call.

    Raises:
        RetryExhausted: After *max_attempts* failures (only if max_attempts > 1).
        Exception:      If max_attempts == 1 or the exception is not retryable,
                        the original exception is re-raised directly.
    """
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc

            # Non-retryable → raise immediately.
            if retryable is not None and not retryable(exc):
                raise

            # Last attempt → stop.
            if attempt + 1 >= max_attempts:
                break

            # Compute delay.
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                delay = float(retry_after)
            else:
                delay = min(base_delay * backoff_factor ** attempt, max_delay)

            if jitter > 0:
                delay += random.uniform(0, jitter)

            ctx = f" [{context}]" if context else ""
            log.warning(
                "Attempt %d/%d failed%s (%s) — retrying in %.1fs.",
                attempt + 1,
                max_attempts,
                ctx,
                exc,
                delay,
            )
            time.sleep(delay)

    # max_attempts == 1 → re-raise the original exception directly.
    assert last_error is not None
    if max_attempts <= 1:
        raise last_error
    raise RetryExhausted(last_error, max_attempts)
