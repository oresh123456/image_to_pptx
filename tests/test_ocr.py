"""
Tests for ocr.py — Gemini OCR call and response parsing.

Verifies I/O contracts documented in docs/modules/ocr.md.
All tests are local — no API calls. HTTP mocked via unittest.mock.patch.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from slide_text_replacer.ocr import _parse_regions, _extract_json_array, run
from slide_text_replacer.schemas import Region


# ── _parse_regions: output contract ──────────────────────────────────────────
# Input: raw JSON string → Output: list[Region]

def test_parse_regions_valid_json():
    """Input: well-formed JSON array → Output: list[Region] with correct fields."""
    raw = json.dumps([
        {"text": "שלום", "box_2d": [10, 20, 100, 500], "font_size_px": 24},
        {"text": "Hello", "box_2d": [200, 50, 300, 900], "font_size_px": 18},
        {"text": "123", "box_2d": [400, 100, 450, 800], "font_size_px": 12},
    ])
    regions = _parse_regions(raw)
    assert len(regions) == 3
    assert regions[0].text == "שלום"
    assert regions[1].text == "Hello"
    assert regions[2].font_size_px == 12.0


def test_parse_regions_strips_markdown_fences():
    """Input: JSON wrapped in ```json fences → Output: parsed correctly."""
    inner = json.dumps([{"text": "title", "box_2d": [0, 0, 100, 1000], "font_size_px": 20}])
    raw = f"```json\n{inner}\n```"
    regions = _parse_regions(raw)
    assert len(regions) == 1
    assert regions[0].text == "title"


def test_parse_regions_clamps_box_coords():
    """Input: box_2d with out-of-range values → Output: clamped to [0, 1000]."""
    raw = json.dumps([
        {"text": "edge", "box_2d": [-50, -10, 1200, 1050], "font_size_px": 16}
    ])
    regions = _parse_regions(raw)
    assert regions[0].box_2d == (0, 0, 1000, 1000)


def test_parse_regions_defaults_invalid_font_size():
    """Input: font_size_px <= 0 → Output: defaulted to 16.0."""
    raw = json.dumps([
        {"text": "small", "box_2d": [10, 10, 50, 50], "font_size_px": 0},
        {"text": "neg", "box_2d": [60, 10, 100, 50], "font_size_px": -5},
    ])
    regions = _parse_regions(raw)
    assert regions[0].font_size_px == 16.0
    assert regions[1].font_size_px == 16.0


def test_parse_regions_empty_array():
    """Input: empty JSON array → Output: empty list."""
    regions = _parse_regions("[]")
    assert regions == []


# ── _parse_regions: input filtering ──────────────────────────────────────────
# Items with missing/invalid fields are skipped silently.

def test_parse_regions_skips_empty_text():
    """Input: item with empty text → Output: skipped, only valid items returned."""
    raw = json.dumps([
        {"text": "", "box_2d": [0, 0, 100, 100], "font_size_px": 16},
        {"text": "valid", "box_2d": [200, 200, 400, 400], "font_size_px": 16},
    ])
    regions = _parse_regions(raw)
    assert len(regions) == 1
    assert regions[0].text == "valid"


def test_parse_regions_skips_missing_box():
    """Input: item without box_2d → Output: skipped."""
    raw = json.dumps([
        {"text": "no box", "font_size_px": 16},
        {"text": "has box", "box_2d": [0, 0, 100, 100], "font_size_px": 16},
    ])
    regions = _parse_regions(raw)
    assert len(regions) == 1
    assert regions[0].text == "has box"


# ── _parse_regions: error handling ───────────────────────────────────────────

def test_parse_regions_non_array_raises():
    """Input: JSON object (not array) → raises ValueError."""
    with pytest.raises(ValueError, match="JSON array"):
        _parse_regions('{"text": "not an array"}')


# ── run(): output contract ───────────────────────────────────────────────────
# Input: image_bytes, mime_type, api_key, model → Output: list[Region]

def _make_gemini_response(regions_json: str) -> MagicMock:
    """Build a mock HTTP response that mimics Gemini generateContent."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": regions_json}]
            }
        }]
    }
    return resp


@patch("slide_text_replacer.ocr.requests.post")
def test_run_success_returns_regions(mock_post, sample_image_bytes):
    """Input: valid image → Output: list[Region] from Gemini response."""
    regions_json = json.dumps([
        {"text": "title", "box_2d": [10, 10, 100, 900], "font_size_px": 30}
    ])
    mock_post.return_value = _make_gemini_response(regions_json)

    result = run(sample_image_bytes, "image/png", "fake-key", "gemini-2.5-pro", candidates=1)
    assert len(result) == 1
    assert result[0].text == "title"
    assert mock_post.call_count == 1


# ── run(): best-of-N candidate selection ─────────────────────────────────────

@patch("slide_text_replacer.ocr.requests.post")
def test_run_picks_candidate_with_most_regions(mock_post, sample_image_bytes):
    """3 candidates return different region counts → picks the one with most."""
    resp_1 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
    ]))
    resp_3 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
        {"text": "b", "box_2d": [200, 200, 300, 300], "font_size_px": 16},
        {"text": "c", "box_2d": [400, 400, 500, 500], "font_size_px": 16},
    ]))
    resp_2 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
        {"text": "b", "box_2d": [200, 200, 300, 300], "font_size_px": 16},
    ]))
    mock_post.side_effect = [resp_1, resp_3, resp_2]

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert len(result) == 3
    assert mock_post.call_count == 3


@patch("slide_text_replacer.ocr.requests.post")
def test_run_partial_failures_still_returns_best(mock_post, sample_image_bytes):
    """2/3 candidates fail → still returns the successful one."""
    good_resp = _make_gemini_response(json.dumps([
        {"text": "survivor", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
    ]))
    mock_post.side_effect = [
        RuntimeError("fail 1"),
        RuntimeError("fail 2"),
        good_resp,
    ]

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert len(result) == 1
    assert result[0].text == "survivor"


# ── run(): error handling ────────────────────────────────────────────────────
# All failures → empty list (never raises to caller).

@patch("slide_text_replacer.ocr.requests.post")
def test_run_returns_empty_on_all_candidates_failed(mock_post, sample_image_bytes):
    """Input: all candidates fail → Output: empty list (graceful degradation)."""
    mock_post.side_effect = RuntimeError("network error")

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert result == []
    assert mock_post.call_count == 3


# ── json-repair fallback tests ──────────────────────────────────────────────

def test_extract_json_array_json_repair_fixes_single_quotes():
    """json-repair catches single-quoted JSON that regex doesn't fix."""
    raw = "[{'text': 'hello', 'box_2d': [10, 20, 100, 500], 'font_size_px': 24}]"
    result = _extract_json_array(raw)
    assert len(result) == 1
    assert result[0]["text"] == "hello"


def test_extract_json_array_json_repair_fixes_unquoted_keys():
    """json-repair catches unquoted keys that regex doesn't fix."""
    raw = '[{text: "שלום", box_2d: [10, 20, 100, 500], font_size_px: 24}]'
    result = _extract_json_array(raw)
    assert len(result) == 1
    assert result[0]["text"] == "שלום"
