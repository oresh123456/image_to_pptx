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
gemini   = ""   # paste your Google AI Studio key
replicate = ""  # paste your Replicate token

[behavior]
gemini_model    = "gemini-2.5-flash"
max_concurrent  = 1    # raise to 5 once your Replicate account has > $5 credit
mask_padding_px = 12   # pixels of padding around each text bbox in the inpaint mask
mask_blur_radius = 2   # Gaussian blur radius applied to the mask (0 = no blur)
thinking_budget = 1    # Gemini thinking token budget (1 = minimal thinking)

[output]
suffix = "_reconstructed"  # output filename: <input_stem><suffix>.pptx
```

## Fields

| Section | Field | Type | Default | Notes |
|---------|-------|------|---------|-------|
| `api_keys` | `gemini` | str | *required* | env `GEMINI_API_KEY` overrides |
| `api_keys` | `replicate` | str | *required* | env `REPLICATE_API_TOKEN` overrides |
| `behavior` | `gemini_model` | str | `"gemini-2.5-flash"` | |
| `behavior` | `max_concurrent` | int | `1` | Replicate free-tier: keep at 1 |
| `behavior` | `mask_padding_px` | int | `12` | |
| `behavior` | `mask_blur_radius` | float | `2.0` | `0` = hard edges |
| `behavior` | `thinking_budget` | int | `1` | Gemini thinking tokens; `1` = minimal thinking |
| `output` | `suffix` | str | `"_reconstructed"` | |

## Hard-coded values (not configurable)

| Name | Value | Purpose |
|------|-------|---------|
| `replicate_model` | `"allenhooo/lama"` | Inpainting model |
| `font_px_to_pt` | `0.75` | Font size conversion |
| `font_min_pt` / `font_max_pt` | `8.0` / `60.0` | Font size clamp |
| `VALID_FONT_FAMILIES` | Heebo, Rubik, Assistant, Frank Ruhl Libre, Heebo Black | MS365 cloud fonts |
