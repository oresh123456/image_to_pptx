"""
Module: schemas
===============
Frozen dataclass definitions for inter-stage data shapes.

These are pure data containers — no logic, no methods beyond what dataclass
provides. All pipeline stages (OCR, enrichment, masking, reconstruction)
communicate through these types, treating them as the single source of truth
for what data a region carries at each stage.

Core types (used throughout the pipeline):
  - Region:          raw OCR output — text, bounding box, font size estimate
  - EnrichedRegion:  enriched output — adds font_family, font_weight, color
  - SlideData:       per-slide container combining image metadata and regions

Pipeline role: defined once, consumed by every module. Import from here,
  never reconstruct these dicts manually.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    """
    A single text region as returned by the OCR pass.

    Attributes:
        text: Exact text content of the region. Spaces between Hebrew words
              are preserved exactly as OCR returned them.
        box_2d: Bounding box as (ymin, xmin, ymax, xmax). Each value is an
                integer in [0, 1000], where 0 is the top/left edge and 1000
                is the bottom/right edge of the slide image. This is Gemini's
                native normalized coordinate format.
        font_size_px: Estimated rendered font size in pixels for a single line
                      of text in this region. For multi-line blocks this is
                      the per-line height, NOT the full block height.
    """

    text: str
    box_2d: tuple[int, int, int, int]
    font_size_px: float


@dataclass(frozen=True)
class EnrichedRegion:
    """
    A text region after the vision-enrichment pass.

    All fields from Region are present (and possibly refined by the enrichment
    model), plus visual metadata that reconstruction uses to style the text box.

    Attributes:
        text: Exact text content, preserved from OCR.
        box_2d: Refined bounding box (ymin, xmin, ymax, xmax), 0-1000.
                Possibly adjusted by the enrichment model for better accuracy.
        font_size_px: Refined single-line font size estimate in pixels.
        font_family: Font name chosen from the locked palette:
                     "Heebo", "Rubik", "Assistant", "Frank Ruhl Libre",
                     "Heebo Black". See notes.md §5 for palette rationale.
        font_weight: "regular" or "bold". No other values are used.
        color: Primary text color as a hex string "#RRGGBB". One color per
               region even if the actual text uses multiple colors.
    """

    text: str
    box_2d: tuple[int, int, int, int]
    font_size_px: float
    font_family: str
    font_weight: str   # "regular" | "bold"
    color: str         # "#RRGGBB"


@dataclass(frozen=True)
class SlideData:
    """
    All per-slide data needed for reconstruction.

    Not used directly in the current pipeline (the pipeline passes individual
    fields rather than wrapping them here), but useful for serialising a
    slide's complete state to JSON for caching or debugging.

    Attributes:
        slide_number: 1-based slide index.
        image_size: (width_px, height_px) of the slide's background image.
        regions: All enriched text regions for this slide, in the same order
                 that OCR detected them.
    """

    slide_number: int
    image_size: tuple[int, int]
    regions: list[EnrichedRegion]
