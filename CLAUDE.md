# slide_text_replacer

Converts image-only PowerPoint files (from NotebookLM) into editable PPTX files. Extracts text via OCR, erases baked-in text via inpainting, then overlays native PowerPoint text boxes with matched fonts/colors/sizes. Content is primarily Hebrew with embedded English fragments — full RTL and bidirectional support is required.

Authoritative technical reference: `docs/notes.md`. If this file and notes.md conflict, **notes.md is correct** — ask the user before changing either.

## Working with limited scope

Each module has a self-contained I/O reference in `docs/modules/<module>.md`. When working on a specific module, read **only** its doc and the docs of modules it directly interfaces with — not the entire codebase. The module docs specify exact input types, output types, error behavior, and guarantees.

Index: `docs/modules/README.md`.

---

## Tech stack

- **Python 3.11+** (uses `tomllib` from stdlib)

- **python-pptx** — PPTX read/write; drops to `lxml` for Hebrew XML manipulation

- **Pillow** — mask generation, image processing

- **requests** — all HTTP calls (no async, no httpx)

- **Google Gemini 2.5 Pro** — OCR pass + vision enrichment pass (REST API with query-param key)

- **Replicate LaMa** (`allenhooo/lama`) — text erasure via inpainting (~$0.0005/slide)

- **Microsoft 365 cloud fonts** — Heebo, Rubik, Assistant, Frank Ruhl Libre, Heebo Black (no embedding needed)

## Project layout

```
image_to_pptx/                 (git root)
├── CLAUDE.md
├── pyproject.toml
├── config.example.toml        # template — copy to config.toml, add API keys
├── src/slide_text_replacer/   # main package (13 modules, ~2200 LOC)
│   ├── __main__.py            # CLI entry point + tkinter file dialogs
│   ├── config.py              # config.toml loading + env var overrides
│   ├── schemas.py             # frozen dataclasses: Region, EnrichedRegion, SlideData
│   ├── pipeline.py            # orchestration with ThreadPoolExecutor
│   ├── extraction.py          # PPTX → per-slide image bytes
│   ├── retry.py               # shared retry utility (retry_call, RetryExhausted, RateLimitedError)
│   ├── ocr.py                 # Gemini OCR call → Region list
│   ├── enrichment.py          # Gemini vision enrichment → EnrichedRegion list
│   ├── masking.py             # bboxes → binary mask PNG
│   ├── inpainting.py          # Replicate LaMa API client
│   ├── reconstruction.py      # clean images + text overlays → output PPTX
│   └── pptx_helpers.py        # XML helpers for <a:cs> Hebrew font + RTL
├── tests/                     # 113 unit tests (no live API calls)
│   ├── conftest.py            # shared fixtures
│   ├── test_config.py         # 10 tests
│   ├── test_retry.py           # 10 tests
│   ├── test_ocr.py            # 10 tests
│   ├── test_enrichment.py     # 12 tests
│   ├── test_extraction.py     # 8 tests
│   ├── test_inpainting.py     # 10 tests
│   ├── test_reconstruction.py # 10 tests
│   ├── test_pipeline.py       # 8 tests
│   ├── test_main.py           # 7 tests
│   ├── test_masking.py        # 9 tests
│   ├── test_pptx_helpers.py   # 8 tests
│   ├── test_schemas.py        # 9 tests
│   └── fixtures/              # sample_ocr.json, sample_enriched.json
├── docs/
│   ├── notes.md               # comprehensive technical manual (read first)
│   ├── plan.md                # project plan
│   ├── prompts.md             # versioned LLM prompts with rationale
│   └── modules/               # per-module I/O reference (12 files + README)
└── scripts/
    ├── setup.bat              # Windows one-time setup (finds Python, creates venv)
    └── run.bat                # Windows launcher
```

## Commands

```bash
# Setup (Windows, one-time)
scripts/setup.bat

# Run (Windows)
scripts/run.bat                                          # GUI file dialogs
python -m slide_text_replacer input.pptx output.pptx     # headless

# Tests
python -m pytest tests/
```

## Pipeline

```
Extraction → OCR (Gemini) → [Enrichment (Gemini) || Masking → Inpainting (LaMa)] → Reconstruction
```

- **ThreadPoolExecutor** — one future per slide; enrichment and masking/inpainting fork in parallel after OCR
- **Reconstruction runs on main thread** (python-pptx is not thread-safe)
- Default `max_concurrent=1` (safe for free Replicate accounts)

## Data contracts (schemas.py)

**Region** (OCR output): `text`, `box_2d` ([ymin,xmin,ymax,xmax] 0-1000), `font_size_px`

**EnrichedRegion** (enrichment output): all Region fields + `font_family`, `font_weight` ("regular"/"bold"), `color` ("#RRGGBB")

Stages add fields in order: OCR writes `text`/`box_2d`/`font_size_px` → Enrichment refines and adds `font_family`/`font_weight`/`color` → Reconstruction reads all.

## Code conventions

- **Module-level functions, not classes** (except frozen dataclasses for data shapes)
- **Type hints everywhere** — modern syntax (`list[Region]`, not `List[Region]`)
- **Google-style docstrings** on every public function
- **`logging` module only** — no `print` in library code
- **No module-level globals** except `logger` and constants
- **No hidden state** — every function takes dependencies explicitly

## Critical constraints

- **Font palette is locked** — 5 Microsoft 365 cloud fonts only. See `docs/modules/config.md`.
- **Prompts are load-bearing** — OCR and enrichment prompts are versioned in `docs/prompts.md`. Do not change without explicit instruction and testing on 3+ slides.
- **Hebrew rendering requires lxml** — python-pptx only exposes Latin fonts. See `docs/modules/pptx_helpers.md`.
- **Gemini timeout is 300s** — not 180s. See `docs/modules/ocr.md`.
- **Replicate free-tier** — ~6 predictions/min, `max_concurrent=1` by default. See `docs/modules/inpainting.md`.

## Configuration

`config.toml` next to the package (gitignored). Env vars override: `GEMINI_API_KEY`, `REPLICATE_API_TOKEN`. See `docs/modules/config.md` for all fields and defaults.

## Anti-patterns — do NOT do these

- **Don't add new external services** — each one is a credential + failure mode. Google Vision, Mistral OCR, Anthropic Claude were all explicitly rejected.
- **Don't use async/await** — stick with `requests` + `ThreadPoolExecutor`.
- **Don't embed fonts** — cloud fonts are sufficient for the target user base (Microsoft 365).
- **Don't make things configurable** that don't need to be. Hard-code sensible defaults.
- **Don't add wrapper classes** — module-level functions, not OOP abstractions.
- **Don't change prompts** without explicit user instruction and testing.
- **Don't break the JSON shape** between stages without updating `schemas.py`.

## Known issues

- Invalid colors fall back to #000000 (pixel sampling not yet implemented)
- Font weight is binary (regular/bold) — semi-bold/light get squashed
- No italic support
- LaMa occasionally leaves faint ghosting on dark-on-light text (16px padding helps)

## TODO — remaining work

### Must do before production use
- **Test prompts on real slides** — OCR and enrichment prompts are v1.0 and have not been validated on actual NotebookLM Hebrew slides. Run on 3+ representative slides with mixed Hebrew/English content. Verify: Hebrew word spacing preserved, font family classification accuracy, color detection accuracy, bounding box precision.

### Nice-to-have improvements
- **Add dev dependencies to pyproject.toml** — add `[project.optional-dependencies] dev = ["pytest>=7.4"]` so developers know what to install for testing
- **Pixel-sampling color fallback** — when enrichment returns an invalid color, sample the actual pixel color from the image instead of defaulting to #000000
- **Config path robustness** — `config.py:76-79` uses `Path(__file__).resolve().parents[2]` which works but is fragile if package structure changes
- **win32com-based extraction** — use PowerPoint's `Slide.Export()` via `win32com.client` to rasterize any slide, making the tool work with arbitrary PPTX files (not just NotebookLM image-only exports). Windows+PowerPoint only. Details in `docs/modules/extraction.md`.
