"""
Module: enrichment
==================
Second Gemini 2.5 Pro call per slide: enriches raw OCR regions with visual
metadata — font family, font weight, primary color, and optionally refined
bounding box and font size.

The model receives the slide image alongside the OCR JSON (so it can correlate
its visual analysis with the already-detected text positions), and for each
region returns a richer object conforming to the EnrichedRegion schema.

Core functions (used in the pipeline):
  - run(image_bytes, mime_type, regions, api_key, model) -> list[EnrichedRegion]:
    Main entry point. Builds the prompt, calls Gemini, parses the response,
    validates all values, and returns one EnrichedRegion per input Region.
    On timeout or parse error: logs a warning and falls back to safe defaults
    (Heebo/regular/#000000) so the slide is not aborted.

Helper functions:
  - _build_prompt(regions) -> str:
    Serialises the OCR Region list to JSON and injects it into the prompt
    template. The model sees the exact text and boxes to enrich.
  - _call_gemini(api_key, model, image_bytes, mime_type, prompt, timeout) -> str:
    Raw HTTP call — identical structure to ocr._call_gemini but kept separate
    to allow independent tuning of timeouts and error messages.
  - _parse_enriched(raw_json, fallback_regions) -> list[EnrichedRegion]:
    Parses the response array, validates font_family/font_weight/color, and
    falls back to per-item defaults for any malformed field. Output length
    always equals len(fallback_regions).
  - _apply_defaults(regions) -> list[EnrichedRegion]:
    Converts Region → EnrichedRegion with safe defaults. Called when the
    entire enrichment API call fails.

Pipeline role: second per-slide stage, called after ocr.run(). Runs inside
  each slide's ThreadPoolExecutor future. Its output feeds reconstruction.py.

Font palette (locked — see notes.md §5):
  "Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"

Prompt version: v1.0 (full text in docs/prompts.md).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

import requests

from slide_text_replacer.config import VALID_FONT_FAMILIES
from slide_text_replacer.retry import retry_call, RetryExhausted
from slide_text_replacer.schemas import Region, EnrichedRegion

log = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_DEFAULT_FONT_FAMILY = "Heebo"
_DEFAULT_FONT_WEIGHT = "regular"
_DEFAULT_COLOR       = "#000000"

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _extract_json_array(raw: str) -> list:
    """
    Extract and parse a JSON array from potentially messy model output.

    Handles markdown fences, leading/trailing prose, trailing commas,
    and missing commas between adjacent objects.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON array found in response ({len(raw)} chars)")
    text = text[start:end + 1]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    fixed = re.sub(r"}\s*{", "},{", fixed)

    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, list):
            log.debug("JSON parsed after fixup.")
            return parsed
    except json.JSONDecodeError:
        pass

    # Dump raw response for debugging
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        dump_path = _LOGS_DIR / f"enrichment_raw_{datetime.now().strftime('%H%M%S')}.txt"
        dump_path.write_text(raw, encoding="utf-8")
        log.warning("Dumped unparseable enrichment response to %s", dump_path)
    except Exception:
        pass

    raise ValueError(f"Cannot parse JSON array from response ({len(raw)} chars)")

# ── Prompt template v1.0 ──────────────────────────────────────────────────────
# {regions_json} is injected at call time. Do NOT change without updating
# docs/prompts.md and bumping the version.

_ENRICHMENT_PROMPT_TEMPLATE = """\
You are given a slide image and a JSON array of text regions already detected in it.

For EACH region in the input array, identify the following visual properties and return
a JSON object with these exact keys:
  "text"        : copy the original text exactly, unchanged.
  "box_2d"      : [ymin, xmin, ymax, xmax] in 0-1000 integers. Refine if you can
                  improve accuracy; otherwise copy the original value.
  "font_size_px": single-line pixel height. Refine if you can improve it; otherwise copy.
  "font_family" : MUST be exactly one of: "Heebo", "Rubik", "Assistant",
                  "Frank Ruhl Libre", "Heebo Black". Pick the closest visual match.
  "font_weight" : exactly "regular" or "bold".
  "color"       : the primary text color in this region as "#RRGGBB" hex. Pick ONE
                  color even if multiple colors appear within the region.

Return a JSON array with one object per input region, IN THE SAME ORDER as the input.
The output array must have exactly the same number of items as the input.

Input regions:
{regions_json}

Respond with ONLY a valid JSON array. No markdown fences, no prose.\
"""


def _build_prompt(regions: list[Region]) -> str:
    """
    Build the enrichment prompt by serialising the OCR region list into it.

    The regions are serialised to compact but readable JSON and injected into
    the template. The model can see both the image and these detected regions
    simultaneously, which improves font/color identification accuracy.

    Args:
        regions: List of Region objects from ocr.run().

    Returns:
        Complete prompt string ready to send to Gemini.
    """
    regions_json = json.dumps(
        [
            {
                "text":        r.text,
                "box_2d":      list(r.box_2d),
                "font_size_px": r.font_size_px,
            }
            for r in regions
        ],
        ensure_ascii=False,
        indent=2,
    )
    return _ENRICHMENT_PROMPT_TEMPLATE.format(regions_json=regions_json)


def _call_gemini(
    api_key: str,
    model: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    timeout: int = 300,
    thinking_budget: int = 1,
) -> str:
    """
    Send a generateContent request to Gemini with an image and prompt.

    Args:
        api_key:     Google AI Studio API key.
        model:       Gemini model identifier.
        image_bytes: Raw slide image bytes.
        mime_type:   Image MIME type.
        prompt:      The full enrichment prompt with injected OCR JSON.
        timeout:     HTTP read timeout in seconds. Default 300.

    Returns:
        The text content of the first candidate's first text part.

    Raises:
        RuntimeError: On non-200 HTTP status or missing text in the response.
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
        "generationConfig": {
            "maxOutputTokens": 5000,
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        },
    }
    r = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(
            f"Gemini enrichment error {r.status_code}: {r.text[:500]}"
        )
    data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(
            f"Gemini returned no candidates. Response: {json.dumps(data)[:400]}"
        )
    candidate = candidates[0]
    finish_reason = candidate.get("finishReason", "UNKNOWN")
    usage = data.get("usageMetadata", {})
    output_tokens = usage.get("candidatesTokenCount", "?")
    log.info("Enrichment output tokens: %s, finishReason: %s", output_tokens, finish_reason)
    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Gemini enrichment truncated (finishReason=MAX_TOKENS, "
            f"outputTokens={output_tokens}). Increase maxOutputTokens."
        )
    if finish_reason not in ("STOP", "UNKNOWN"):
        raise RuntimeError(
            f"Gemini enrichment stopped unexpectedly (finishReason={finish_reason}, "
            f"outputTokens={output_tokens})."
        )
    parts = candidate.get("content", {}).get("parts", [])
    log.debug("Enrichment parts structure: %s", json.dumps([{k: v if k != "text" else v[:80] for k, v in p.items()} for p in parts]))
    text_part = next((p["text"] for p in parts if "text" in p and not p.get("thought")), None)
    if text_part is None:
        raise RuntimeError(
            f"No text part in enrichment candidate. Response: {json.dumps(data)[:400]}"
        )
    log.debug("Enrichment raw response length: %d chars", len(text_part))
    return text_part


def _parse_enriched(
    raw_json: str,
    fallback_regions: list[Region],
) -> list[EnrichedRegion]:
    """
    Parse Gemini's enrichment response and merge with fallback Region data.

    Items are matched by index (same-order constraint in the prompt). If the
    response has fewer items than expected, or individual items have invalid
    values, per-item fallbacks fill the gaps. The output always has the same
    length as fallback_regions.

    Validation rules:
      - font_family must be in VALID_FONT_FAMILIES; defaults to "Heebo".
      - font_weight must be "regular" or "bold"; defaults to "regular".
      - color must match #RRGGBB; defaults to "#000000".
      - box_2d must be a list/tuple of 4 numbers; falls back to original.
      - font_size_px must be a positive number; falls back to original.

    Args:
        raw_json:         Raw text response from Gemini.
        fallback_regions: The original OCR Region list for fallback values.

    Returns:
        List of EnrichedRegion objects, one per entry in fallback_regions.

    Raises:
        ValueError:          If the response is not a JSON list at all.
        json.JSONDecodeError: If the text is not valid JSON after fence removal.
    """
    parsed = _extract_json_array(raw_json)

    result: list[EnrichedRegion] = []
    for i, fallback in enumerate(fallback_regions):
        item = parsed[i] if i < len(parsed) else {}

        text_str   = (item.get("text") or fallback.text).strip() or fallback.text
        box        = item.get("box_2d", list(fallback.box_2d))
        font_px    = item.get("font_size_px", fallback.font_size_px)
        font_family = item.get("font_family", _DEFAULT_FONT_FAMILY)
        font_weight = item.get("font_weight", _DEFAULT_FONT_WEIGHT)
        color       = item.get("color", _DEFAULT_COLOR)

        # Validate and clamp each field.
        if font_family not in VALID_FONT_FAMILIES:
            log.debug("Unknown font_family %r → using default.", font_family)
            font_family = _DEFAULT_FONT_FAMILY

        if font_weight not in ("regular", "bold"):
            font_weight = _DEFAULT_FONT_WEIGHT

        if not (isinstance(color, str) and _COLOR_RE.match(color)):
            log.debug("Invalid color %r → using default.", color)
            color = _DEFAULT_COLOR

        if not (isinstance(font_px, (int, float)) and font_px > 0):
            font_px = fallback.font_size_px

        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            box = list(fallback.box_2d)

        result.append(EnrichedRegion(
            text=text_str,
            box_2d=tuple(max(0, min(1000, int(c))) for c in box),
            font_size_px=float(font_px),
            font_family=font_family,
            font_weight=font_weight,
            color=color,
        ))
    return result


def _apply_defaults(regions: list[Region]) -> list[EnrichedRegion]:
    """
    Convert Region objects to EnrichedRegion using safe default visual metadata.

    Called when the enrichment API call fails entirely. The resulting text
    boxes will be visible and editable but will use Heebo/regular/black
    rather than matched font and color.

    Args:
        regions: OCR Region list to convert.

    Returns:
        List of EnrichedRegion with Heebo/regular/#000000 defaults.
    """
    return [
        EnrichedRegion(
            text=r.text,
            box_2d=r.box_2d,
            font_size_px=r.font_size_px,
            font_family=_DEFAULT_FONT_FAMILY,
            font_weight=_DEFAULT_FONT_WEIGHT,
            color=_DEFAULT_COLOR,
        )
        for r in regions
    ]


def run(
    image_bytes: bytes,
    mime_type: str,
    regions: list[Region],
    api_key: str,
    model: str = "gemini-3.1-flash-image-preview",
    thinking_budget: int = 1,
) -> list[EnrichedRegion]:
    """
    Enrich OCR regions with font family, weight, color, and refined geometry.

    Sends the slide image alongside the serialised OCR JSON to Gemini 2.5 Pro.
    On any failure (timeout, parse error, HTTP error), logs a warning and
    returns the regions with safe defaults — the slide is not aborted.

    Returns immediately with an empty list if regions is empty (no API call made).

    Args:
        image_bytes: Raw slide image bytes (same image used in the OCR pass).
        mime_type:   Image MIME type, e.g. "image/png".
        regions:     OCR Region list from ocr.run(). Must be non-empty for
                     a meaningful enrichment call.
        api_key:     Google AI Studio API key.
        model:       Gemini model name. Defaults to "gemini-2.5-pro".

    Returns:
        List of EnrichedRegion in the same order as the input regions.
        Falls back to Heebo/regular/#000000 defaults on any API failure.
    """
    if not regions:
        return []

    prompt = _build_prompt(regions)

    def _attempt() -> list[EnrichedRegion]:
        raw = _call_gemini(api_key, model, image_bytes, mime_type, prompt, thinking_budget=thinking_budget)
        enriched = _parse_enriched(raw, regions)
        log.debug("Enrichment returned %d region(s).", len(enriched))
        return enriched

    try:
        return retry_call(
            _attempt, max_attempts=2, base_delay=1.0, context="enrichment",
        )
    except RetryExhausted as exc:
        log.warning(
            "Enrichment failed after %d attempts (%s) "
            "— using default font/color for this slide.",
            exc.attempts,
            exc.last_error,
        )
        return _apply_defaults(regions)
