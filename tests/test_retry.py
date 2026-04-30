"""
Tests for retry.py — shared retry utility with exponential backoff.

Verifies I/O contracts documented in docs/modules/retry.md.
All tests are local. time.sleep mocked to avoid real delays.
"""

from unittest.mock import patch, MagicMock

import pytest

from slide_text_replacer.retry import retry_call, RetryExhausted, RateLimitedError


# ── retry_call(): output contract (success) ──────────────────────────────────
# Input: fn() → Output: fn's return value.

def test_success_on_first_attempt():
    """Input: fn succeeds immediately → Output: fn's return value, no retry."""
    fn = MagicMock(return_value="ok")
    result = retry_call(fn, max_attempts=3)
    assert result == "ok"
    assert fn.call_count == 1


@patch("slide_text_replacer.retry.time.sleep")
def test_success_after_one_failure(mock_sleep):
    """Input: fn fails once then succeeds → Output: success value after 1 retry."""
    fn = MagicMock(side_effect=[ValueError("boom"), "ok"])
    result = retry_call(fn, max_attempts=3, base_delay=1.0)
    assert result == "ok"
    assert fn.call_count == 2
    assert mock_sleep.call_count == 1


# ── retry_call(): exhaustion ─────────────────────────────────────────────────
# All attempts fail → RetryExhausted (when max_attempts > 1).

@patch("slide_text_replacer.retry.time.sleep")
def test_retry_exhausted_after_max_attempts(mock_sleep):
    """Input: all 3 attempts fail → raises RetryExhausted with correct attributes."""
    fn = MagicMock(side_effect=ValueError("fail"))
    with pytest.raises(RetryExhausted) as exc_info:
        retry_call(fn, max_attempts=3, base_delay=0.1)
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.last_error, ValueError)
    assert fn.call_count == 3


def test_max_attempts_one_raises_original_exception():
    """Input: max_attempts=1, fn fails → raises original exception (not RetryExhausted)."""
    fn = MagicMock(side_effect=ValueError("only one shot"))
    with pytest.raises(ValueError, match="only one shot"):
        retry_call(fn, max_attempts=1)
    assert fn.call_count == 1


# ── retry_call(): retryable predicate ────────────────────────────────────────
# Only exceptions matching retryable() are retried.

def test_non_retryable_exception_raises_immediately():
    """Input: exception not matching retryable → raises immediately, no retry."""
    fn = MagicMock(side_effect=[TypeError("not retryable")])
    with pytest.raises(TypeError, match="not retryable"):
        retry_call(fn, max_attempts=3, retryable=lambda e: isinstance(e, ValueError))
    assert fn.call_count == 1


@patch("slide_text_replacer.retry.time.sleep")
def test_retryable_exception_is_retried(mock_sleep):
    """Input: exception matching retryable → retried, then succeeds."""
    fn = MagicMock(side_effect=[ValueError("retry me"), "ok"])
    result = retry_call(fn, max_attempts=3, base_delay=0.1, retryable=lambda e: isinstance(e, ValueError))
    assert result == "ok"
    assert fn.call_count == 2


# ── retry_call(): server-directed delay ──────────────────────────────────────
# Exception with retry_after attribute → uses that instead of calculated delay.

@patch("slide_text_replacer.retry.time.sleep")
def test_server_directed_delay_via_retry_after(mock_sleep):
    """Input: RateLimitedError(retry_after=7.0) → sleep uses 7.0, not base_delay."""
    err = RateLimitedError(retry_after=7.0)
    fn = MagicMock(side_effect=[err, "ok"])
    result = retry_call(fn, max_attempts=3, base_delay=1.0, jitter=0.0)
    assert result == "ok"
    mock_sleep.assert_called_once()
    actual_delay = mock_sleep.call_args[0][0]
    assert actual_delay == 7.0


# ── retry_call(): backoff and jitter ─────────────────────────────────────────

@patch("slide_text_replacer.retry.time.sleep")
def test_backoff_increases_across_attempts(mock_sleep):
    """Input: backoff_factor=2.0 → delays: 1.0, 2.0, 4.0 (exponential)."""
    fn = MagicMock(side_effect=[ValueError("1"), ValueError("2"), ValueError("3"), "ok"])
    retry_call(fn, max_attempts=4, base_delay=1.0, backoff_factor=2.0, jitter=0.0)
    delays = [c[0][0] for c in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0, 4.0]


@patch("slide_text_replacer.retry.time.sleep")
def test_jitter_adds_randomness_to_delay(mock_sleep):
    """Input: jitter=1.0 → delay is between base_delay and base_delay+1.0."""
    fn = MagicMock(side_effect=[ValueError("fail"), "ok"])
    retry_call(fn, max_attempts=2, base_delay=1.0, backoff_factor=1.0, jitter=1.0)
    actual_delay = mock_sleep.call_args[0][0]
    assert 1.0 <= actual_delay <= 2.0


# ── retry_call(): logging ────────────────────────────────────────────────────

@patch("slide_text_replacer.retry.time.sleep")
def test_context_appears_in_log_messages(mock_sleep, caplog):
    """Input: context="my-context" → Output: "my-context" in WARNING log."""
    fn = MagicMock(side_effect=[ValueError("oops"), "ok"])
    with caplog.at_level("WARNING", logger="slide_text_replacer.retry"):
        retry_call(fn, max_attempts=2, base_delay=0.01, context="my-context")
    assert "my-context" in caplog.text
