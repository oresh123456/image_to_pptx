"""
Tests for enrichment.py — Gemini vision enrichment and response parsing.

Verifies I/O contracts documented in docs/modules/enrichment.md.
All tests are local — no API calls. HTTP mocked via unittest.mock.patch.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from slide_text_replacer.enrichment import (
    _build_prompt,
    _parse_enriched,
    _apply_defaults,
    run,
)
from slide_text_replacer.schemas import Region, EnrichedRegion


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_regions() -> list[Region]:
    """Build 3 sample Region objects for testing."""
    return [
        Region(text="מהלך אסטרטגי", box_2d=(77, 95, 124, 500), font_size_px=38.0),
        Region(text="ClimateTech", box_2d=(130, 95, 165, 350), font_size_px=22.0),
        Region(text="פתרונות", box_2d=(200, 95, 260, 900), font_size_px=18.0),
    ]


def _make_gemini_response(body_json: str) -> MagicMock:
    """Build a mock HTTP response that mimics Gemini generateContent."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": body_json}]
            }
        }]
    }
    return resp


# ── _build_prompt(): output contract ─────────────────────────────────────────
# Input: list[Region] → Output: prompt string containing region data + font palette.

def test_build_prompt_contains_region_text():
    """Input: regions with Hebrew + English text → Output: prompt containing that text."""
    prompt = _build_prompt(_make_regions())
    assert "מהלך אסטרטגי" in prompt
    assert "ClimateTech" in prompt


def test_build_prompt_contains_font_palette():
    """Output: prompt must list all 5 locked font names."""
    prompt = _build_prompt(_make_regions())
    for font in ("Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"):
        assert font in prompt, f"Missing font {font!r} in prompt"


# ── _parse_enriched(): output contract ───────────────────────────────────────
# Input: raw JSON + fallback regions → Output: list[EnrichedRegion], len == len(regions).

def test_parse_enriched_valid_response():
    """Input: well-formed response → Output: EnrichedRegions with correct visual fields."""
    regions = _make_regions()
    response = json.dumps([
        {"text": "מהלך אסטרטגי", "box_2d": [77, 95, 124, 500], "font_size_px": 38,
         "font_family": "Heebo", "font_weight": "bold", "color": "#1a3a8a"},
        {"text": "ClimateTech", "box_2d": [130, 95, 165, 350], "font_size_px": 22,
         "font_family": "Rubik", "font_weight": "regular", "color": "#333333"},
        {"text": "פתרונות", "box_2d": [200, 95, 260, 900], "font_size_px": 18,
         "font_family": "Assistant", "font_weight": "regular", "color": "#444444"},
    ])
    result = _parse_enriched(response, regions)
    assert len(result) == 3
    assert result[0].font_family == "Heebo"
    assert result[0].font_weight == "bold"
    assert result[0].color == "#1a3a8a"
    assert result[1].font_family == "Rubik"
    assert result[2].font_family == "Assistant"


def test_parse_enriched_short_response_pads_with_defaults():
    """Input: 1 item for 3 regions → Output: 3 EnrichedRegions, extras get defaults."""
    regions = _make_regions()
    response = json.dumps([{
        "text": "מהלך אסטרטגי", "box_2d": [77, 95, 124, 500], "font_size_px": 38,
        "font_family": "Heebo", "font_weight": "bold", "color": "#1a3a8a",
    }])
    result = _parse_enriched(response, regions)
    assert len(result) == 3
    assert result[1].font_family == "Heebo"
    assert result[2].color == "#000000"


def test_parse_enriched_strips_markdown_fences():
    """Input: JSON in ```json fences → Output: parsed correctly."""
    regions = [Region(text="test", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    inner = json.dumps([{
        "text": "test", "box_2d": [0, 0, 100, 100], "font_size_px": 16,
        "font_family": "Heebo", "font_weight": "regular", "color": "#000000",
    }])
    raw = f"```json\n{inner}\n```"
    result = _parse_enriched(raw, regions)
    assert len(result) == 1
    assert result[0].text == "test"


# ── _parse_enriched(): fallback defaults per field ───────────────────────────

def test_parse_enriched_invalid_font_family_falls_back():
    """Input: font_family not in palette → Output: defaults to "Heebo"."""
    regions = [Region(text="test", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    response = json.dumps([{
        "text": "test", "box_2d": [0, 0, 100, 100], "font_size_px": 16,
        "font_family": "Arial", "font_weight": "regular", "color": "#000000",
    }])
    result = _parse_enriched(response, regions)
    assert result[0].font_family == "Heebo"


def test_parse_enriched_invalid_font_weight_falls_back():
    """Input: font_weight not "regular"/"bold" → Output: defaults to "regular"."""
    regions = [Region(text="test", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    response = json.dumps([{
        "text": "test", "box_2d": [0, 0, 100, 100], "font_size_px": 16,
        "font_family": "Heebo", "font_weight": "semi-bold", "color": "#000000",
    }])
    result = _parse_enriched(response, regions)
    assert result[0].font_weight == "regular"


def test_parse_enriched_invalid_color_falls_back():
    """Input: color not matching #RRGGBB → Output: defaults to "#000000"."""
    regions = [Region(text="test", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    response = json.dumps([{
        "text": "test", "box_2d": [0, 0, 100, 100], "font_size_px": 16,
        "font_family": "Heebo", "font_weight": "regular", "color": "red",
    }])
    result = _parse_enriched(response, regions)
    assert result[0].color == "#000000"


# ── _parse_enriched(): error handling ────────────────────────────────────────

def test_parse_enriched_non_array_raises():
    """Input: JSON object (not array) → raises ValueError."""
    regions = [Region(text="x", box_2d=(0, 0, 10, 10), font_size_px=16.0)]
    with pytest.raises(ValueError, match="JSON array"):
        _parse_enriched('{"not": "an array"}', regions)


# ── _apply_defaults(): output contract ───────────────────────────────────────
# Input: list[Region] → Output: list[EnrichedRegion] with Heebo/regular/#000000.

def test_apply_defaults_uses_heebo_regular_black():
    """Input: Region → Output: EnrichedRegion with documented default values."""
    regions = [Region(text="שלום", box_2d=(10, 20, 30, 40), font_size_px=16.0)]
    result = _apply_defaults(regions)
    assert len(result) == 1
    assert result[0].font_family == "Heebo"
    assert result[0].font_weight == "regular"
    assert result[0].color == "#000000"
    assert result[0].text == "שלום"
    assert result[0].box_2d == (10, 20, 30, 40)


# ── run(): output contract ───────────────────────────────────────────────────
# Input: image_bytes, regions, api_key → Output: list[EnrichedRegion]

@patch("slide_text_replacer.enrichment.requests.post")
def test_run_empty_regions_no_api_call(mock_post, sample_image_bytes):
    """Input: empty regions → Output: empty list, no HTTP call made."""
    result = run(sample_image_bytes, "image/png", [], "fake-key")
    assert result == []
    mock_post.assert_not_called()


# ── run(): error handling ────────────────────────────────────────────────────
# All failures → falls back to defaults (never raises).

@patch("slide_text_replacer.retry.time.sleep")
@patch("slide_text_replacer.enrichment.requests.post")
def test_run_falls_back_on_exhausted_retries(mock_post, mock_sleep, sample_image_bytes):
    """Input: API fails on all attempts → Output: defaults (Heebo/regular/#000000)."""
    mock_post.side_effect = RuntimeError("connection error")
    regions = [Region(text="test", box_2d=(0, 0, 100, 100), font_size_px=20.0)]

    result = run(sample_image_bytes, "image/png", regions, "fake-key")
    assert len(result) == 1
    assert result[0].font_family == "Heebo"
    assert result[0].font_weight == "regular"
    assert result[0].color == "#000000"
    assert mock_post.call_count == 2
