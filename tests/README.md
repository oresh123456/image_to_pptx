# Tests

## Prerequisites

```bash
scripts\setup.bat          # creates venv, installs deps
pip install pytest         # if not already installed
```

## Unit tests (default)

No API keys needed. All external calls are mocked.

```bash
python -m pytest tests/
```

## API health checks

Verifies API keys work. Requires `config.toml` with valid keys.

```bash
python -m pytest tests/ -m api -v
```

## Integration tests

End-to-end tests against real APIs with real slide data.

### Setup

1. Place a real NotebookLM PPTX at `tests/fixtures/test_input.pptx` (gitignored)
2. Ensure `config.toml` has valid API keys (see `docs/config.md`)

Tests skip automatically if either is missing.

### Run

```bash
# All integration tests
python -m pytest tests/ -m integration -v

# Text removal only (masking + inpainting)
python -m pytest tests/test_integration_removal.py -m integration -v

# Overlay only (cheapest — no Replicate calls)
python -m pytest tests/test_integration_overlay.py -m integration -v

# Full pipeline
python -m pytest tests/test_integration_full.py -m integration -v
```

### Output

Results saved to `tests/output/` (gitignored):

| File | What to check |
|------|---------------|
| `slide_N_mask.png` | White areas cover all text regions |
| `slide_N_clean.png` | Text erased cleanly, no ghosting |
| `overlay_only.pptx` | Text boxes align with baked-in text underneath |
| `full_result.pptx` | Clean background + correctly positioned text overlays |

**Note:** Output PPTX has **2x slides** (interleaved A/B versions per input slide).
OCR fires 10 parallel calls, picks top-2 by region count, consensus-stabilizes
coordinates using median from all 10 results, then processes both through the
full pipeline. User picks the better version for each slide.

### What each test file validates

| File | Tests | API calls |
|------|-------|-----------|
| `test_integration_removal.py` | Mask has white pixels, inpainted image valid + differs from original | Gemini + Replicate |
| `test_integration_overlay.py` | Text boxes added, text matches OCR, font properties set | Gemini only |
| `test_integration_full.py` | Full pipeline output valid, all slides have text boxes | Gemini + Replicate |

## Every test file

```bash
# unit
python -m pytest tests/test_config.py -v
python -m pytest tests/test_retry.py -v
python -m pytest tests/test_ocr.py -v
python -m pytest tests/test_enrichment.py -v
python -m pytest tests/test_extraction.py -v
python -m pytest tests/test_inpainting.py -v
python -m pytest tests/test_reconstruction.py -v
python -m pytest tests/test_pipeline.py -v
python -m pytest tests/test_main.py -v
python -m pytest tests/test_masking.py -v
python -m pytest tests/test_pptx_helpers.py -v
python -m pytest tests/test_schemas.py -v

# api health checks
python -m pytest tests/test_gemini_api.py -m api -v
python -m pytest tests/test_replicate_api.py -m api -v

# integration
python -m pytest tests/test_integration_removal.py -m integration -v
python -m pytest tests/test_integration_overlay.py -m integration -v
python -m pytest tests/test_integration_full.py -m integration -v
```
