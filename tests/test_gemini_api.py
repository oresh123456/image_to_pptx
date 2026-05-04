"""
Live health-check tests for the Gemini API.

These tests make real HTTP calls — run them explicitly with:
    python -m pytest tests/test_gemini_api.py -m api

They are skipped automatically when:
  - No GEMINI_API_KEY is configured (env var or config.toml)
  - pytest runs without the ``-m api`` marker selector
"""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from slide_text_replacer.ocr import _call_gemini

# ── Skip conditions ──────────────────────────────────────────────────────────

def _get_gemini_key() -> str | None:
    """Return the Gemini key from env or config.toml, or None."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    # Try loading from config.toml (same search as config.py)
    try:
        from slide_text_replacer.config import load_config
        cfg = load_config()
        return cfg.gemini_api_key
    except Exception:
        return None


_api_key = _get_gemini_key()

pytestmark = [
    pytest.mark.api,
    pytest.mark.skipif(_api_key is None, reason="GEMINI_API_KEY not configured"),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tiny_png() -> bytes:
    """Generate a 4×4 solid-red PNG — the smallest useful image."""
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tests ────────────────────────────────────────────────────────────────────

def test_gemini_health_returns_text():
    """Gemini responds with a non-empty text part to a trivial prompt."""
    result = _call_gemini(
        api_key=_api_key,
        model="gemini-2.5-pro",
        image_bytes=_tiny_png(),
        mime_type="image/png",
        prompt="Reply with the single word: OK",
        timeout=60,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_gemini_health_json_capable():
    """Gemini returns parseable JSON when asked."""
    result = _call_gemini(
        api_key=_api_key,
        model="gemini-2.5-pro",
        image_bytes=_tiny_png(),
        mime_type="image/png",
        prompt='Respond with ONLY this exact JSON: [{"status": "ok"}]',
        timeout=60,
    )
    import json
    import re
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.strip())
    data = json.loads(cleaned)
    # Gemini may return [{"status":"ok"}] or {"status":"ok"} — both fine
    item = data[0] if isinstance(data, list) else data
    assert item["status"] == "ok"
