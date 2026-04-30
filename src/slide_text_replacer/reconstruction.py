"""
Module: reconstruction
======================
Assembles the final PPTX slide: replaces the original rasterized image with
the inpainted (text-erased) version, then overlays one editable text box per
enriched region.

The result is a slide that looks visually identical to the original (background
restored by LaMa, text at the correct position and size) but where every text
element is a native PowerPoint text box — selectable, editable, copy-pasteable,
and searchable.

Core functions (used in the pipeline):
  - rebuild_slide(slide, old_pic, clean_image_bytes, enriched_regions, config)
    -> None:
    The single pipeline entry point. Captures the picture's EMU position and
    size before replacing it, then calls _replace_picture_image() and
    _add_text_box() for each region. Modifies the slide in place.

Helper functions:
  - _replace_picture_image(slide, old_pic, new_image_bytes) -> None:
    Inserts a new Picture shape at old_pic's position/size, then removes
    old_pic. python-pptx has no in-place image replacement API — this is the
    correct workaround (add then remove). Must be called before adding text
    boxes so text shapes render on top of the background.
  - _parse_color(color_hex) -> RGBColor:
    Parse a "#RRGGBB" hex string into a python-pptx RGBColor object.
  - _add_text_box(slide, region, pic_left_emu, pic_top_emu,
                  pic_width_emu, pic_height_emu, config) -> None:
    Create one text box for one region. Converts box_2d (0-1000 normalized)
    to EMU using the picture's reference frame. Sets RTL, font, size, color.

Pipeline role: final per-slide stage, called on the MAIN thread after all
  ThreadPoolExecutor futures have completed. python-pptx is not thread-safe;
  all mutations to Slide objects happen here under the main thread.

Font sizing (notes.md §6.3):
  pt = px * config.font_px_to_pt  (default 0.75, the 96 DPI convention)
  Clamped to [config.font_min_pt, config.font_max_pt] (default 8–60 pt).

RTL rendering (notes.md §6.1 and §6.2):
  Every paragraph gets alignment=RIGHT + set_paragraph_rtl().
  Every run gets set_run_font() which sets both <a:latin> and <a:cs>.
"""

from __future__ import annotations

import io
import logging

from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.util import Emu, Pt

from slide_text_replacer.config import Config
from slide_text_replacer.pptx_helpers import set_run_font, set_paragraph_rtl
from slide_text_replacer.schemas import EnrichedRegion

log = logging.getLogger(__name__)


def _replace_picture_image(slide, old_pic, new_image_bytes: bytes) -> None:
    """
    Replace a slide picture's image while keeping its position and size.

    python-pptx does not expose an in-place image replacement API, so we
    add a new Picture shape at the same (left, top, width, height) and then
    remove the old shape from the XML tree. The new shape lands at the top
    of the z-order; call this before adding text boxes so text renders above
    the background.

    Args:
        slide:           The python-pptx Slide that contains old_pic.
        old_pic:         The existing Picture shape to replace.
        new_image_bytes: Raw bytes of the replacement image (PNG or JPEG).

    Returns:
        None. Modifies slide.shapes in place.
    """
    left, top     = old_pic.left, old_pic.top
    width, height = old_pic.width, old_pic.height

    slide.shapes.add_picture(
        io.BytesIO(new_image_bytes), left, top, width=width, height=height
    )
    old_pic._element.getparent().remove(old_pic._element)


def _parse_color(color_hex: str) -> RGBColor:
    """
    Parse a "#RRGGBB" hex color string into a python-pptx RGBColor.

    Args:
        color_hex: Color string in "#RRGGBB" format (the leading # is optional).

    Returns:
        RGBColor instance.

    Raises:
        ValueError: If color_hex is not a valid 6-digit hex color.
    """
    h = color_hex.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected 6-digit hex color, got: {color_hex!r}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return RGBColor(r, g, b)


def _add_text_box(
    slide,
    region: EnrichedRegion,
    pic_left_emu: int,
    pic_top_emu: int,
    pic_width_emu: int,
    pic_height_emu: int,
    config: Config,
) -> None:
    """
    Add a single editable text box to the slide for one enriched region.

    Converts the region's normalized 0-1000 bounding box to EMU coordinates
    using the picture's EMU position and size as the reference frame. Creates
    the text box with no margins, word wrap enabled, top-anchored, with a
    right-aligned RTL Hebrew paragraph containing a single run styled with
    the region's font, size, color, and bold setting.

    Args:
        slide:          The python-pptx Slide to add the text box to.
        region:         The enriched region with all visual metadata.
        pic_left_emu:   Left edge of the slide picture in EMU.
        pic_top_emu:    Top edge of the slide picture in EMU.
        pic_width_emu:  Width of the slide picture in EMU.
        pic_height_emu: Height of the slide picture in EMU.
        config:         Pipeline config for font sizing parameters.

    Returns:
        None. Adds a TextBox shape to the slide in place.
    """
    ymin, xmin, ymax, xmax = region.box_2d

    # Denormalize from 0-1000 to EMU using the picture's reference frame.
    left_emu = pic_left_emu + int(xmin / 1000 * pic_width_emu)
    top_emu  = pic_top_emu  + int(ymin / 1000 * pic_height_emu)
    w_emu    = max(Emu(10_000), int((xmax - xmin) / 1000 * pic_width_emu))
    h_emu    = max(Emu(10_000), int((ymax - ymin) / 1000 * pic_height_emu))

    tb = slide.shapes.add_textbox(left_emu, top_emu, w_emu, h_emu)
    tf = tb.text_frame
    tf.margin_left   = Emu(0)
    tf.margin_right  = Emu(0)
    tf.margin_top    = Emu(0)
    tf.margin_bottom = Emu(0)
    tf.word_wrap       = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.auto_size       = MSO_AUTO_SIZE.NONE

    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.RIGHT
    set_paragraph_rtl(para)

    run = para.add_run()
    run.text = region.text

    # Convert px → pt and clamp (notes.md §6.3).
    font_pt = region.font_size_px * config.font_px_to_pt
    font_pt = max(config.font_min_pt, min(config.font_max_pt, round(font_pt)))
    run.font.size = Pt(font_pt)
    run.font.bold = (region.font_weight == "bold")

    try:
        run.font.color.rgb = _parse_color(region.color)
    except ValueError:
        log.debug(
            "Unparseable color %r for %r — using black.", region.color, region.text[:20]
        )
        run.font.color.rgb = RGBColor(0, 0, 0)

    # Set font for both Latin and complex-script (Hebrew) — see notes.md §6.1.
    set_run_font(run, region.font_family)

    # Remove the text box border so it's invisible.
    tb.line.fill.background()


def rebuild_slide(
    slide,
    old_pic,
    clean_image_bytes: bytes,
    enriched_regions: list[EnrichedRegion],
    config: Config,
) -> None:
    """
    Replace a slide's background image and add editable text overlays.

    This is the main reconstruction entry point. It:
      1. Reads and stores the picture's current EMU position and size.
      2. Calls _replace_picture_image() to swap in the inpainted background.
      3. Calls _add_text_box() for each enriched region to create the overlay.

    Errors in individual text box creation are caught and logged without
    aborting the slide — a partial overlay is better than a failed slide.

    The slide is modified in place. Call prs.save() after all slides are done.

    Args:
        slide:             The python-pptx Slide object to modify.
        old_pic:           The original Picture shape (used for position/size
                           reference, then removed by _replace_picture_image).
        clean_image_bytes: Inpainted image bytes to use as the new background.
        enriched_regions:  Text regions with visual metadata for overlay.
        config:            Pipeline config containing font sizing constants.

    Returns:
        None. Modifies the slide in place.
    """
    # Capture position before the shape is removed.
    pic_left   = old_pic.left
    pic_top    = old_pic.top
    pic_width  = old_pic.width
    pic_height = old_pic.height

    _replace_picture_image(slide, old_pic, clean_image_bytes)
    log.debug(
        "Picture replaced. Adding %d text box(es).", len(enriched_regions)
    )

    for region in enriched_regions:
        try:
            _add_text_box(
                slide, region,
                pic_left, pic_top, pic_width, pic_height,
                config,
            )
        except Exception as exc:
            log.warning(
                "Failed to add text box for %r: %s", region.text[:30], exc
            )
