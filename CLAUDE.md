- in all interactions and comit messages, be extremely concise and sacrafice grammer for the sake of concision

# slide_text_replacer

Converts image-only PowerPoint files (from NotebookLM) into editable PPTX files. Extracts text via OCR, erases baked-in text via inpainting, then overlays native PowerPoint text boxes with matched fonts/colors/sizes. Content is primarily Hebrew with embedded English fragments — full RTL and bidirectional support is required.

Authoritative technical reference: `docs/notes.md`. If this file and notes.md conflict, **notes.md is correct** — ask the user before changing either.

## Working with limited scope

This project uses an **I/O-contract workflow**: each module's public interface (inputs, outputs, errors, guarantees) is documented in `docs/modules/<module>.md`. You work from these contracts instead of reading the full codebase, which keeps context small and focused.

**Do not read any file without direct instructions** — this saves context tokens.

When the user instructs you to read a module for context, read the module source and its doc. When working on a module, read **only** its doc and the docs of modules it directly interfaces with. Index: `docs/modules/README.md`.

### Changing a module's I/O contract

**Do not change inputs or outputs without explicit user approval.** When you detect that a task would require an I/O change:

1. **Stop and warn the user** — state exactly what would change (added/removed/renamed fields, new error types, changed return shape) and why the current task requires it.
2. **Ask permission to search the full codebase** (`src/` and `tests/`) for all affected call sites — both functions that feed input to the changed module and functions that consume its output.
3. After searching, **return a report** listing:
   - Every affected function/location
   - Which pipeline stages are impacted
   - A rough **difficulty score** (low / medium / high) and **complexity score** (isolated change / multi-module ripple / pipeline-wide) for the overall change
4. **Wait for user go-ahead** before making any changes. Then update code and the module doc (`docs/modules/<module>.md`).

### Reading beyond your current module

**Never read files outside your assigned module scope without permission.** You are encouraged to request permission whenever it would help — include the file/module name and a one-line reason. Example: *"May I read `docs/modules/enrichment.md`? The function I'm editing receives `EnrichedRegion` as input and I need to verify the field names."*

---

## Tech stack

- **Python 3.11+** (uses `tomllib` from stdlib)

- **python-pptx** — PPTX read/write; drops to `lxml` for Hebrew XML manipulation

- **Pillow** — mask generation, image processing

- **requests** — all HTTP calls (no async, no httpx)

- **Google Gemini 2.5 Flash** — OCR pass + vision enrichment pass (REST API with query-param key, thinking disabled by default)

- **Replicate LaMa** (`allenhooo/lama`) — text erasure via inpainting (~$0.0005/slide)

- **Microsoft 365 cloud fonts** — Heebo, Rubik, Assistant, Frank Ruhl Libre, Heebo Black (no embedding needed)

## Project layout

```
image_to_pptx/                 (git root)
├── CLAUDE.md
├── README.md                  # full explanation of distribution system
├── pyproject.toml
├── icon.ico                   # app icon (exe + installer)
├── docs/config.md             # config template + field reference
├── src/slide_text_replacer/   # main package (13 modules, ~2200 LOC)
│   ├── __main__.py            # GUI entry point + tkinter file dialogs
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
├── installer/
│   ├── build.bat              # one-click build: PyInstaller → Inno Setup
│   ├── slide_text_replacer.spec  # PyInstaller recipe (onedir, hidden imports)
│   ├── setup.iss              # Inno Setup script (shortcuts, context menu, uninstall)
│   ├── config.toml.template   # config with API key placeholders for build
│   └── assets/
│       └── banner.bmp         # installer wizard banner image
├── tests/                     # 113 unit + 8 integration tests
│   ├── conftest.py            # shared fixtures (unit + integration)
│   ├── README.md              # how to run all test types
│   ├── test_config.py         # 10 unit tests
│   ├── test_retry.py           # 10 unit tests
│   ├── test_ocr.py            # 10 unit tests
│   ├── test_enrichment.py     # 12 unit tests
│   ├── test_extraction.py     # 8 unit tests
│   ├── test_inpainting.py     # 10 unit tests
│   ├── test_reconstruction.py # 10 unit tests
│   ├── test_pipeline.py       # 8 unit tests
│   ├── test_main.py           # 7 unit tests
│   ├── test_masking.py        # 9 unit tests
│   ├── test_pptx_helpers.py   # 8 unit tests
│   ├── test_schemas.py        # 9 unit tests
│   ├── test_integration_removal.py   # 3 integration tests (masking + inpainting)
│   ├── test_integration_overlay.py   # 3 integration tests (text recreation)
│   ├── test_integration_full.py      # 2 integration tests (full pipeline)
│   ├── fixtures/              # sample_ocr.json, sample_enriched.json, test_input.pptx (gitignored)
│   └── output/                # integration test outputs (gitignored)
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

# Tests (unit only, default)
python -m pytest tests/

# Integration tests (requires config.toml + tests/fixtures/test_input.pptx)
python -m pytest tests/ -m integration -v
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

`config.toml` next to the package (gitignored). Env vars override: `GEMINI_API_KEY`, `REPLICATE_API_TOKEN`. See `docs/config.md` for template and all fields.

### Current config state

All tunable parameters are centralized in `config.toml` (under `[gemini]`, `[replicate]`, `[masking]`, `[output]` sections). No hardcoded magic numbers in module code. `sys.frozen` guards live inside function bodies only (`_find_config_file()`, `_config_path()`, `_setup_logging()`) — not at module level.

## Installer / distribution

Full explanation in `README.md`. Build chain: `installer/build.bat` → PyInstaller (onedir) → Inno Setup → Windows installer `.exe`. Key files: `installer/slide_text_replacer.spec` (PyInstaller recipe), `installer/setup.iss` (Inno Setup script), `installer/config.toml.template` (API key placeholders).

`sys.frozen` guards ensure paths resolve correctly in both dev and installed modes. All guards are inside function bodies (not module-level) so modules stay importable in tests.

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
