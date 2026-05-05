# config

Loads and validates runtime configuration from `config.toml` and environment variable overrides. Called once at startup.

## `Config` (dataclass)

| Field              | Type    | Default              | Source                              |
|--------------------|---------|----------------------|-------------------------------------|
| `gemini_api_key`   | `str`   | *required*           | `GEMINI_API_KEY` env or `[api_keys] gemini` |
| `replicate_token`  | `str`   | *required*           | `REPLICATE_API_TOKEN` env or `[api_keys] replicate` |
| `gemini_model`     | `str`   | `"gemini-3.1-flash-image-preview"`   | `[behavior] gemini_model`           |
| `replicate_model`  | `str`   | `"allenhooo/lama"`   | hard-coded                          |
| `max_concurrent`   | `int`   | `1`                  | `[behavior] max_concurrent`         |
| `mask_padding_px`  | `int`   | `12`                 | `[behavior] mask_padding_px`        |
| `mask_blur_radius` | `float` | `2.0`                | `[behavior] mask_blur_radius`       |
| `thinking_budget`  | `int`   | `1`                  | `[behavior] thinking_budget`        |
| `output_suffix`    | `str`   | `"_reconstructed"`   | `[output] suffix`                   |
| `font_px_to_pt`    | `float` | `0.75`               | hard-coded                          |
| `font_min_pt`      | `float` | `8.0`                | hard-coded                          |
| `font_max_pt`      | `float` | `60.0`               | hard-coded                          |

## Public functions

### `load_config() -> Config`

| Input  | Type | Description |
|--------|------|-------------|
| *(none)* | — | Reads `config.toml` from CWD or project root, plus env vars. |

| Output | Type     | Description |
|--------|----------|-------------|
| return | `Config` | Validated config with both API keys present. |

| Raises         | When                                           |
|----------------|------------------------------------------------|
| `RuntimeError` | Either API key missing from all sources.        |

## Constants

| Name                  | Type              | Value |
|-----------------------|-------------------|-------|
| `FONT_PX_TO_PT`       | `float`           | `0.75` |
| `FONT_MIN_PT`         | `float`           | `8.0` |
| `FONT_MAX_PT`         | `float`           | `60.0` |
| `VALID_FONT_FAMILIES` | `frozenset[str]`  | `{"Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"}` — Microsoft 365 cloud fonts (no embedding needed). Smaller list = better model classification accuracy. Do not add fonts without testing cloud font availability. |

## Dependencies

`tomllib` (stdlib 3.11+), `os`, `dataclasses`, `pathlib`.
