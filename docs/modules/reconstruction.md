# reconstruction

Final per-slide stage. Replaces the background image with the inpainted version and overlays editable text boxes. Runs on the main thread (python-pptx is not thread-safe).

## Public functions

### `rebuild_slide(slide, old_pic, clean_image_bytes, enriched_regions, config) -> None`

| Input                | Type                   | Description                              |
|----------------------|------------------------|------------------------------------------|
| `slide`              | `Slide`                | python-pptx Slide object.               |
| `old_pic`            | `Shape`                | Existing Picture shape to replace.       |
| `clean_image_bytes`  | `bytes`                | Inpainted image from `inpainting.inpaint()`. |
| `enriched_regions`   | `list[EnrichedRegion]` | Text regions from `enrichment.run()`.    |
| `config`             | `Config`               | Pipeline config (font sizing params).    |

| Output | Type   | Description                     |
|--------|--------|---------------------------------|
| return | `None` | Modifies `slide` in place.      |

| Raises | When |
|--------|------|
| *(never)* | Per-text-box exceptions are caught and logged. Partial overlay > total failure. |

### Behavior details

1. Captures `old_pic` EMU position and size.
2. Replaces background image (`_replace_picture_image`).
3. For each `EnrichedRegion`, adds a text box (`_add_text_box`):
   - Denormalizes `box_2d` from 0-1000 to EMU using picture bounds.
   - Font size: `pt = px * config.font_px_to_pt` (default `0.75`, i.e. 96 DPI), clamped to `[config.font_min_pt, config.font_max_pt]` (default `[8.0, 60.0]` pt). Trust model font-size estimates over geometric inference from bbox height.
   - Sets font via `pptx_helpers.set_run_font()` (both Latin and complex-script).
   - Sets RTL via `pptx_helpers.set_paragraph_rtl()`.
   - Alignment: `PP_ALIGN.RIGHT`.
   - Color from `region.color`; falls back to black on invalid hex.
   - No text box border, no margins, word wrap enabled, top-anchored.

## Dependencies

`python-pptx` (RGBColor, PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE, Emu, Pt), `pptx_helpers` (set_run_font, set_paragraph_rtl), `config` (Config), `schemas` (EnrichedRegion), stdlib `io`, `logging`.
