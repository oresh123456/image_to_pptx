"""
Tests for masking.py — deterministic mask generation from text region bboxes.

Verifies I/O contracts documented in docs/modules/masking.md.
All tests are local — no API calls. Synthetic images, pixel-level assertions.
"""

import io

import pytest
from PIL import Image

from slide_text_replacer.masking import build_mask, _is_watermark
from slide_text_replacer.schemas import EnrichedRegion


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_image_bytes(w: int = 200, h: int = 200) -> bytes:
    """Create a solid grey PNG image of the given dimensions."""
    img = Image.new("RGB", (w, h), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_region(
    text: str, ymin: int, xmin: int, ymax: int, xmax: int,
    font_size_px: float = 20.0,
) -> EnrichedRegion:
    """Build a minimal EnrichedRegion with the given text and bbox."""
    return EnrichedRegion(
        text=text, box_2d=(ymin, xmin, ymax, xmax), font_size_px=font_size_px,
        font_family="Heebo", font_weight="regular", color="#000000",
    )


def _open_mask(mask_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(mask_bytes))


# ── _is_watermark: output contract ──────────────────────────────────────────
# Input: text string → Output: True if contains "notebooklm" (case-insensitive).

def test_is_watermark_detects_notebooklm():
    """Input: variations of "NotebookLM" → Output: True."""
    assert _is_watermark("NotebookLM") is True
    assert _is_watermark("notebooklm") is True
    assert _is_watermark("NOTEBOOKLM") is True
    assert _is_watermark("Created by NotebookLM") is True


def test_is_watermark_rejects_normal_text():
    """Input: normal text → Output: False."""
    assert _is_watermark("מהלך אסטרטגי") is False
    assert _is_watermark("ClimateTech") is False
    assert _is_watermark("") is False


# ── build_mask(): output format ──────────────────────────────────────────────
# Input: image_bytes, regions → Output: PNG bytes, same dimensions as input.

def test_mask_dimensions_match_image():
    """Input: 640x480 image → Output: mask with same (640, 480) dimensions."""
    image = _make_image_bytes(640, 480)
    region = _make_region("text", ymin=100, xmin=100, ymax=200, xmax=900)
    mask_bytes = build_mask(image, [region])
    mask = _open_mask(mask_bytes)
    assert mask.size == (640, 480)


def test_empty_regions_produces_black_mask():
    """Input: empty regions list → Output: all-black mask (no areas to inpaint)."""
    image = _make_image_bytes(100, 100)
    mask_bytes = build_mask(image, [], padding_px=0, blur_radius=0.0)
    mask = _open_mask(mask_bytes)
    pixels = list(mask.getdata())
    assert all(p == 0 for p in pixels)


# ── build_mask(): region coverage ────────────────────────────────────────────
# White pixels = text areas to inpaint. Black = preserve.

def test_mask_covers_region_center():
    """Input: region at center of image → Output: white pixel at region center."""
    image = _make_image_bytes(200, 200)
    region = _make_region("title", ymin=250, xmin=250, ymax=500, xmax=750)
    mask_bytes = build_mask(image, [region], padding_px=0, blur_radius=0.0)
    mask = _open_mask(mask_bytes)
    # Pixel coords: x=250/1000*200=50→750/1000*200=150, y=250/1000*200=50→500/1000*200=100
    center_px = mask.getpixel((100, 75))
    assert center_px == 255


# ── build_mask(): padding ────────────────────────────────────────────────────

def test_mask_extends_beyond_region_by_padding():
    """Input: padding_px=12 → Output: mask extends 12px outside region boundary."""
    image = _make_image_bytes(1000, 1000)
    region = _make_region("body", ymin=500, xmin=500, ymax=600, xmax=600)
    mask_bytes = build_mask(image, [region], padding_px=12, blur_radius=0.0)
    mask = _open_mask(mask_bytes)
    # Region pixel coords: [500,500]→[600,600]. With padding: starts at 488.
    px = mask.getpixel((488, 488))
    assert px == 255


def test_mask_without_padding_leaves_border_black():
    """Input: padding_px=0 → Output: pixel just outside region is black."""
    image = _make_image_bytes(1000, 1000)
    region = _make_region("body", ymin=500, xmin=500, ymax=600, xmax=600)
    mask_bytes = build_mask(image, [region], padding_px=0, blur_radius=0.0)
    mask = _open_mask(mask_bytes)
    outside_px = mask.getpixel((499, 500))
    assert outside_px == 0


# ── build_mask(): watermark filtering ────────────────────────────────────────

def test_watermark_region_excluded_from_mask():
    """Input: "NotebookLM" region, skip_watermark=True → Output: all-black mask."""
    image = _make_image_bytes(200, 200)
    region = _make_region("NotebookLM", ymin=100, xmin=100, ymax=200, xmax=900)
    mask_bytes = build_mask(image, [region], padding_px=0, blur_radius=0.0, skip_watermark=True)
    mask = _open_mask(mask_bytes)
    pixels = list(mask.getdata())
    assert all(p == 0 for p in pixels)


def test_watermark_region_included_when_skip_disabled():
    """Input: "NotebookLM" region, skip_watermark=False → Output: region is masked."""
    image = _make_image_bytes(200, 200)
    region = _make_region("NotebookLM", ymin=100, xmin=100, ymax=200, xmax=900)
    mask_bytes = build_mask(image, [region], padding_px=0, blur_radius=0.0, skip_watermark=False)
    mask = _open_mask(mask_bytes)
    center_x = int((100 + 900) / 2 / 1000 * 200)
    center_y = int((100 + 200) / 2 / 1000 * 200)
    px = mask.getpixel((center_x, center_y))
    assert px == 255
