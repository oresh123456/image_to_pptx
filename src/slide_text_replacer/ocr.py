"""
Module: ocr
===========
Calls Gemini to detect all text regions in a slide image via best-of-N
parallel OCR with top-2 selection and median consensus stabilization.

This is the first per-slide API call in the pipeline. It fires N parallel
requests to Gemini, each returning a JSON array of text elements. The top 2
results (by region count) are consensus-stabilized using median coordinates
from all N candidates, then both are returned for downstream processing.

Core functions (used in the pipeline):
  - run(image_bytes, mime_type, api_key, model, ...) -> list[list[Region]]:
    Main entry point. Fires N parallel Gemini calls, ranks by region count,
    picks top 2, consensus-stabilizes each using all N results.
    Returns [[], []] if all candidates fail.

  - _consensus_refine(candidate, all_candidates, min_matches) -> list[Region]:
    For each region, finds text+proximity matches across all N candidates and
    takes median box_2d + font_size_px when >= min_matches found.

  - _text_matches(a, b) -> bool:
    Fuzzy text match (SequenceMatcher >= 0.85) + centroid proximity < 150.

Helper functions (not called from outside this module):
  - _call_gemini(api_key, model, image_bytes, mime_type, prompt, timeout) -> str:
    Raw HTTP POST to the Gemini generateContent endpoint. Returns the text
    of the first candidate's first text part.
  - _parse_regions(raw_json) -> list[Region]:
    Parse and validate Gemini's JSON response. Tolerates markdown code fences.
    Skips items that are missing required fields or have degenerate boxes.

Pipeline role: first per-slide stage. Called inside each slide's ThreadPoolExecutor
  future. Its output list[list[Region]] (2 candidates) feeds both enrichment.run()
  and masking.build_mask() — each candidate processed independently.

Prompt version: v1.0 (full text in docs/prompts.md).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import statistics
from difflib import SequenceMatcher
from pathlib import Path

import requests
from json_repair import repair_json

from concurrent.futures import ThreadPoolExecutor, as_completed

from slide_text_replacer.schemas import Region

log = logging.getLogger(__name__)
_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"

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
    thinking_budget: int = 1,
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
        "generationConfig": {
            "maxOutputTokens": 5000,
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        },
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
    candidate = candidates[0]
    finish_reason = candidate.get("finishReason", "UNKNOWN")
    usage = data.get("usageMetadata", {})
    output_tokens = usage.get("candidatesTokenCount", "?")
    log.info("OCR output tokens: %s, finishReason: %s", output_tokens, finish_reason)
    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Gemini OCR truncated (finishReason=MAX_TOKENS, "
            f"outputTokens={output_tokens}). Increase maxOutputTokens."
        )
    if finish_reason not in ("STOP", "UNKNOWN"):
        raise RuntimeError(
            f"Gemini OCR stopped unexpectedly (finishReason={finish_reason}, "
            f"outputTokens={output_tokens})."
        )
    parts = candidate.get("content", {}).get("parts", [])
    text_part = next((p["text"] for p in parts if "text" in p and not p.get("thought")), None)
    if text_part is None:
        raise RuntimeError(
            f"No text part in Gemini candidate. Response: {json.dumps(data)[:400]}"
        )
    log.debug("OCR raw response length: %d chars", len(text_part))
    return text_part


def _extract_json_array(raw: str) -> list:
    """
    Extract and parse a JSON array from potentially messy model output.

    Handles markdown fences, leading/trailing prose, trailing commas,
    and missing commas between adjacent objects.

    Args:
        raw: Raw text returned by Gemini.

    Returns:
        Parsed list.

    Raises:
        ValueError: If no JSON array can be extracted.
    """
    text = raw.strip()
    # Strip markdown fences.
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()

    # Isolate the outermost [ … ] to discard leading/trailing prose.
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON array found in response ({len(raw)} chars)")
    text = text[start:end + 1]

    # First attempt: parse as-is.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fixup: remove trailing commas before ] or }, add missing commas
    # between }{ or }  {.
    fixed = re.sub(r",\s*([}\]])", r"\1", text)   # trailing commas
    fixed = re.sub(r"}\s*{", "},{", fixed)          # missing commas between objects
    # Fixup: remove hallucinated "label": prefix before real keys
    fixed = re.sub(r'"label":\s*"(font_size_px)"', r'"\1"', fixed)
    # Fixup: add missing { before "box_2d" when preceded by , at array level
    fixed = re.sub(r',\s*"box_2d"', ', {"box_2d"', fixed)
    # Fixup: remove stray quotes inside numeric arrays [N, N, N, N"]
    fixed = re.sub(r'(\d)"(\s*[,\]])', r'\1\2', fixed)

    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, list):
            log.debug("JSON parsed after fixup.")
            return parsed
    except json.JSONDecodeError:
        pass

    # Phase 4: json-repair catch-all for unknown malformations
    try:
        repaired = repair_json(fixed, return_objects=False)
        parsed = json.loads(repaired)
        if isinstance(parsed, list):
            log.debug("JSON parsed after json-repair.")
            return parsed
    except (json.JSONDecodeError, Exception):
        pass

    # Dump raw response for debugging
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        dump_path = _LOGS_DIR / f"ocr_raw_{datetime.now().strftime('%H%M%S')}.txt"
        dump_path.write_text(raw, encoding="utf-8")
        log.warning("Dumped unparseable OCR response to %s", dump_path)
    except Exception:
        pass

    raise ValueError(f"Cannot parse JSON array from response ({len(raw)} chars)")


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
    parsed = _extract_json_array(raw_json)
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected a JSON array from Gemini, got {type(parsed).__name__}"
        )

    regions: list[Region] = []
    skipped = 0
    for item in parsed:
        text_str = (item.get("text") or "").strip()
        box = item.get("box_2d")
        if not text_str or not box or len(box) != 4:
            skipped += 1
            continue
        font_px = item.get("font_size_px")
        if not isinstance(font_px, (int, float)) or font_px <= 0:
            font_px = 16.0
        regions.append(Region(
            text=text_str,
            box_2d=tuple(max(0, min(1000, int(c))) for c in box),
            font_size_px=float(font_px),
        ))
    log.info(
        "OCR parse: %d raw items → %d regions (%d skipped)",
        len(parsed), len(regions), skipped,
    )
    return regions



def _centroid(box: tuple[int, int, int, int]) -> tuple[float, float]:
    """Return (y_center, x_center) of a box_2d tuple."""
    ymin, xmin, ymax, xmax = box
    return ((ymin + ymax) / 2, (xmin + xmax) / 2)


def _text_matches(a: Region, b: Region, max_centroid_dist: float = 150.0) -> bool:
    """
    Check if two regions refer to the same text element.

    Uses exact match first, then fuzzy (SequenceMatcher >= 0.85).
    Also requires centroid proximity < max_centroid_dist to avoid
    matching repeated text in different locations.
    """
    # Centroid proximity check
    cy_a, cx_a = _centroid(a.box_2d)
    cy_b, cx_b = _centroid(b.box_2d)
    dist = ((cy_a - cy_b) ** 2 + (cx_a - cx_b) ** 2) ** 0.5
    if dist > max_centroid_dist:
        return False

    # Text match: exact (whitespace-normalized) or fuzzy
    ta = " ".join(a.text.split())
    tb = " ".join(b.text.split())
    if ta == tb:
        return True
    return SequenceMatcher(None, ta, tb).ratio() >= 0.85


def _consensus_refine(
    candidate: list[Region],
    all_candidates: list[list[Region]],
    min_matches: int = 3,
) -> list[Region]:
    """
    Stabilize a candidate's coordinates using median consensus from all candidates.

    For each region in candidate, find text+proximity matches across all candidates.
    If >= min_matches found: take median box_2d (per-coord) and median font_size_px.
    If < min_matches: keep original values.
    Clamps box_2d to [0, 1000].
    """
    refined: list[Region] = []
    for region in candidate:
        matched_boxes: list[tuple] = []
        matched_sizes: list[float] = []
        for other_candidate in all_candidates:
            for other_region in other_candidate:
                if _text_matches(region, other_region):
                    matched_boxes.append(other_region.box_2d)
                    matched_sizes.append(other_region.font_size_px)
                    break  # one match per candidate

        if len(matched_boxes) >= min_matches:
            median_box = tuple(
                max(0, min(1000, int(statistics.median(coords))))
                for coords in zip(*matched_boxes)
            )
            median_size = statistics.median(matched_sizes)
            refined.append(Region(
                text=region.text,
                box_2d=median_box,
                font_size_px=median_size,
            ))
        else:
            refined.append(region)

    return refined


def run(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    model: str = "gemini-3.1-flash-image-preview",
    thinking_budget: int = 1,
    candidates: int = 10,
    top_k: int = 2,
    timeout: int = 300,
) -> list[list[Region]]:
    """
    Detect all text regions via N parallel OCR calls with top-k consensus.

    Fires N parallel calls to Gemini, ranks by region count, picks top-k,
    and consensus-stabilizes each using median coordinates from all N results.

    Args:
        image_bytes: Raw bytes of the slide image (PNG or JPEG).
        mime_type:   MIME type of the image, e.g. "image/png".
        api_key:     Google AI Studio API key.
        model:       Gemini model name.
        thinking_budget: Gemini thinking token budget.
        candidates:  Number of parallel OCR calls (default 10).
        top_k:       How many top candidates to select (default 2).
        timeout:     HTTP timeout in seconds for each Gemini call.

    Returns:
        List of top_k region lists (each consensus-stabilized).
        Returns list of top_k empty lists if all candidates failed.
    """
    def _single_attempt() -> list[Region]:
        raw = _call_gemini(api_key, model, image_bytes, mime_type, OCR_PROMPT, timeout=timeout, thinking_budget=thinking_budget)
        return _parse_regions(raw)

    results: list[list[Region]] = []
    with ThreadPoolExecutor(max_workers=candidates) as pool:
        futures = [pool.submit(_single_attempt) for _ in range(candidates)]
        for fut in as_completed(futures):
            try:
                regions = fut.result()
                results.append(regions)
            except Exception as exc:
                log.warning("OCR candidate failed: %s", exc)

    empty_result = [[] for _ in range(top_k)]

    if not results:
        log.error("All %d OCR candidates failed — no text overlay.", candidates)
        return empty_result

    # Sort by region count descending, pick top-k
    ranked = sorted(results, key=len, reverse=True)
    top = ranked[:top_k]

    # Pad if fewer successful candidates than top_k
    while len(top) < top_k:
        top.append(top[-1])

    log.info(
        "OCR %d/%d succeeded — top-%d have %s regions (all: %s)",
        len(results), candidates, top_k, [len(r) for r in top],
        [len(r) for r in results],
    )

    if not top[0]:
        log.warning("All %d OCR candidates returned 0 regions.", candidates)
        return empty_result

    # Consensus-stabilize each top candidate
    stabilized = [_consensus_refine(c, results) for c in top]
    return stabilized
