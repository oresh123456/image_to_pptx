# ocr

Calls Gemini 2.5 Pro to detect all text regions in a slide image. First per-slide API call.

## Public functions

### `run(image_bytes, mime_type, api_key, model, thinking_budget, candidates) -> list[list[Region]]`

| Input             | Type    | Default              | Description                     |
|-------------------|---------|----------------------|---------------------------------|
| `image_bytes`     | `bytes` | —                    | Raw slide image (PNG or JPEG).  |
| `mime_type`       | `str`   | —                    | `"image/png"` or `"image/jpeg"`. |
| `api_key`         | `str`   | —                    | Google AI Studio API key.       |
| `model`           | `str`   | `"gemini-3.1-flash-image-preview"` | Gemini model name.              |
| `thinking_budget` | `int`   | `1`                  | Thinking token budget (1 = minimal). |
| `candidates`      | `int`   | `10`                 | Parallel OCR calls; top-2 selected + consensus-stabilized. |

| Output | Type                 | Description |
|--------|----------------------|-------------|
| return | `list[list[Region]]` | Top-2 candidates, each consensus-stabilized. `[[], []]` on total failure. |

| Raises | When |
|--------|------|
| *(never)* | All exceptions caught internally. Returns `[[], []]` if all candidates fail. |

### Best-of-N + top-2 + consensus strategy

- Fires `candidates` parallel calls via inner ThreadPoolExecutor.
- Ranks results by region count descending, picks top 2.
- If only 1 successful candidate, pads to 2 (duplicates it).
- Consensus-stabilizes each top-2 candidate using median coords from all N candidates.
- If all candidates fail: logs error, returns `[[], []]`.

### Consensus stabilization

For each region in a candidate, finds text+proximity matches across all N results:
- Text match: exact (whitespace-normalized) or fuzzy (SequenceMatcher >= 0.85).
- Centroid proximity: < 150 units (prevents matching repeated text at different positions).
- If >= 3 matches: takes median box_2d (per-coord) + median font_size_px.
- If < 3 matches: keeps original values.
- All box_2d values clamped to [0, 1000].

### Output PPTX impact

The pipeline produces **2 slides per input slide** (interleaved: [1a, 1b, 2a, 2b, ...]).
User manually picks the better version for each slide.

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

`requests`, `schemas` (Region), stdlib `base64`, `json`, `logging`, `statistics`, `difflib`, `concurrent.futures`.
