"""
Tests for config.py — TOML loading, env var overrides, and validation.

Verifies I/O contracts documented in docs/modules/config.md.
All tests are local — no API calls. Env vars via monkeypatch.
"""

import pytest

from slide_text_replacer.config import (
    Config,
    FONT_PX_TO_PT,
    FONT_MIN_PT,
    FONT_MAX_PT,
    VALID_FONT_FAMILIES,
    _parse_raw,
    has_valid_config,
    load_config,
    save_config,
)


# ── Constants: output values ─────────────────────────────────────────────────

def test_font_constants_values():
    """Constants → FONT_PX_TO_PT=0.75, MIN=8, MAX=60."""
    assert FONT_PX_TO_PT == 0.75
    assert FONT_MIN_PT == 8.0
    assert FONT_MAX_PT == 60.0


def test_valid_font_families_exactly_five():
    """VALID_FONT_FAMILIES → frozenset of exactly the 5 locked palette fonts."""
    assert isinstance(VALID_FONT_FAMILIES, frozenset)
    assert len(VALID_FONT_FAMILIES) == 5
    expected = {"Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"}
    assert VALID_FONT_FAMILIES == expected


# ── Config: default values ───────────────────────────────────────────────────

def test_config_defaults():
    """Input: only required keys → Output: Config with documented defaults."""
    cfg = Config(gemini_api_key="k", replicate_token="t")
    assert cfg.gemini_model == "gemini-3.1-flash-image-preview"
    assert cfg.replicate_model == "allenhooo/lama"
    assert cfg.max_concurrent == 1
    assert cfg.mask_padding_px == 12
    assert cfg.mask_blur_radius == 2.0
    assert cfg.output_suffix == "_reconstructed"
    assert cfg.font_px_to_pt == 0.75
    assert cfg.font_min_pt == 8.0
    assert cfg.font_max_pt == 60.0


# ── _parse_raw(): output contract ────────────────────────────────────────────

def test_parse_raw_full_toml_dict():
    """Input: complete raw dict → Output: Config with all fields from dict."""
    raw = {
        "api_keys": {"gemini": "g-key", "replicate": "r-key"},
        "gemini": {
            "model": "gemini-2.0-flash",
            "thinking_budget": 5,
            "ocr_candidates": 8,
            "ocr_top_k": 3,
            "timeout": 120,
        },
        "replicate": {"max_concurrent": 4},
        "masking": {"padding_px": 16, "blur_radius": 3.0},
        "output": {"suffix": "_out"},
    }
    cfg = _parse_raw(raw, env_gemini="", env_replicate="")
    assert cfg.gemini_api_key == "g-key"
    assert cfg.replicate_token == "r-key"
    assert cfg.gemini_model == "gemini-2.0-flash"
    assert cfg.gemini_thinking_budget == 5
    assert cfg.gemini_ocr_candidates == 8
    assert cfg.gemini_ocr_top_k == 3
    assert cfg.gemini_timeout == 120
    assert cfg.max_concurrent == 4
    assert cfg.mask_padding_px == 16
    assert cfg.mask_blur_radius == 3.0
    assert cfg.output_suffix == "_out"


def test_parse_raw_env_overrides_file():
    """Input: env vars + file values → Output: env vars take precedence."""
    raw = {"api_keys": {"gemini": "file-gemini", "replicate": "file-replicate"}}
    cfg = _parse_raw(raw, env_gemini="env-gemini", env_replicate="env-replicate")
    assert cfg.gemini_api_key == "env-gemini"
    assert cfg.replicate_token == "env-replicate"


def test_parse_raw_sections_parsed():
    """Input: gemini/replicate/masking sections → Output: Config fields set."""
    raw = {
        "api_keys": {"gemini": "g", "replicate": "r"},
        "gemini": {"ocr_candidates": 5},
        "replicate": {"max_concurrent": 3},
        "masking": {"padding_px": 20, "blur_radius": 5.0},
    }
    cfg = _parse_raw(raw, env_gemini="", env_replicate="")
    assert cfg.gemini_ocr_candidates == 5
    assert cfg.mask_padding_px == 20
    assert cfg.mask_blur_radius == 5.0
    assert cfg.max_concurrent == 3


# ── _parse_raw(): error handling ─────────────────────────────────────────────

def test_parse_raw_missing_gemini_raises():
    """Input: no gemini key anywhere → raises RuntimeError mentioning GEMINI_API_KEY."""
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        _parse_raw({}, env_gemini="", env_replicate="has-value")


def test_parse_raw_missing_replicate_raises():
    """Input: no replicate key anywhere → raises RuntimeError mentioning REPLICATE_API_TOKEN."""
    with pytest.raises(RuntimeError, match="REPLICATE_API_TOKEN"):
        _parse_raw({}, env_gemini="has-value", env_replicate="")


def test_parse_raw_empty_string_treated_as_missing():
    """Input: empty string in config file → treated as missing, raises RuntimeError."""
    raw = {"api_keys": {"gemini": "", "replicate": ""}}
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        _parse_raw(raw, env_gemini="", env_replicate="")


# ── load_config(): output contract ───────────────────────────────────────────

def test_load_config_from_env_only(monkeypatch):
    """Input: env vars only (no config.toml) → Output: valid Config."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-g")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "env-r")
    monkeypatch.setattr(
        "slide_text_replacer.config._CONFIG_SEARCH_PATHS", []
    )
    cfg = load_config()
    assert cfg.gemini_api_key == "env-g"
    assert cfg.replicate_token == "env-r"


def test_load_config_returns_none_when_keys_missing(monkeypatch):
    """Input: no keys anywhere → Output: None (not RuntimeError)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    monkeypatch.setattr("slide_text_replacer.config._CONFIG_SEARCH_PATHS", [])
    assert load_config() is None


# ── save_config(): output contract ───────────────────────────────────────────

def test_save_config_creates_file(tmp_path, monkeypatch):
    """save_config writes a valid config.toml at the project root."""
    monkeypatch.setattr(
        "slide_text_replacer.config._config_path",
        lambda: tmp_path / "config.toml",
    )
    path = save_config("gkey", "rtoken", 5, 3)
    assert path.exists()
    import tomllib
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    assert raw["api_keys"]["gemini"] == "gkey"
    assert raw["api_keys"]["replicate"] == "rtoken"
    assert raw["gemini"]["ocr_candidates"] == 5
    assert raw["gemini"]["ocr_top_k"] == 3


def test_save_config_caps_candidates(tmp_path, monkeypatch):
    """save_config caps ocr_candidates at 10 and ocr_top_k at candidates."""
    monkeypatch.setattr(
        "slide_text_replacer.config._config_path",
        lambda: tmp_path / "config.toml",
    )
    save_config("g", "r", 99, 50)
    import tomllib
    with open(tmp_path / "config.toml", "rb") as f:
        raw = tomllib.load(f)
    assert raw["gemini"]["ocr_candidates"] == 10
    assert raw["gemini"]["ocr_top_k"] == 10


# ── has_valid_config(): output contract ──────────────────────────────────────

def test_has_valid_config_true(tmp_path, monkeypatch):
    """has_valid_config returns True when keys are present."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[api_keys]\ngemini = "k"\nreplicate = "t"\n')
    monkeypatch.setattr(
        "slide_text_replacer.config._CONFIG_SEARCH_PATHS", [cfg_file]
    )
    assert has_valid_config() is True


def test_has_valid_config_false_no_file(monkeypatch):
    """has_valid_config returns False when no config file exists."""
    monkeypatch.setattr("slide_text_replacer.config._CONFIG_SEARCH_PATHS", [])
    assert has_valid_config() is False
