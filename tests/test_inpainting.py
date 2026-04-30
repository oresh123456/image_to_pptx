"""
Tests for inpainting.py — Replicate LaMa API client.

Verifies I/O contracts documented in docs/modules/inpainting.md.
All tests are local — no API calls. HTTP and time.sleep mocked.
"""

import base64
from unittest.mock import patch, MagicMock, call

import pytest

from slide_text_replacer.inpainting import _bytes_to_data_url, resolve_version, inpaint
from slide_text_replacer.retry import RetryExhausted


# ── _bytes_to_data_url: output contract ──────────────────────────────────────
# Input: (bytes, mime) → Output: "data:<mime>;base64,<b64>" string.

def test_bytes_to_data_url_format():
    """Input: raw bytes + MIME → Output: decodable data URL with correct prefix."""
    data = b"hello world"
    result = _bytes_to_data_url(data, "image/png")
    assert result.startswith("data:image/png;base64,")
    b64_part = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_part)
    assert decoded == data


# ── resolve_version(): output contract ───────────────────────────────────────
# Input: (model, token) → Output: version ID string.

@patch("slide_text_replacer.inpainting.requests.get")
def test_resolve_version_returns_version_id(mock_get):
    """Input: valid model + token → Output: version ID string from API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"latest_version": {"id": "abc123def456"}}
    mock_get.return_value = mock_resp

    version = resolve_version("allenhooo/lama", "fake-token")
    assert version == "abc123def456"


# ── resolve_version(): error handling ────────────────────────────────────────

@patch("slide_text_replacer.inpainting.requests.get")
def test_resolve_version_non_200_raises(mock_get):
    """Input: non-200 response → raises RuntimeError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Replicate model lookup failed"):
        resolve_version("allenhooo/lama", "fake-token")


# ── inpaint(): output contract ───────────────────────────────────────────────
# Input: version_id, image_bytes, mask_bytes, token → Output: inpainted PNG bytes.

@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_returns_image_bytes(mock_requests, mock_sleep):
    """Input: submit(201) → poll(succeeded) → download(200) → Output: result bytes."""
    submit_resp = MagicMock()
    submit_resp.status_code = 201
    submit_resp.json.return_value = {"urls": {"get": "https://api.replicate.com/v1/predictions/123"}}
    mock_requests.post.return_value = submit_resp

    poll_resp = MagicMock()
    poll_resp.json.return_value = {"status": "succeeded", "output": "https://output.png"}
    download_resp = MagicMock()
    download_resp.status_code = 200
    download_resp.content = b"inpainted-image-bytes"
    mock_requests.get.side_effect = [poll_resp, download_resp]

    result = inpaint("v123", b"img", "image/png", b"mask", "token")
    assert result == b"inpainted-image-bytes"


@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_polls_until_succeeded(mock_requests, mock_sleep):
    """Input: processing → processing → succeeded → Output: result bytes."""
    submit_resp = MagicMock()
    submit_resp.status_code = 201
    submit_resp.json.return_value = {"urls": {"get": "https://poll-url"}}
    mock_requests.post.return_value = submit_resp

    poll1 = MagicMock()
    poll1.json.return_value = {"status": "processing"}
    poll2 = MagicMock()
    poll2.json.return_value = {"status": "processing"}
    poll3 = MagicMock()
    poll3.json.return_value = {"status": "succeeded", "output": "https://out.png"}
    download_resp = MagicMock()
    download_resp.status_code = 200
    download_resp.content = b"final"
    mock_requests.get.side_effect = [poll1, poll2, poll3, download_resp]

    result = inpaint("v123", b"img", "image/png", b"mask", "token")
    assert result == b"final"


# ── inpaint(): 429 retry handling ────────────────────────────────────────────
# RateLimitedError (429) → retried. Other errors → raised immediately.

@patch("slide_text_replacer.retry.time.sleep")
@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_retries_on_429_then_succeeds(mock_requests, mock_sleep, mock_retry_sleep):
    """Input: first 429, then 201 → Output: result bytes after retry."""
    rate_limited_resp = MagicMock()
    rate_limited_resp.status_code = 429
    rate_limited_resp.json.return_value = {"retry_after": 1}

    submit_resp = MagicMock()
    submit_resp.status_code = 201
    submit_resp.json.return_value = {"urls": {"get": "https://api.replicate.com/v1/predictions/123"}}
    mock_requests.post.side_effect = [rate_limited_resp, submit_resp]

    poll_resp = MagicMock()
    poll_resp.json.return_value = {"status": "succeeded", "output": "https://output.png"}
    download_resp = MagicMock()
    download_resp.status_code = 200
    download_resp.content = b"result"
    mock_requests.get.side_effect = [poll_resp, download_resp]

    result = inpaint("v123", b"img", "image/png", b"mask", "token", max_retries=6)
    assert result == b"result"
    assert mock_retry_sleep.call_count >= 1


@patch("slide_text_replacer.retry.time.sleep")
@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_exhausted_429_retries_raises(mock_requests, mock_sleep, mock_retry_sleep):
    """Input: all 429s past max_retries → raises RetryExhausted."""
    rate_limited_resp = MagicMock()
    rate_limited_resp.status_code = 429
    rate_limited_resp.json.return_value = {"retry_after": 0.1}
    mock_requests.post.return_value = rate_limited_resp

    with pytest.raises(RetryExhausted):
        inpaint("v123", b"img", "image/png", b"mask", "token", max_retries=2)


# ── inpaint(): non-429 error handling ────────────────────────────────────────

@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_non_429_submit_raises_immediately(mock_requests, mock_sleep):
    """Input: 500 on submit → raises RuntimeError (no retry)."""
    submit_resp = MagicMock()
    submit_resp.status_code = 500
    submit_resp.text = "Internal Server Error"
    mock_requests.post.return_value = submit_resp

    with pytest.raises(RuntimeError, match="Replicate submit failed"):
        inpaint("v123", b"img", "image/png", b"mask", "token")


@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_failed_prediction_raises(mock_requests, mock_sleep):
    """Input: poll returns "failed" → raises RuntimeError."""
    submit_resp = MagicMock()
    submit_resp.status_code = 201
    submit_resp.json.return_value = {"urls": {"get": "https://poll-url"}}
    mock_requests.post.return_value = submit_resp

    poll_resp = MagicMock()
    poll_resp.json.return_value = {"status": "failed", "error": "OOM"}
    mock_requests.get.return_value = poll_resp

    with pytest.raises(RuntimeError, match="LaMa prediction failed"):
        inpaint("v123", b"img", "image/png", b"mask", "token")


@patch("slide_text_replacer.inpainting.time.sleep")
@patch("slide_text_replacer.inpainting.requests")
def test_inpaint_poll_timeout_raises(mock_requests, mock_sleep):
    """Input: always "processing" past max_poll_sec → raises RuntimeError."""
    submit_resp = MagicMock()
    submit_resp.status_code = 201
    submit_resp.json.return_value = {"urls": {"get": "https://poll-url"}}
    mock_requests.post.return_value = submit_resp

    poll_resp = MagicMock()
    poll_resp.json.return_value = {"status": "processing"}
    mock_requests.get.return_value = poll_resp

    with pytest.raises(RuntimeError, match="timed out"):
        inpaint(
            "v123", b"img", "image/png", b"mask", "token",
            poll_interval=1.0, max_poll_sec=2.0,
        )
