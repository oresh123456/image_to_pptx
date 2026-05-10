# Slide Text Replacer

Converts image-only PowerPoint files (e.g. from NotebookLM) into editable PPTX files. Extracts text via OCR (Gemini), erases baked-in text via inpainting (LaMa), then overlays native PowerPoint text boxes with matched fonts, colors, and sizes. Supports Hebrew/English bidirectional content.

## Quick start (developer)

```bash
# One-time setup: creates venv, installs deps
scripts\setup.bat

# Run (GUI mode)
scripts\run.bat

# Run headless
python -m slide_text_replacer input.pptx output.pptx
```

Requires `config.toml` with API keys (Gemini + Replicate). On first GUI launch, a key-entry dialog appears automatically.

## How the installer works

This section explains the full build chain for someone unfamiliar with PyInstaller or Inno Setup.

### PyInstaller — bundling Python into a folder

[PyInstaller](https://pyinstaller.org/) takes a Python application and packages it into a standalone directory that can run without a Python installation on the target machine.

**What "onedir" means.** PyInstaller has two modes: `onefile` (single `.exe`, slow startup) and `onedir` (a folder with the `.exe` + all dependencies). This project uses **onedir** — it produces a `slide_text_replacer/` folder containing:

- `slide_text_replacer.exe` — the bootloader that starts the bundled Python interpreter
- `python3XX.dll` — the embedded CPython runtime
- All `.pyd`/`.dll` files for every dependency (Pillow, lxml, requests, etc.)
- A `_internal/` directory with bytecode-compiled `.pyc` files

**The `.spec` file is the recipe.** Instead of passing flags on the CLI, PyInstaller reads `installer/slide_text_replacer.spec` — a Python script that defines:

- **Entry point**: `src/slide_text_replacer/__main__.py`
- **Hidden imports**: modules that PyInstaller can't auto-detect from static analysis (e.g. `tomllib`, `lxml.etree`, `json_repair`). Without these, the bundled app would crash at runtime with `ModuleNotFoundError`.
- **Excludes**: test packages stripped from the bundle to reduce size.
- **console=False**: the `.exe` launches as a GUI app (no terminal window).

**Key spec details:**

```python
# Entry point
Analysis([os.path.join(ROOT, "src", "slide_text_replacer", "__main__.py")])

# Modules PyInstaller misses during static analysis
hiddenimports=["tomllib", "lxml", "lxml.etree", "json_repair"]

# Don't bundle test code
excludes=["pytest", "test", "tests", "unittest"]
```

### Inno Setup — wrapping the folder into a Windows installer

[Inno Setup](https://jrsoftware.org/isinfo.php) takes the PyInstaller output folder and wraps it into a single `Setup_SlideTextReplacer_vX.Y.Z.exe` installer that:

1. **Copies files** — the entire `dist/slide_text_replacer/` folder goes to `C:\Program Files\SlideTextReplacer\`
2. **Creates shortcuts** — desktop shortcut + Start Menu group
3. **Registers a context menu** — adds "Convert with Slide Text Replacer" to the right-click menu for `.pptx` files (uses a shell verb so it doesn't replace PowerPoint as the default handler)
4. **Supports uninstall** — registry entries and log directory are cleaned up on uninstall

The `installer/setup.iss` script controls all of this. Key sections:

| Section      | What it does                                          |
|-------------|-------------------------------------------------------|
| `[Files]`    | Copies the entire PyInstaller onedir output recursively |
| `[Icons]`    | Desktop + Start Menu shortcuts                        |
| `[Registry]` | `.pptx` right-click context menu entry                |
| `[UninstallDelete]` | Removes the `logs/` dir created at runtime     |

### The build chain

```
build.bat → PyInstaller → Inno Setup → final installer .exe
```

`installer/build.bat` automates the full sequence:

1. Reads the version from `pyproject.toml`
2. Checks for `GEMINI_API_KEY` and `REPLICATE_API_TOKEN` env vars (warns if missing, uses placeholders)
3. Generates `config.toml` from `installer/config.toml.template` with API keys substituted in
4. Runs PyInstaller with the `.spec` file → produces `installer/dist/slide_text_replacer/`
5. Copies the generated `config.toml` into the dist folder
6. Runs Inno Setup (`iscc`) → produces `installer/output/Setup_SlideTextReplacer_vX.Y.Z.exe`

### `sys.frozen` detection — dev vs. installed paths

When Python runs normally, `__file__` points to the source `.py` file on disk. But inside a PyInstaller bundle, there is no source tree — `__file__` points somewhere inside the bundle's temp directory and the usual `Path(__file__).parents[2]` trick to find the project root breaks.

PyInstaller sets `sys.frozen = True` when running inside a bundle. The code checks this to compute paths differently:

| Location | Dev mode (`sys.frozen` = False) | Installed mode (`sys.frozen` = True) |
|---|---|---|
| `config.py:_find_config_file()` | Searches CWD then project root | Searches **exe directory first** (where `config.toml` is installed alongside the `.exe`) |
| `config.py:_config_path()` | `Path(__file__).parents[2] / "config.toml"` | `Path(sys.executable).parent / "config.toml"` |
| `__main__.py:_setup_logging()` | `Path(__file__).parents[2] / "logs"` | `Path(sys.executable).parent / "logs"` |

All `sys.frozen` checks live **inside function bodies** (not at module level) — this keeps the module importable in tests without side effects.

### Config template

`installer/config.toml.template` contains the full config with placeholder API keys (`__GEMINI_API_KEY__`, `__REPLICATE_API_TOKEN__`). During the build, `build.bat` substitutes these with actual env var values (or leaves placeholders if unset — the GUI will prompt on first launch).

## Building the installer

### Prerequisites

- Python 3.11+ with project deps installed (`scripts\setup.bat`)
- [PyInstaller](https://pyinstaller.org/) — `pip install pyinstaller`
- [Inno Setup 6+](https://jrsoftware.org/isdl.php) — install and add `iscc.exe` to PATH
- Microsoft Visual C++ Build Tools (for compiling native extensions)

### Build steps

```bash
# Set API keys (optional — GUI prompts on first launch if missing)
set GEMINI_API_KEY=your-key-here
set REPLICATE_API_TOKEN=your-token-here

# Run the build
installer\build.bat
```

Output: `installer\output\Setup_SlideTextReplacer_vX.Y.Z.exe`

## Project layout

```
slide_text_replacer/               (git root)
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── icon.ico
├── docs/
│   ├── notes.md                   # comprehensive technical manual
│   ├── config.md                  # config template + field reference
│   ├── plan.md                    # project plan
│   ├── prompts.md                 # versioned LLM prompts
│   └── modules/                   # per-module I/O reference (12 files + README)
├── src/slide_text_replacer/       # main package
│   ├── __main__.py                # GUI entry point + tkinter dialogs
│   ├── config.py                  # config.toml loading + env var overrides
│   ├── schemas.py                 # frozen dataclasses: Region, EnrichedRegion, SlideData
│   ├── pipeline.py                # orchestration with ThreadPoolExecutor
│   ├── extraction.py              # PPTX → per-slide image bytes
│   ├── retry.py                   # shared retry utility
│   ├── ocr.py                     # Gemini OCR → Region list
│   ├── enrichment.py              # Gemini vision enrichment → EnrichedRegion list
│   ├── masking.py                 # bboxes → binary mask PNG
│   ├── inpainting.py              # Replicate LaMa API client
│   ├── reconstruction.py          # clean images + text overlays → output PPTX
│   └── pptx_helpers.py            # XML helpers for Hebrew font + RTL
├── installer/
│   ├── build.bat                  # one-click build: PyInstaller → Inno Setup
│   ├── slide_text_replacer.spec   # PyInstaller recipe (onedir, hidden imports)
│   ├── setup.iss                  # Inno Setup script (shortcuts, context menu, uninstall)
│   ├── config.toml.template       # config with API key placeholders
│   └── assets/
│       └── banner.bmp             # installer wizard banner image
├── tests/                         # unit + integration tests
├── scripts/
│   ├── setup.bat                  # Windows one-time setup
│   └── run.bat                    # Windows launcher
└── docs/
    └── modules/                   # per-module I/O contracts
```

## Pipeline

```
Extraction → OCR (Gemini) → [Enrichment (Gemini) || Masking → Inpainting (LaMa)] → Reconstruction
```

## Tests

```bash
# Unit tests
python -m pytest tests/

# Integration tests (requires config.toml + test fixtures)
python -m pytest tests/ -m integration -v
```
