"""
Live health-check tests for the Replicate API.

These tests make real HTTP calls — run them explicitly with:
    python -m pytest tests/test_replicate_api.py -m api

They are skipped automatically when:
  - No REPLICATE_API_TOKEN is configured (env var or config.toml)
  - pytest runs without the ``-m api`` marker selector
"""

from __future__ import annotations

import os

import pytest
import requests

from slide_text_replacer.inpainting import resolve_version

# ── Skip conditions ──────────────────────────────────────────────────────────

def _get_replicate_token() -> str | None:
    """Return the Replicate token from env or config.toml, or None."""
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if token:
        return token
    try:
        from slide_text_replacer.config import load_config
        cfg = load_config()
        return cfg.replicate_token
    except Exception:
        return None


_token = _get_replicate_token()
_MODEL = "allenhooo/lama"

pytestmark = [
    pytest.mark.api,
    pytest.mark.skipif(_token is None, reason="REPLICATE_API_TOKEN not configured"),
]


# ── Tests ────────────────────────────────────────────────────────────────────

def test_replicate_auth_valid():
    """Replicate token is accepted — GET /account returns 200."""
    r = requests.get(
        "https://api.replicate.com/v1/account",
        headers={"Authorization": f"Bearer {_token}"},
        timeout=15,
    )
    assert r.status_code == 200, f"Auth failed: {r.status_code} {r.text[:200]}"


def test_replicate_model_resolvable():
    """resolve_version returns a 64-char hex version ID for LaMa."""
    version_id = resolve_version(_MODEL, _token)
    assert isinstance(version_id, str)
    assert len(version_id) == 64, f"Expected 64-char hash, got {len(version_id)}"
