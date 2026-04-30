"""
Tests for schemas.py — frozen dataclass contracts between pipeline stages.

Verifies I/O contracts documented in docs/modules/schemas.md.
All tests are deterministic — no API calls or external resources.
"""

import pytest
from dataclasses import asdict

from slide_text_replacer.schemas import Region, EnrichedRegion, SlideData


# ── Region: field constraints ────────────────────────────────────────────────

def test_region_fields_stored_correctly():
    """Input: text, box_2d, font_size_px → Output: identical values accessible by attribute."""
    r = Region(text="שלום", box_2d=(10, 20, 30, 40), font_size_px=16.0)
    assert r.text == "שלום"
    assert r.box_2d == (10, 20, 30, 40)
    assert r.font_size_px == 16.0


def test_region_font_size_accepts_int():
    """Input: font_size_px as int → Output: stored without coercion."""
    r = Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=20)
    assert r.font_size_px == 20


def test_region_equality():
    """Input: two Regions with identical values → Output: equal."""
    r1 = Region(text="שלום", box_2d=(10, 20, 30, 40), font_size_px=16.0)
    r2 = Region(text="שלום", box_2d=(10, 20, 30, 40), font_size_px=16.0)
    assert r1 == r2


# ── Region: immutability ─────────────────────────────────────────────────────

def test_region_is_frozen():
    """Mutation attempt → raises exception (frozen dataclass)."""
    r = Region(text="hello", box_2d=(0, 0, 500, 500), font_size_px=14.0)
    with pytest.raises(Exception):
        r.text = "changed"  # type: ignore[misc]


# ── EnrichedRegion: field constraints ────────────────────────────────────────

def test_enriched_region_all_fields():
    """Input: all 6 fields → Output: all accessible and correctly typed."""
    r = EnrichedRegion(
        text="ציר חדשנות",
        box_2d=(100, 200, 300, 400),
        font_size_px=18.0,
        font_family="Heebo",
        font_weight="bold",
        color="#1a3a8a",
    )
    assert r.font_family == "Heebo"
    assert r.font_weight == "bold"
    assert r.color == "#1a3a8a"


def test_enriched_region_preserves_hebrew():
    """Input: Hebrew text with spaces → Output: text and spaces preserved."""
    text = "מהלך אסטרטגי אקלים"
    r = EnrichedRegion(
        text=text, box_2d=(77, 95, 124, 500), font_size_px=38.0,
        font_family="Heebo", font_weight="bold", color="#1a3a8a",
    )
    assert r.text == text
    assert " " in r.text


def test_enriched_region_roundtrip():
    """Input: EnrichedRegion → asdict → EnrichedRegion → Output: equals original."""
    original = EnrichedRegion(
        text="ציר חדשנות", box_2d=(100, 200, 300, 400), font_size_px=18.0,
        font_family="Heebo", font_weight="bold", color="#1a3a8a",
    )
    d = asdict(original)
    reconstructed = EnrichedRegion(**d)
    assert original == reconstructed


# ── EnrichedRegion: immutability ─────────────────────────────────────────────

def test_enriched_region_is_frozen():
    """Mutation attempt → raises exception (frozen dataclass)."""
    r = EnrichedRegion(
        text="test", box_2d=(0, 0, 100, 100), font_size_px=12.0,
        font_family="Rubik", font_weight="regular", color="#000000",
    )
    with pytest.raises(Exception):
        r.color = "#FF0000"  # type: ignore[misc]


# ── SlideData: field constraints ─────────────────────────────────────────────

def test_slide_data_holds_regions():
    """Input: slide_number, image_size, regions list → Output: all accessible."""
    region = EnrichedRegion(
        text="title", box_2d=(0, 0, 100, 1000), font_size_px=32.0,
        font_family="Heebo", font_weight="bold", color="#000000",
    )
    sd = SlideData(slide_number=3, image_size=(1920, 1080), regions=[region])
    assert sd.slide_number == 3
    assert sd.image_size == (1920, 1080)
    assert len(sd.regions) == 1
    assert sd.regions[0].text == "title"


def test_slide_data_empty_regions():
    """Input: empty regions list → Output: valid SlideData with regions == []."""
    sd = SlideData(slide_number=5, image_size=(1920, 1080), regions=[])
    assert sd.regions == []


# ── SlideData: immutability ──────────────────────────────────────────────────

def test_slide_data_is_frozen():
    """Mutation attempt → raises exception (frozen dataclass)."""
    sd = SlideData(slide_number=1, image_size=(1280, 720), regions=[])
    with pytest.raises(Exception):
        sd.slide_number = 2  # type: ignore[misc]
