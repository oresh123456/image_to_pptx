"""
Module: inpainting
==================
Client for the Replicate LaMa model that performs text-erasure inpainting.

LaMa (Large Mask inpainting) reconstructs masked image regions by learning
the surrounding visual context. Applied to our masks, it fills in text areas
with background content that matches surrounding grid lines, gradients, and
solid fills — producing slides that look clean in the final PPTX.

Core functions (used in the pipeline):
  - resolve_version(model, token) -> str:
    Fetch the current latest version ID for a Replicate model. Called once
    per pipeline run (before the thread pool starts) so all worker threads
    share the same version ID without making redundant API calls.
  - inpaint(version_id, image_bytes, image_mime, mask_bytes, token,
            max_retries, poll_interval, max_poll_sec) -> bytes:
    Submit an inpainting prediction, poll until it completes, download and
    return the result image bytes. Handles HTTP 429 rate-limiting by honoring
    the server's retry_after hint plus a per-attempt jitter.

Helper functions:
  - _bytes_to_data_url(data, mime) -> str:
    Encode raw bytes as a base64 data URL for the Replicate API payload.

Pipeline role: called after masking.build_mask() inside each slide's
  ThreadPoolExecutor future. Returns the inpainted image bytes that
  reconstruction.py will use as the new slide background.

Rate limit notes (from notes.md §6.6):
  - Replicate accounts with < $5 credit are throttled to 6 predictions/minute.
  - We honor Replicate's retry_after field from 429 responses.
  - Default max_concurrent=1 keeps under the rate limit automatically.
  - Users with > $5 credit can raise max_concurrent to 5 in config.toml for
    ~5x throughput without risk of rate-limit errors.
"""

from __future__ import annotations

import base64
import logging
import time

import requests

from slide_text_replacer.retry import retry_call, RateLimitedError

log = logging.getLogger(__name__)

_REPLICATE_BASE = "https://api.replicate.com/v1"


def _bytes_to_data_url(data: bytes, mime: str) -> str:
    """
    Encode raw bytes as a base64 data URL string.

    Args:
        data: Raw bytes to encode.
        mime: MIME type string, e.g. "image/png".

    Returns:
        A string of the form "data:<mime>;base64,<b64data>".
    """
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def resolve_version(model: str, token: str) -> str:
    """
    Fetch the latest version ID for a Replicate model.

    Replicate models are versioned by a content-addressed hash. Callers
    need the specific version ID when submitting predictions. This lookup
    is cheap (~200ms) and is called once before the thread pool starts.

    Args:
        model: Replicate model identifier in "owner/model-name" format,
               e.g. "allenhooo/lama".
        token: Replicate API token (Bearer auth).

    Returns:
        The version ID string (a 64-char hex hash).

    Raises:
        RuntimeError: If the model lookup returns a non-200 response.
    """
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{_REPLICATE_BASE}/models/{model}", headers=headers, timeout=30
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Replicate model lookup failed ({r.status_code}): {r.text[:300]}"
        )
    version_id: str = r.json()["latest_version"]["id"]
    log.debug("Resolved %s → version %s...", model, version_id[:16])
    return version_id


def inpaint(
    version_id: str,
    image_bytes: bytes,
    image_mime: str,
    mask_bytes: bytes,
    token: str,
    max_retries: int = 6,
    poll_interval: float = 1.0,
    max_poll_sec: float = 240.0,
) -> bytes:
    """
    Submit a LaMa inpainting prediction and wait for the result.

    Encodes the slide image and mask as base64 data URLs, submits them to
    the Replicate predictions API, then polls the status endpoint until the
    prediction succeeds, fails, or times out. Downloads and returns the
    result image.

    Handles HTTP 429 (rate limit) by reading the server's retry_after field
    and sleeping for that duration plus a per-attempt jitter, up to max_retries.
    This strategy keeps the tool working correctly on free-tier Replicate
    accounts without any manual tuning.

    Args:
        version_id:   The LaMa model version ID from resolve_version().
        image_bytes:  Raw bytes of the original (un-inpainted) slide image.
        image_mime:   MIME type of the image, e.g. "image/png" or "image/jpeg".
        mask_bytes:   PNG mask bytes from masking.build_mask().
        token:        Replicate API token.
        max_retries:  Maximum number of 429 retries before raising. Default 6.
        poll_interval: Seconds between status poll requests. Default 1.0.
        max_poll_sec: Maximum total polling duration in seconds. Default 240.

    Returns:
        Raw bytes of the inpainted result image (PNG).

    Raises:
        RuntimeError: On unrecoverable API errors (non-429 submit failures,
                      prediction failures or cancellations, poll timeout,
                      or failed download of the result).
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "version": version_id,
        "input": {
            "image": _bytes_to_data_url(image_bytes, image_mime),
            "mask":  _bytes_to_data_url(mask_bytes, "image/png"),
        },
    }

    # Submit prediction — retry on 429 via retry_call + RateLimitedError.
    def _submit_prediction() -> dict:
        r = requests.post(
            f"{_REPLICATE_BASE}/predictions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 429:
            try:
                retry_after = float(r.json().get("retry_after", 5))
            except Exception:
                retry_after = 5.0
            raise RateLimitedError(retry_after)
        raise RuntimeError(
            f"Replicate submit failed ({r.status_code}): {r.text[:300]}"
        )

    submit_data = retry_call(
        _submit_prediction,
        max_attempts=max_retries + 1,
        base_delay=1.0,
        jitter=0.5,
        retryable=lambda e: isinstance(e, RateLimitedError),
        context="inpainting submit",
    )

    status_url: str = submit_data["urls"]["get"]
    log.debug("Prediction submitted. Polling: %s", status_url)

    # Poll until succeeded, failed/canceled, or timeout.
    elapsed = 0.0
    state: dict = {}
    while True:
        time.sleep(poll_interval)
        elapsed += poll_interval
        state = requests.get(status_url, headers=headers, timeout=30).json()
        status = state.get("status")
        log.debug("Poll %.0fs: status=%s", elapsed, status)

        if status == "succeeded":
            break
        if status in ("failed", "canceled"):
            raise RuntimeError(
                f"LaMa prediction {status}: {state.get('error')}"
            )
        if elapsed > max_poll_sec:
            raise RuntimeError(
                f"LaMa prediction timed out after {elapsed:.0f}s"
            )

    output = state.get("output")
    if not output:
        raise RuntimeError("LaMa succeeded but returned no output URL.")
    result_url = output if isinstance(output, str) else output[0]

    resp = requests.get(result_url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to download inpainted image ({resp.status_code})."
        )
    log.debug("Inpainting complete — downloaded %d bytes.", len(resp.content))
    return resp.content
