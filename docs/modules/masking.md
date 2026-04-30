# masking

Converts text region bounding boxes into a binary PNG mask for LaMa inpainting. Local operation, no API calls.

## Public functions

### `build_mask(image_bytes, regions, padding_px, blur_radius, skip_watermark) -> bytes`

| Input            | Type                    | Default | Description                              |
|------------------|-------------------------|---------|------------------------------------------|
| `image_bytes`    | `bytes`                 | —       | Raw slide image (read for dimensions only). |
| `regions`        | `list[EnrichedRegion]`  | —       | Text regions from enrichment.            |
| `padding_px`     | `int`                   | `12`    | Pixels of padding around each bbox.      |
| `blur_radius`    | `float`                 | `2.0`   | GaussianBlur radius. `0.0` = hard edges. |
| `skip_watermark` | `bool`                  | `True`  | Exclude regions containing "notebooklm". |

| Output | Type    | Description                                              |
|--------|---------|----------------------------------------------------------|
| return | `bytes` | PNG image bytes. Same dimensions as input image. Black background, white = text areas. |

| Raises | When |
|--------|------|
| *(never)* | Always produces a valid mask. |

### Behavior details

- Denormalizes `box_2d` from 0-1000 to pixel coordinates using image dimensions.
- Draws white rectangles with `padding_px` expansion on all sides.
- Applies Gaussian blur if `blur_radius > 0`.
- Skips regions where text contains "notebooklm" (case-insensitive) when `skip_watermark=True`.
- Skips degenerate bboxes (< 3px in either dimension after denormalization).
- Empty `regions` list produces an all-black mask.

## Dependencies

`Pillow` (Image, ImageDraw, ImageFilter), `schemas` (EnrichedRegion), stdlib `io`, `logging`.
