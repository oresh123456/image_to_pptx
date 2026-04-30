# schemas

Frozen dataclasses that define the data contracts between pipeline stages. No functions, no I/O — pure data shapes.

## `Region`

OCR output. Produced by `ocr.run()`, consumed by `enrichment.run()` and `masking.build_mask()`.

| Field          | Type                          | Constraints                             |
|----------------|-------------------------------|-----------------------------------------|
| `text`         | `str`                         | Non-empty. Hebrew words are space-separated. |
| `box_2d`       | `tuple[int, int, int, int]`   | `(ymin, xmin, ymax, xmax)`, each in [0, 1000]. |
| `font_size_px` | `float`                       | Positive. Estimated single-line height in pixels. |

## `EnrichedRegion`

Enrichment output. Produced by `enrichment.run()`, consumed by `masking.build_mask()` and `reconstruction.rebuild_slide()`.

| Field          | Type                          | Constraints                             |
|----------------|-------------------------------|-----------------------------------------|
| `text`         | `str`                         | Same as Region.                         |
| `box_2d`       | `tuple[int, int, int, int]`   | Same as Region (may be refined).        |
| `font_size_px` | `float`                       | Same as Region (may be refined).        |
| `font_family`  | `str`                         | One of: `"Heebo"`, `"Rubik"`, `"Assistant"`, `"Frank Ruhl Libre"`, `"Heebo Black"`. |
| `font_weight`  | `str`                         | `"regular"` or `"bold"`.                |
| `color`        | `str`                         | `"#RRGGBB"` hex format.                |

## `SlideData`

Not currently used in the active pipeline. Reserved for future serialization.

| Field          | Type                          | Constraints                             |
|----------------|-------------------------------|-----------------------------------------|
| `slide_number` | `int`                         | 1-based.                                |
| `image_size`   | `tuple[int, int]`             | `(width_px, height_px)`.                |
| `regions`      | `list[EnrichedRegion]`        | May be empty.                           |

## Dependencies

None (stdlib `dataclasses` only).
