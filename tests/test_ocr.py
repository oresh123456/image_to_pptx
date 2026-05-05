"""
Tests for ocr.py — Gemini OCR with top-2 consensus stabilization.

Verifies I/O contracts documented in docs/modules/ocr.md:
  - run() fires N parallel OCR calls, returns top-2 consensus-stabilized candidates
  - _text_matches() fuzzy text + centroid proximity matching
  - _consensus_refine() median coordinate stabilization from all N candidates
  - _parse_regions() JSON parsing + validation

All tests are local — no API calls. HTTP mocked via unittest.mock.patch.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from slide_text_replacer.ocr import _parse_regions, _extract_json_array, run, _text_matches, _consensus_refine
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
def test_run_success_returns_two_candidates(mock_post, sample_image_bytes):
    """Input: valid image → Output: list of 2 region lists."""
    regions_json = json.dumps([
        {"text": "title", "box_2d": [10, 10, 100, 900], "font_size_px": 30}
    ])
    mock_post.return_value = _make_gemini_response(regions_json)

    result = run(sample_image_bytes, "image/png", "fake-key", "gemini-2.5-pro", candidates=1)
    assert len(result) == 2  # always returns 2 candidates
    assert len(result[0]) == 1
    assert result[0][0].text == "title"
    # With 1 candidate, both are the same (padded)
    assert len(result[1]) == 1
    assert mock_post.call_count == 1


# ── run(): top-2 selection + consensus ───────────────────────────────────────

@patch("slide_text_replacer.ocr.requests.post")
def test_run_picks_top2_by_region_count(mock_post, sample_image_bytes):
    """3 candidates → top-2 are the ones with most regions."""
    resp_1 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
    ]))
    resp_2 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
        {"text": "b", "box_2d": [200, 200, 300, 300], "font_size_px": 16},
        {"text": "c", "box_2d": [400, 400, 500, 500], "font_size_px": 16},
    ]))
    resp_3 = _make_gemini_response(json.dumps([
        {"text": "a", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
        {"text": "d", "box_2d": [600, 600, 700, 700], "font_size_px": 16},
    ]))
    mock_post.side_effect = [resp_1, resp_2, resp_3]

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert len(result) == 2  # always 2 candidates
    assert len(result[0]) == 3  # top candidate has 3 regions
    assert len(result[1]) == 2  # second has 2
    assert mock_post.call_count == 3


@patch("slide_text_replacer.ocr.requests.post")
def test_run_partial_failures_still_returns_best(mock_post, sample_image_bytes):
    """2/3 candidates fail → still returns 2 lists (padded from single success)."""
    good_resp = _make_gemini_response(json.dumps([
        {"text": "survivor", "box_2d": [10, 10, 100, 100], "font_size_px": 16},
    ]))
    mock_post.side_effect = [
        RuntimeError("fail 1"),
        RuntimeError("fail 2"),
        good_resp,
    ]

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert len(result) == 2
    assert result[0][0].text == "survivor"
    # Padded: both candidates are the same
    assert result[1][0].text == "survivor"


# ── run(): error handling ────────────────────────────────────────────────────
# All failures → empty list (never raises to caller).

@patch("slide_text_replacer.ocr.requests.post")
def test_run_returns_empty_on_all_candidates_failed(mock_post, sample_image_bytes):
    """Input: all candidates fail → Output: [[], []] (graceful degradation)."""
    mock_post.side_effect = RuntimeError("network error")

    result = run(sample_image_bytes, "image/png", "fake-key", candidates=3)
    assert result == [[], []]
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


# ── _text_matches tests ─────────────���────────────────────────────────────────

def test_text_matches_exact():
    """Exact same text + close centroids → match."""
    a = Region(text="שלום עולם", box_2d=(100, 100, 200, 400), font_size_px=16.0)
    b = Region(text="שלום עולם", box_2d=(105, 98, 205, 395), font_size_px=16.0)
    assert _text_matches(a, b) is True


def test_text_matches_fuzzy():
    """Slightly different text (>= 0.85 ratio) + close centroids → match."""
    a = Region(text="שלום עולם טוב", box_2d=(100, 100, 200, 400), font_size_px=16.0)
    b = Region(text="שלום עולם טו", box_2d=(100, 100, 200, 400), font_size_px=16.0)
    assert _text_matches(a, b) is True


def test_text_matches_centroid_filter():
    """Same text but far apart centroids → no match."""
    a = Region(text="שלום", box_2d=(100, 100, 200, 200), font_size_px=16.0)
    b = Region(text="שלום", box_2d=(700, 700, 800, 800), font_size_px=16.0)
    assert _text_matches(a, b) is False


def test_text_matches_different_text():
    """Completely different text → no match."""
    a = Region(text="hello", box_2d=(100, 100, 200, 200), font_size_px=16.0)
    b = Region(text="world", box_2d=(100, 100, 200, 200), font_size_px=16.0)
    assert _text_matches(a, b) is False


# ── _consensus_refine tests ──────────────��───────────────────────────────────

def test_consensus_refine_takes_median():
    """Jittered coords across candidates → median is taken."""
    candidate = [Region(text="title", box_2d=(100, 200, 300, 800), font_size_px=20.0)]
    all_candidates = [
        [Region(text="title", box_2d=(98, 198, 302, 798), font_size_px=19.0)],
        [Region(text="title", box_2d=(102, 202, 298, 802), font_size_px=21.0)],
        [Region(text="title", box_2d=(100, 200, 300, 800), font_size_px=20.0)],
        [Region(text="title", box_2d=(104, 196, 304, 796), font_size_px=22.0)],
    ]
    result = _consensus_refine(candidate, all_candidates, min_matches=3)
    assert len(result) == 1
    # Median of [98,102,100,104] = 101, [198,202,200,196] = 199, etc.
    # With 4 matches: median is average of middle two
    ymin = result[0].box_2d[0]
    assert 99 <= ymin <= 102  # median of [98,100,102,104]


def test_consensus_refine_below_min_keeps_original():
    """< min_matches → keeps original coords."""
    candidate = [Region(text="rare", box_2d=(100, 200, 300, 400), font_size_px=16.0)]
    all_candidates = [
        [Region(text="rare", box_2d=(110, 210, 310, 410), font_size_px=18.0)],
        [Region(text="other", box_2d=(500, 500, 600, 600), font_size_px=16.0)],
    ]
    result = _consensus_refine(candidate, all_candidates, min_matches=3)
    assert result[0].box_2d == (100, 200, 300, 400)
    assert result[0].font_size_px == 16.0


def test_consensus_refine_clamps_to_bounds():
    """Median result is clamped to [0, 1000]."""
    candidate = [Region(text="edge", box_2d=(0, 0, 1000, 1000), font_size_px=16.0)]
    all_candidates = [
        [Region(text="edge", box_2d=(0, 0, 1000, 1000), font_size_px=16.0)],
        [Region(text="edge", box_2d=(0, 0, 1000, 1000), font_size_px=16.0)],
        [Region(text="edge", box_2d=(0, 0, 1000, 1000), font_size_px=16.0)],
    ]
    result = _consensus_refine(candidate, all_candidates, min_matches=3)
    for coord in result[0].box_2d:
        assert 0 <= coord <= 1000
