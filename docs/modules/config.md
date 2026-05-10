# config

Loads and validates runtime configuration from `config.toml` and environment variable overrides. Called once at startup. Also provides helpers for first-run detection and config persistence (GUI key dialog).

## `Config` (dataclass)

| Field              | Type    | Default              | Source                              |
|--------------------|---------|----------------------|-------------------------------------|
| `gemini_api_key`   | `str`   | *required*           | `GEMINI_API_KEY` env or `[api_keys] gemini` |
| `replicate_token`  | `str`   | *required*           | `REPLICATE_API_TOKEN` env or `[api_keys] replicate` |
| `gemini_model`     | `str`   | `"gemini-3.1-flash-image-preview"`   | `[gemini] model`           |
| `gemini_timeout`   | `int`   | `300`                | `[gemini] timeout`                  |
| `gemini_thinking_budget` | `int` | `1`              | `[gemini] thinking_budget`          |
| `gemini_ocr_candidates`  | `int` | `10`             | `[gemini] ocr_candidates`           |
| `gemini_ocr_top_k`       | `int` | `2`              | `[gemini] ocr_top_k`               |
| `replicate_model`  | `str`   | `"allenhooo/lama"`   | hard-coded                          |
| `max_concurrent`   | `int`   | `1`                  | `[replicate] max_concurrent`        |
| `mask_padding_px`  | `int`   | `12`                 | `[masking] padding_px`              |
| `mask_blur_radius` | `float` | `2.0`                | `[masking] blur_radius`             |
| `output_suffix`    | `str`   | `"_reconstructed"`   | `[output] suffix`                   |
| `font_px_to_pt`    | `float` | `0.75`               | hard-coded                          |
| `font_min_pt`      | `float` | `8.0`                | hard-coded                          |
| `font_max_pt`      | `float` | `60.0`               | hard-coded                          |

## Public functions

### `load_config() -> Config | None`

| Input  | Type | Description |
|--------|------|-------------|
| *(none)* | — | Reads `config.toml` from search path, plus env vars. |

| Output | Type           | Description |
|--------|----------------|-------------|
| return | `Config | None` | Validated config, or `None` if keys missing (allows GUI first-run detection). |

### `has_valid_config() -> bool`

| Input  | Type | Description |
|--------|------|-------------|
| *(none)* | — | Checks if `config.toml` exists with non-empty API keys. |

| Output | Type   | Description |
|--------|--------|-------------|
| return | `bool` | `True` if config file found and both API keys are non-empty. |

### `save_config(gemini_key, replicate_token, ocr_candidates, ocr_top_k) -> Path`

| Input             | Type  | Description |
|-------------------|-------|-------------|
| `gemini_key`      | `str` | Gemini API key to write. |
| `replicate_token` | `str` | Replicate token to write. |
| `ocr_candidates`  | `int` | Capped to 1–10. |
| `ocr_top_k`       | `int` | Capped to 1–`ocr_candidates`. |

| Output | Type   | Description |
|--------|--------|-------------|
| return | `Path` | Path to the written `config.toml`. |

Writes a complete `config.toml` with the given keys and Gemini params. All other sections use hardcoded defaults.

## Internal functions

### `_find_config_file() -> Path | None`

Searches known locations for `config.toml`. When running inside a PyInstaller bundle (`sys.frozen` is `True`), the exe directory is checked first. Uses `sys` imported inside the function body.

### `_config_path() -> Path`

Returns the canonical `config.toml` path: exe directory when frozen, project root otherwise. Uses `sys` imported inside the function body.

### `_parse_raw(raw, env_gemini, env_replicate) -> Config`

Assembles a `Config` from parsed TOML dict + env overrides. Raises `RuntimeError` if either API key is missing.

## Constants

| Name                  | Type              | Value |
|-----------------------|-------------------|-------|
| `FONT_PX_TO_PT`       | `float`           | `0.75` |
| `FONT_MIN_PT`         | `float`           | `8.0` |
| `FONT_MAX_PT`         | `float`           | `60.0` |
| `VALID_FONT_FAMILIES` | `frozenset[str]`  | `{"Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"}` — Microsoft 365 cloud fonts (no embedding needed). Smaller list = better model classification accuracy. Do not add fonts without testing cloud font availability. |

## Dependencies

`tomllib` (stdlib 3.11+), `os`, `dataclasses`, `pathlib`, `sys` (imported inside function bodies for frozen-path detection).
