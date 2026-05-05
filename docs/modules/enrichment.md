# enrichment

Second Gemini call per slide. Enriches raw OCR regions with font family, weight, color, and optionally refined geometry.

## Public functions

### `run(image_bytes, mime_type, regions, api_key, model, thinking_budget) -> list[EnrichedRegion]`

| Input             | Type            | Default              | Description                        |
|-------------------|-----------------|----------------------|------------------------------------|
| `image_bytes`     | `bytes`         | —                    | Same slide image used in OCR pass. |
| `mime_type`       | `str`           | —                    | `"image/png"` or `"image/jpeg"`.   |
| `regions`         | `list[Region]`  | —                    | OCR output from `ocr.run()`.       |
| `api_key`         | `str`           | —                    | Google AI Studio API key.          |
| `model`           | `str`           | `"gemini-3.1-flash-image-preview"` | Gemini model name.                 |
| `thinking_budget` | `int`           | `1`                  | Thinking token budget (1 = minimal). |

| Output | Type                    | Description |
|--------|-------------------------|-------------|
| return | `list[EnrichedRegion]`  | Same length as input `regions`. Falls back to defaults on failure.

| Raises | When |
|--------|------|
| *(never)* | All exceptions caught internally. Falls back to defaults after 2 failed attempts. |

### Special cases

- **Empty `regions`**: returns `[]` immediately, no API call made.

### Retry behavior

- 2 attempts via `retry_call(max_attempts=2, base_delay=1.0)`.
- On `RetryExhausted`: logs warning, returns `_apply_defaults(regions)`.

### Fallback defaults (per item)

| Field         | Default value     | Condition                      |
|---------------|-------------------|--------------------------------|
| `font_family` | `"Heebo"`         | Not in `VALID_FONT_FAMILIES`.  |
| `font_weight` | `"regular"`       | Not `"regular"` or `"bold"`.   |
| `color`       | `"#000000"`       | Doesn't match `#RRGGBB` regex. |
| `font_size_px`| original Region's | Not a positive number.          |
| `box_2d`      | original Region's | Not a list/tuple of 4 numbers.  |

### Output guarantees

- Output list always has exactly `len(regions)` items.
- All `font_family` values are in `VALID_FONT_FAMILIES`.
- All `color` values match `#RRGGBB`.
- All `box_2d` values clamped to [0, 1000].

## Dependencies

`requests`, `config` (VALID_FONT_FAMILIES), `retry` (retry_call, RetryExhausted), `schemas` (Region, EnrichedRegion), stdlib `base64`, `json`, `logging`, `re`.
