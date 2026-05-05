# ocr

Calls Gemini 2.5 Pro to detect all text regions in a slide image. First per-slide API call.

## Public functions

### `run(image_bytes, mime_type, api_key, model, thinking_budget, candidates) -> list[Region]`

| Input             | Type    | Default              | Description                     |
|-------------------|---------|----------------------|---------------------------------|
| `image_bytes`     | `bytes` | —                    | Raw slide image (PNG or JPEG).  |
| `mime_type`       | `str`   | —                    | `"image/png"` or `"image/jpeg"`. |
| `api_key`         | `str`   | —                    | Google AI Studio API key.       |
| `model`           | `str`   | `"gemini-3.1-flash-image-preview"` | Gemini model name.              |
| `thinking_budget` | `int`   | `1`                  | Thinking token budget (1 = minimal). |
| `candidates`      | `int`   | `3`                  | Parallel OCR calls; picks best (most regions). |

| Output | Type            | Description |
|--------|-----------------|-------------|
| return | `list[Region]`  | Detected text regions. Empty list on total failure. |

| Raises | When |
|--------|------|
| *(never)* | All exceptions caught internally. Returns `[]` if all candidates fail. |

### Best-of-N parallel strategy

- Fires `candidates` parallel calls via inner ThreadPoolExecutor.
- Picks the result with the most regions (more regions = more complete, no false positives observed).
- If some candidates fail, still returns the best successful result.
- If all candidates fail: logs error, returns `[]`.

### Output guarantees

- Each `Region` has non-empty `text`, valid `box_2d` (clamped to [0, 1000]), positive `font_size_px`.
- Invalid `font_size_px` defaults to `16.0`.
- Items with empty text or missing `box_2d` are silently skipped.
- Markdown code fences in Gemini response are stripped before parsing.

## Constraints

- HTTP timeout must be **300 seconds** (not 180s) — Gemini 2.5 Pro "thinking" can exceed 180s on complex slides.
- Prompt is versioned in `docs/prompts.md`. Do not change without testing on 3+ representative slides and version bump.

## Constants

| Name         | Type  | Description |
|--------------|-------|-------------|
| `OCR_PROMPT` | `str` | v1.0 prompt. Load-bearing — do not change without version bump. |

## Dependencies

`requests`, `schemas` (Region), stdlib `base64`, `json`, `logging`, `concurrent.futures`.
