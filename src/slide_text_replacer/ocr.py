"""
Module: ocr
===========
Calls Gemini 2.5 Pro to detect all text regions in a slide image.

This is the first per-slide API call in the pipeline. It sends the raw slide
image to Gemini and receives back a JSON array describing every text element:
its content, its normalized bounding box (0-1000 coords), and an estimated
single-line font size in pixels.

Core functions (used in the pipeline):
  - run(image_bytes, mime_type, api_key, model) -> list[Region]:
    Main entry point. Encodes the image, builds the request, calls Gemini,
    parses the JSON response into Region objects, and returns them.
    Retries exactly once on any failure. Returns an empty list after two
    failures so the pipeline can continue with other slides.

Helper functions (not called from outside this module):
  - _call_gemini(api_key, model, image_bytes, mime_type, prompt, timeout) -> str:
    Raw HTTP POST to the Gemini generateContent endpoint. Returns the text
    of the first candidate's first text part.
  - _parse_regions(raw_json) -> list[Region]:
    Parse and validate Gemini's JSON response. Tolerates markdown code fences.
    Skips items that are missing required fields or have degenerate boxes.

Pipeline role: first per-slide stage. Called inside each slide's ThreadPoolExecutor
  future. Its output list[Region] feeds both enrichment.run() and masking.build_mask().

Prompt version: v1.0 (full text in docs/prompts.md).
"""

from __future__ import annotations

import base64
import json
import logging

import requests

from slide_text_replacer.retry import retry_call, RetryExhausted
from slide_text_replacer.schemas import Region

log = logging.getLogger(__name__)

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ── Prompt v1.0 ───────────────────────────────────────────────────────────────
# Do NOT change this without bumping the version and updating docs/prompts.md.
# The Hebrew space-preservation instruction is load-bearing — without it Gemini
# occasionally concatenates Hebrew words into one token.

OCR_PROMPT = """\
Detect every distinct text element in this slide image.

For each text element output a JSON object with these exact keys:
  "text"        : exact text content. IMPORTANT: preserve the space between every
                  Hebrew word — do not concatenate words. Preserve English, numbers,
                  symbols, and punctuation exactly as shown.
  "box_2d"      : [ymin, xmin, ymax, xmax] — four integers each in 0-1000,
                  where 0,0 is the image top-left and 1000,1000 is bottom-right.
  "font_size_px": integer — estimated rendered height of ONE line of text in pixels.
                  If the text wraps across multiple lines, estimate a single line's
                  height — NOT the full block height.

A "text element" is one visually-grouped region (a slide title, one bullet, one
label, a caption, a slide number). Do NOT merge visually-separate regions. Do NOT
split a visually-grouped region.

Respond with ONLY a valid JSON array. No markdown fences, no prose.\
"""


def _call_gemini(
    api_key: str,
    model: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    timeout: int = 300,
) -> str:
    """
    Send a single generateContent request to Gemini with an image and prompt.

    The image is sent as base64-encoded inline_data. Authentication is via
    the ?key= query parameter. The timeout is set high (300s) because
    Gemini 2.5 Pro is a thinking model that can reason for 2-3 minutes on
    geometrically complex slides (see notes.md §6.7).

    Args:
        api_key:    Google AI Studio API key.
        model:      Gemini model identifier, e.g. "gemini-2.5-pro".
        image_bytes: Raw bytes of the slide image.
        mime_type:  MIME type of the image, e.g. "image/png".
        prompt:     The text prompt to send alongside the image.
        timeout:    HTTP read timeout in seconds. Default 300.

    Returns:
        The text content of the first candidate's first text part.

    Raises:
        RuntimeError: On non-200 HTTP status, empty candidates list, or
                      response with no text part.
    """
    url = f"{_GEMINI_BASE}/{model}:generateContent"
    payload = {
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                },
                {"text": prompt},
            ]
        }],
    }
    r = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(
            f"Gemini OCR error {r.status_code}: {r.text[:500]}"
        )
    data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(
            f"Gemini returned no candidates. Response: {json.dumps(data)[:400]}"
        )
    parts = candidates[0].get("content", {}).get("parts", [])
    text_part = next((p["text"] for p in parts if "text" in p), None)
    if text_part is None:
        raise RuntimeError(
            f"No text part in Gemini candidate. Response: {json.dumps(data)[:400]}"
        )
    log.debug("OCR raw response length: %d chars", len(text_part))
    return text_part


def _parse_regions(raw_json: str) -> list[Region]:
    """
    Parse a Gemini text response into a list of Region objects.

    Handles both raw JSON and JSON wrapped in markdown code fences. Skips
    any items missing required fields or with degenerate boxes (too small
    to be real text). box_2d values are clamped to [0, 1000].

    Args:
        raw_json: The raw text returned by Gemini.

    Returns:
        List of Region objects. May be empty if the response was valid JSON
        but contained no usable items.

    Raises:
        ValueError: If the response cannot be parsed as a JSON list at all.
        json.JSONDecodeError: If the text is not valid JSON after fence removal.
    """
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected a JSON array from Gemini, got {type(parsed).__name__}"
        )

    regions: list[Region] = []
    for item in parsed:
        text_str = (item.get("text") or "").strip()
        box = item.get("box_2d")
        if not text_str or not box or len(box) != 4:
            continue
        font_px = item.get("font_size_px")
        if not isinstance(font_px, (int, float)) or font_px <= 0:
            font_px = 16.0
        regions.append(Region(
            text=text_str,
            box_2d=tuple(max(0, min(1000, int(c))) for c in box),
            font_size_px=float(font_px),
        ))
    return regions


def run(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    model: str = "gemini-2.5-pro",
) -> list[Region]:
    """
    Detect all text regions in a slide image using Gemini 2.5 Pro.

    Makes up to two attempts. On the first failure logs a warning and retries.
    On the second failure logs an error and returns an empty list — the slide
    proceeds through the rest of the pipeline with no text detected, resulting
    in an inpainted background with no text overlay.

    Args:
        image_bytes: Raw bytes of the slide image (PNG or JPEG).
        mime_type:   MIME type of the image, e.g. "image/png".
        api_key:     Google AI Studio API key.
        model:       Gemini model name. Defaults to "gemini-2.5-pro".

    Returns:
        List of Region objects with normalized 0-1000 bounding boxes.
        Returns an empty list if OCR failed or detected no text.
    """
    def _attempt() -> list[Region]:
        raw = _call_gemini(api_key, model, image_bytes, mime_type, OCR_PROMPT)
        regions = _parse_regions(raw)
        log.debug("OCR found %d region(s).", len(regions))
        return regions

    try:
        return retry_call(_attempt, max_attempts=2, base_delay=1.0, context="OCR")
    except RetryExhausted as exc:
        log.error(
            "OCR failed after %d attempts (%s) — slide will have no text overlay.",
            exc.attempts,
            exc.last_error,
        )
        return []
