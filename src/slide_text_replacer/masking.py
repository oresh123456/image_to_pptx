"""
Module: masking
===============
Converts text region bounding boxes into a binary PNG mask for LaMa inpainting.

White pixels in the mask tell LaMa to reconstruct that region from the
surrounding visual context. Black pixels are left untouched. The mask is
produced locally with no external API calls — it's purely a Pillow operation.

Core functions (used in the pipeline):
  - build_mask(image_bytes, regions, padding_px, blur_radius, skip_watermark)
    -> bytes:
    The single pipeline entry point. Opens the image to read its dimensions,
    converts each region's normalized 0-1000 box_2d to pixel coordinates,
    adds padding, paints white rectangles, applies Gaussian blur, and returns
    the mask as PNG bytes. Runs in the ThreadPoolExecutor worker alongside
    enrichment.

Helper / tuning functions:
  - _is_watermark(text) -> bool:
    Returns True if the region text contains "notebooklm" (case-insensitive).
    NotebookLM watermarks always include this string; they are excluded from
    the mask so LaMa does not try to inpaint them (they're at a fixed position
    and we don't want to add them back as editable text either).

Pipeline role: runs after ocr.run() returns, in parallel with enrichment.run()
  within each slide's worker future. Its output (mask PNG bytes) is passed
  directly to inpainting.inpaint().

Tuning notes (from notes.md §6.5):
  - 12px padding: LaMa handles oversized masks well. Under-masking leaves
    visible text fragments at the edges of erased regions.
  - GaussianBlur radius 2: soft edges blend better into the background
    than hard rectangle boundaries, especially on slides with gradients.
  - skip_watermark=True: the NotebookLM watermark is near bottom-right at
    a known location; erasing it leaves an unnatural patch and it should
    not be recreated as an editable text box.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw, ImageFilter

from slide_text_replacer.schemas import EnrichedRegion

log = logging.getLogger(__name__)


def _is_watermark(text: str) -> bool:
    """
    Return True if the region text appears to be a NotebookLM watermark.

    Detection is a case-insensitive substring match on "notebooklm". The
    watermark always contains this string as visible text in the exported PPTX.

    Args:
        text: The text content of the region.

    Returns:
        True if the region text contains "notebooklm" (case-insensitive).
    """
    return bool(text) and "notebooklm" in text.strip().lower()


def build_mask(
    image_bytes: bytes,
    regions: list[EnrichedRegion],
    padding_px: int = 12,
    blur_radius: float = 2.0,
    skip_watermark: bool = True,
) -> bytes:
    """
    Generate a binary PNG mask covering all text regions in the slide image.

    Each region's box_2d (ymin, xmin, ymax, xmax) in 0-1000 normalized space
    is converted to pixel coordinates relative to the image dimensions, then
    expanded by padding_px on each side. White rectangles are drawn on a black
    canvas. A Gaussian blur is applied to soften the edges. The result is
    encoded as PNG and returned.

    Args:
        image_bytes:    Raw bytes of the slide image (PNG or JPEG). Read to
                        determine pixel dimensions — the image is not modified.
        regions:        Enriched text regions. Only box_2d and text are used;
                        font metadata is ignored at this stage.
        padding_px:     Pixels of padding added around each bbox on all sides.
                        Default 12. Increase to 16 if LaMa leaves edge artifacts.
        blur_radius:    GaussianBlur radius applied after painting. Default 2.0.
                        Set to 0.0 for hard rectangle edges (useful in tests).
        skip_watermark: If True, regions whose text contains "notebooklm" are
                        excluded from the mask. Default True.

    Returns:
        PNG image bytes of the mask with the same (width, height) as image_bytes.
        White pixels mark regions to inpaint; black pixels are left unchanged.
    """
    with Image.open(io.BytesIO(image_bytes)) as im:
        img_w, img_h = im.size

    mask = Image.new("L", (img_w, img_h), 0)
    draw = ImageDraw.Draw(mask)

    painted = 0
    for region in regions:
        if skip_watermark and _is_watermark(region.text):
            log.debug("Skipping watermark region: %r", region.text[:40])
            continue

        ymin, xmin, ymax, xmax = region.box_2d

        # Denormalize from 0-1000 to pixel coordinates.
        x1 = max(0,     int(xmin / 1000 * img_w) - padding_px)
        y1 = max(0,     int(ymin / 1000 * img_h) - padding_px)
        x2 = min(img_w, int(xmax / 1000 * img_w) + padding_px)
        y2 = min(img_h, int(ymax / 1000 * img_h) + padding_px)

        if x2 - x1 < 3 or y2 - y1 < 3:
            log.debug("Skipping degenerate bbox for %r", region.text[:30])
            continue

        draw.rectangle([x1, y1, x2, y2], fill=255)
        painted += 1

    log.debug(
        "Mask built: %d region(s) painted on %dx%d image.", painted, img_w, img_h
    )

    if blur_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()
