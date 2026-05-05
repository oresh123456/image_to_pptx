# Configuration Reference

## File location

Create `config.toml` in the project root (next to `pyproject.toml`). This file is gitignored.

## API keys

| Key | Where to get it |
|-----|-----------------|
| `gemini` | [Google AI Studio](https://aistudio.google.com/apikey) |
| `replicate` | [Replicate account](https://replicate.com/account/api-tokens) |

Environment variables `GEMINI_API_KEY` and `REPLICATE_API_TOKEN` override the file.

## Full template

Copy this into `config.toml`:

```toml
[api_keys]
gemini    = ""   # paste your Google AI Studio key
replicate = ""   # paste your Replicate token

[gemini]
model           = "gemini-3.1-flash-image-preview"
thinking_budget = 1      # thinking tokens (1 = minimal)
ocr_candidates  = 10    # parallel OCR calls per slide
ocr_top_k       = 2     # how many top candidates to select
timeout         = 300   # HTTP timeout in seconds

[replicate]
max_concurrent = 1      # raise to 5 once account has > $5 credit

[masking]
padding_px  = 12
blur_radius = 2

[output]
suffix = "_reconstructed"
```

## Fields

| Section | Field | Type | Default | Notes |
|---------|-------|------|---------|-------|
| `api_keys` | `gemini` | str | *required* | env `GEMINI_API_KEY` overrides |
| `api_keys` | `replicate` | str | *required* | env `REPLICATE_API_TOKEN` overrides |
| `gemini` | `model` | str | `"gemini-3.1-flash-image-preview"` | |
| `gemini` | `thinking_budget` | int | `1` | Gemini thinking tokens; `1` = minimal |
| `gemini` | `ocr_candidates` | int | `10` | Parallel OCR calls per slide |
| `gemini` | `ocr_top_k` | int | `2` | Top-k candidates selected from OCR |
| `gemini` | `timeout` | int | `300` | HTTP timeout for all Gemini calls |
| `replicate` | `max_concurrent` | int | `1` | Free-tier: keep at 1 |
| `masking` | `padding_px` | int | `12` | |
| `masking` | `blur_radius` | float | `2.0` | `0` = hard edges |
| `output` | `suffix` | str | `"_reconstructed"` | |

## Hard-coded values (not configurable)

| Name | Value | Purpose |
|------|-------|---------|
| `replicate_model` | `"allenhooo/lama"` | Inpainting model |
| `font_px_to_pt` | `0.75` | Font size conversion |
| `font_min_pt` / `font_max_pt` | `8.0` / `60.0` | Font size clamp |
| `VALID_FONT_FAMILIES` | Heebo, Rubik, Assistant, Frank Ruhl Libre, Heebo Black | MS365 cloud fonts |
