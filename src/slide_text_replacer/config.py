"""
Module: config
==============
Loads and validates runtime configuration from config.toml plus environment
variable overrides.

Config file is searched in this order:
  1. config.toml in the current working directory
  2. config.toml two levels up from this file (the project root when installed
     via 'pip install -e .')

Environment variables override file values for the two required keys:
  GEMINI_API_KEY      overrides [api_keys] gemini
  REPLICATE_API_TOKEN overrides [api_keys] replicate

Core functions (used in the pipeline):
  - load_config() -> Config: locate config.toml, parse it, apply env overrides,
    validate that both API keys are present, and return a Config instance.

Helper functions (not called from outside this module):
  - _find_config_file() -> Path | None: walk the search path list.
  - _parse_raw(raw, env_gemini, env_replicate) -> Config: assemble Config from
    parsed TOML dict plus env override strings.

Pipeline role: called once at startup in __main__.py before the pipeline runs.
  The returned Config is passed explicitly to every stage that needs credentials
  or tuning parameters. No module reads from globals.

config.toml layout (see docs/config.md for the full template):

  [api_keys]
  gemini   = ""   # required
  replicate = ""  # required

  [gemini]
  model           = "gemini-3.1-flash-image-preview"
  thinking_budget = 1
  ocr_candidates  = 10
  ocr_top_k       = 2
  timeout         = 300

  [replicate]
  max_concurrent = 1

  [masking]
  padding_px  = 12
  blur_radius = 2

  [output]
  suffix = "_reconstructed"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib          # stdlib on Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        raise ImportError(
            "Python < 3.11 requires 'tomli': pip install tomli"
        )

# Font conversion constants shared with reconstruction.py.
FONT_PX_TO_PT: float = 0.75   # 96 DPI: 1 CSS pixel = 0.75 points
FONT_MIN_PT: float = 8.0
FONT_MAX_PT: float = 60.0

# Allowed font family names (locked palette — see notes.md §5).
VALID_FONT_FAMILIES: frozenset[str] = frozenset({
    "Heebo",
    "Rubik",
    "Assistant",
    "Frank Ruhl Libre",
    "Heebo Black",
})

# Search locations for config.toml, tried in order.
_CONFIG_SEARCH_PATHS: list[Path] = [
    Path.cwd() / "config.toml",
    Path(__file__).resolve().parents[2] / "config.toml",  # project root
]


@dataclass
class Config:
    """
    Validated runtime configuration for the pipeline.

    All fields except the two required API keys have safe defaults.
    Instances are assembled by load_config() and should be treated as
    read-only once created (no mutation after construction).

    Attributes:
        gemini_api_key:   Google AI Studio API key for OCR + enrichment.
        replicate_token:  Replicate API token for LaMa inpainting.
        gemini_model:     Gemini model name used in the API URL.
        gemini_timeout:   HTTP timeout for Gemini API calls in seconds.
        gemini_thinking_budget: Gemini thinking token budget (1 = minimal).
        gemini_ocr_candidates:  Number of parallel OCR calls per slide.
        gemini_ocr_top_k:       How many top candidates to select from OCR.
        replicate_model:  Replicate model identifier (user/model-name).
        max_concurrent:   Max slides processed in parallel by the thread pool.
        mask_padding_px:  Pixels of padding added around each bbox in the mask.
        mask_blur_radius: GaussianBlur radius on the mask (0 = hard edges).
        output_suffix:    Appended to the input stem to form the output filename.
        font_px_to_pt:    Pixel-to-point conversion factor (96 DPI convention).
        font_min_pt:      Minimum font size in points after conversion.
        font_max_pt:      Maximum font size in points after conversion.
    """

    gemini_api_key: str
    replicate_token: str
    gemini_model: str = "gemini-3.1-flash-image-preview"
    gemini_timeout: int = 300
    gemini_thinking_budget: int = 1
    gemini_ocr_candidates: int = 10
    gemini_ocr_top_k: int = 2
    replicate_model: str = "allenhooo/lama"
    max_concurrent: int = 1
    mask_padding_px: int = 12
    mask_blur_radius: float = 2.0
    output_suffix: str = "_reconstructed"
    font_px_to_pt: float = FONT_PX_TO_PT
    font_min_pt: float = FONT_MIN_PT
    font_max_pt: float = FONT_MAX_PT


def _find_config_file() -> Path | None:
    """
    Search known locations for config.toml and return the first one found.

    Args:
        None.

    Returns:
        Path to the config.toml file, or None if not found anywhere.
    """
    for path in _CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def _parse_raw(raw: dict, env_gemini: str, env_replicate: str) -> Config:
    """
    Assemble a Config from parsed TOML data and environment variable overrides.

    Environment variables take precedence over config file values. All fields
    not present in raw use dataclass defaults.

    Args:
        raw:           Dict returned by tomllib.load() on a config.toml file.
                       May be empty ({}) if no config file was found.
        env_gemini:    Value of GEMINI_API_KEY env var (empty string if unset).
        env_replicate: Value of REPLICATE_API_TOKEN env var (empty string if unset).

    Returns:
        Validated Config instance.

    Raises:
        RuntimeError: If either required API key is absent from both the config
                      file and environment variables, with a clear path hint.
    """
    api = raw.get("api_keys", {})
    output = raw.get("output", {})

    # Env var takes precedence over config file.
    gemini_key = env_gemini or api.get("gemini", "")
    replicate_token = env_replicate or api.get("replicate", "")

    if not gemini_key:
        hint = _find_config_file() or _CONFIG_SEARCH_PATHS[0]
        raise RuntimeError(
            f"GEMINI_API_KEY is not set.\n"
            f"  Option 1: add it to {hint} under [api_keys] gemini = \"...\"\n"
            f"  Option 2: set the GEMINI_API_KEY environment variable.\n"
            f"  Get a key at: https://aistudio.google.com/apikey"
        )

    if not replicate_token:
        hint = _find_config_file() or _CONFIG_SEARCH_PATHS[0]
        raise RuntimeError(
            f"REPLICATE_API_TOKEN is not set.\n"
            f"  Option 1: add it to {hint} under [api_keys] replicate = \"...\"\n"
            f"  Option 2: set the REPLICATE_API_TOKEN environment variable.\n"
            f"  Get a token at: https://replicate.com/account/api-tokens"
        )

    gemini = raw.get("gemini", {})
    replicate = raw.get("replicate", {})
    mask = raw.get("masking", {})

    return Config(
        gemini_api_key=gemini_key,
        replicate_token=replicate_token,
        gemini_model=gemini.get("model", "gemini-3.1-flash-image-preview"),
        gemini_timeout=int(gemini.get("timeout", 300)),
        gemini_thinking_budget=int(gemini.get("thinking_budget", 1)),
        gemini_ocr_candidates=int(gemini.get("ocr_candidates", 10)),
        gemini_ocr_top_k=int(gemini.get("ocr_top_k", 2)),
        replicate_model=replicate.get("model", "allenhooo/lama"),
        max_concurrent=int(replicate.get("max_concurrent", 1)),
        mask_padding_px=int(mask.get("padding_px", 12)),
        mask_blur_radius=float(mask.get("blur_radius", 2.0)),
        output_suffix=output.get("suffix", "_reconstructed"),
    )


def _config_path() -> Path:
    """Return the canonical config.toml path (project root)."""
    return Path(__file__).resolve().parents[2] / "config.toml"


def has_valid_config() -> bool:
    """Check if config.toml exists with non-empty API keys."""
    path = _find_config_file()
    if path is None:
        return False
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        api = raw.get("api_keys", {})
        return bool(api.get("gemini")) and bool(api.get("replicate"))
    except Exception:
        return False


def save_config(
    gemini_key: str,
    replicate_token: str,
    ocr_candidates: int,
    ocr_top_k: int,
) -> Path:
    """Write config.toml with API keys and user-exposed Gemini params.

    Caps ocr_candidates at 10, ocr_top_k at ocr_candidates.
    All other sections use hardcoded defaults.

    Returns:
        Path to the written config.toml.
    """
    ocr_candidates = min(max(ocr_candidates, 1), 10)
    ocr_top_k = min(max(ocr_top_k, 1), ocr_candidates)

    content = (
        "[api_keys]\n"
        f'gemini    = "{gemini_key}"\n'
        f'replicate = "{replicate_token}"\n'
        "\n"
        "[gemini]\n"
        'model           = "gemini-3.1-flash-image-preview"\n'
        "thinking_budget = 1\n"
        f"ocr_candidates  = {ocr_candidates}\n"
        f"ocr_top_k       = {ocr_top_k}\n"
        "timeout         = 300\n"
        "\n"
        "[replicate]\n"
        "max_concurrent = 1\n"
        "\n"
        "[masking]\n"
        "padding_px  = 12\n"
        "blur_radius = 2\n"
        "\n"
        "[output]\n"
        'suffix = "_reconstructed"\n'
    )

    dest = _config_path()
    dest.write_text(content, encoding="utf-8")
    return dest


def load_config() -> Config | None:
    """
    Load configuration from config.toml (if present) and environment variables.

    Returns None if no valid config is found (keys missing and no env vars),
    allowing the GUI to detect first-run and show key dialog.

    Returns:
        Validated Config, or None if keys are missing.
    """
    env_gemini = os.environ.get("GEMINI_API_KEY", "")
    env_replicate = os.environ.get("REPLICATE_API_TOKEN", "")

    raw: dict = {}
    config_path = _find_config_file()
    if config_path is not None:
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)

    try:
        return _parse_raw(raw, env_gemini, env_replicate)
    except (RuntimeError, IndexError):
        return None
