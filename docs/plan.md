# Plan: slide_text_replacer — Full Build

## Context

Three relevant artifacts exist in `temp_vision/`:
- `vision_test.py` — Claude API → OCR + overlay (no inpainting)
- `lama_test.py` — original masking/inpainting prototype
- **`SlideTextRemover/`** — **proven, production-deployed tool** for text deletion only.
  Contains `remove_text.py`, `setup.bat`, `run.bat`, `config.txt.example`, `README.txt`.

The `SlideTextRemover` is the text-erasure half of our pipeline and **works perfectly**.
We are extending it, NOT replacing it. The new tool adds:
- Gemini 2.5 Pro OCR → extracts text + bboxes + font_size estimates
- Gemini 2.5 Pro enrichment → adds font_family, font_weight, color per region
- python-pptx reconstruction → overlays editable text boxes on the clean background

The OCR/text-overlay backend uses **Gemini 2.5 Pro** (Google Vision was rejected for Hebrew
because it strips spaces between words). The proven masking/LaMa pipeline from
SlideTextRemover is kept as-is.

**Code reuse strategy:**
- `SlideTextRemover/remove_text.py` → `masking.py` + `inpainting.py` + `extraction.py`
- `SlideTextRemover/setup.bat` → `scripts/setup.bat`
- `SlideTextRemover/run.bat` → `scripts/run.bat`
- `SlideTextRemover/config.txt.example` → new `config.example.toml` adding `GEMINI_API_KEY`

---

## What we're building

A Python package that takes a NotebookLM-exported PPTX (slides = rasterized images) and
produces a new PPTX where:
1. Background images have all baked-in text **erased** via LaMa inpainting
2. **Native editable text boxes** are overlaid with matched font, size, color, RTL/Hebrew support

---

## Project structure to create

```
slide_text_replacer/
├── pyproject.toml
├── config.example.toml
├── README.md
├── .gitignore
├── src/
│   └── slide_text_replacer/
│       ├── __init__.py
│       ├── __main__.py          # CLI + file picker
│       ├── config.py            # load/validate config.toml + env vars
│       ├── schemas.py           # frozen dataclasses: Region, EnrichedRegion, SlideData
│       ├── pipeline.py          # ThreadPoolExecutor orchestration
│       ├── extraction.py        # PPTX → per-slide image bytes
│       ├── ocr.py               # Gemini 2.5 Pro OCR → list[Region]
│       ├── enrichment.py        # Gemini vision enrichment → adds font/color
│       ├── masking.py           # bboxes → binary PNG mask
│       ├── inpainting.py        # Replicate LaMa client
│       ├── reconstruction.py    # python-pptx assembly with text overlays
│       └── pptx_helpers.py      # XML helpers: RTL para, complex-script font
├── tests/
│   ├── __init__.py
│   ├── test_masking.py
│   ├── test_pptx_helpers.py
│   ├── test_schemas.py
│   └── fixtures/
│       ├── sample_ocr.json
│       └── sample_enriched.json
├── docs/
│   └── prompts.md               # versioned prompts for OCR + enrichment
└── scripts/
    ├── setup.bat
    └── run.bat
```

---

## Implementation steps

### Step 1 — Scaffold

- Create `slide_text_replacer/` directory with the full layout above
- `pyproject.toml`: deps = `python-pptx`, `Pillow`, `requests`, `tomllib` (stdlib on 3.11+)
- `config.example.toml` with all keys documented
- `.gitignore` excluding `config.toml`, `venv/`, `__pycache__/`

### Step 2 — `schemas.py`

Frozen dataclasses only, no logic:

```python
@dataclass(frozen=True)
class Region:
    text: str
    box_2d: tuple[int, int, int, int]   # ymin, xmin, ymax, xmax (0-1000)
    font_size_px: float

@dataclass(frozen=True)
class EnrichedRegion:
    text: str
    box_2d: tuple[int, int, int, int]
    font_size_px: float
    font_family: str
    font_weight: str          # "regular" | "bold"
    color: str                # "#RRGGBB"

@dataclass(frozen=True)
class SlideData:
    slide_number: int
    image_size: tuple[int, int]   # (width_px, height_px)
    regions: list[EnrichedRegion]
```

### Step 3 — `config.py`

- Read `config.toml` from project root (next to the package)
- Env vars override file values
- Validate: missing `gemini` or `replicate` key → `RuntimeError` with path hint
- Expose a single `load_config() -> Config` function

### Step 4 — `extraction.py`

Port the working extraction logic from `vision_test.py` and `lama_test.py`:
- `extract_slides(pptx_path: str) -> list[tuple[int, bytes, str]]`
  - Returns `(slide_idx, image_bytes, mime_type)` per slide
  - Picks largest picture shape per slide (same logic as both prototypes)
  - Skips slides with no picture

### Step 5 — `ocr.py`

Gemini 2.5 Pro REST API call (no SDK, just `requests`):
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent`
- Auth via `?key=<api_key>` query param
- Pass image as `inline_data` base64 part
- **Prompt** (in `docs/prompts.md` v1.0): asks for JSON array of `{text, box_2d, font_size_px}`
  - Explicit: preserve spaces between Hebrew words
  - Explicit: `box_2d` = `[ymin, xmin, ymax, xmax]` normalized 0-1000
  - Explicit: `font_size_px` = single-line estimate, not block height
- HTTP timeout: 300s
- 1 retry on any exception before skip-and-continue
- Returns `list[Region]`

### Step 6 — `enrichment.py`

Second Gemini 2.5 Pro call per slide:
- Input: same slide image + the OCR JSON from step 5
- **Prompt** (in `docs/prompts.md` v1.0): for each region, identify:
  - `font_family` — pick from: `["Heebo", "Rubik", "Assistant", "Frank Ruhl Libre", "Heebo Black"]`
  - `font_weight` — `"regular"` or `"bold"`
  - `color` — primary text color as `#RRGGBB`
  - Optionally refine `box_2d` and `font_size_px`
- Returns `list[EnrichedRegion]`
- On timeout: return regions with defaults (`font_family="Heebo"`, `font_weight="regular"`,
  `color="#000000"`) — log warning, don't abort slide

### Step 7 — `masking.py`

**Source: `SlideTextRemover/remove_text.py` → `build_mask()` function (proven)**

Adapt to accept `EnrichedRegion` list instead of Google Vision regions:
- `build_mask(image_bytes, regions: list[EnrichedRegion], image_size, padding_px=12, blur_radius=2.0) -> bytes`
- Denormalize `box_2d` from 0-1000 coords to pixels using `image_size`
- Keep ALL existing Pillow logic: `Image.new("L", ...)`, `ImageDraw.rectangle`, `GaussianBlur`
- Keep watermark filter: `_is_watermark(text)` (case-insensitive "notebooklm")
- Returns PNG bytes

### Step 8 — `inpainting.py`

**Source: `SlideTextRemover/remove_text.py` → `inpaint()`, `_resolve_version()` (proven, copy verbatim)**

Only changes:
- Accept `token` as a parameter instead of reading global `REPLICATE_API_TOKEN`
- Accept `max_retries` instead of global `MAX_RETRIES_ON_429`
- Everything else identical: polling loop, retry on 429, `retry_after` honor, jitter

### Step 9 — `pptx_helpers.py`

XML helpers (ported from `vision_test.py`, expanded):

```python
def set_run_font(run, font_name: str) -> None:
    """Sets <a:latin>, <a:cs>, <a:ea> and lang=he-IL on rPr."""

def set_paragraph_rtl(paragraph) -> None:
    """Sets rtl='1' on <a:pPr>."""
```

### Step 10 — `reconstruction.py`

`rebuild_slide(slide, clean_image_bytes: bytes, regions: list[EnrichedRegion], slide_data: SlideData) -> None`

Per region:
- Denormalize `box_2d` to EMU using slide dimensions and image pixel size
- `slide.shapes.add_textbox(left, top, w, h)`
- Set `word_wrap=True`, `auto_size=NONE`, `vertical_anchor=TOP`, margins=0
- Add paragraph: `alignment=RIGHT`, call `set_paragraph_rtl`
- Add run: set text, call `set_run_font`, set size (px × 0.75 → pt, clamped 8-60), set color, bold flag

Image replacement: same `_replace_picture_image` logic from `lama_test.py`.

### Step 11 — `pipeline.py`

`run_pipeline(input_pptx: str, output_pptx: str, config: Config) -> None`

```
1. extract_slides(input_pptx)
2. For each slide (parallel, ThreadPoolExecutor, max_workers=config.max_concurrent):
   a. ocr.run(image_bytes) → list[Region]
   b. SEQUENTIAL within future:
      - enrichment.run(image_bytes, regions) → list[EnrichedRegion]
      - masking.build_mask(image_bytes, regions) → mask_bytes
        → inpainting.inpaint(mask_bytes, ...) → clean_bytes
   c. reconstruction.rebuild_slide(slide, clean_bytes, enriched_regions)
3. prs.save(output_pptx)
```

Log at INFO: slide N started / done. DEBUG for API details.

### Step 12 — `__main__.py`

```
python -m slide_text_replacer [<input.pptx> [<output.pptx>]]
```
- **No args (default / GUI mode):**
  1. `filedialog.askopenfilename` → user picks the input `.pptx`
  2. `filedialog.asksaveasfilename` → user picks the output location and filename
     (default filename pre-filled as `<stem>_reconstructed.pptx`, filter `*.pptx`)
  3. If either dialog is cancelled, exit with a clear message
- 1 arg: input path given, still open `asksaveasfilename` for output
- 2 args: fully explicit, no dialog
- `logging.basicConfig(level=INFO, format="%(levelname)s %(message)s")`

### Step 13 — `scripts/setup.bat` and `scripts/run.bat`

**Source: `SlideTextRemover/setup.bat` + `run.bat` (copy, then modify)**

`setup.bat`: install `requests Pillow python-pptx` (no Gemini SDK — using REST API).
Copy `config.example.toml` → `config.toml` on first run.

`run.bat`: call `python -m slide_text_replacer` instead of `remove_text.py`.

`config.example.toml` keys:
```
GEMINI_API_KEY=         # NEW (replaces GOOGLE_VISION_API_KEY)
REPLICATE_API_TOKEN=    # same as SlideTextRemover
```

### Step 14 — Tests

`tests/test_masking.py`:
- `test_mask_covers_region`: single bbox → mask has white pixels at that location
- `test_mask_padding`: mask extends 12px beyond bbox
- `test_watermark_filtered`: "notebooklm" region → mask stays black

`tests/test_pptx_helpers.py`:
- `test_set_run_font_sets_cs_element`: XML has both `<a:latin>` and `<a:cs>` with correct typeface
- `test_set_paragraph_rtl_sets_attribute`: `<a:pPr rtl="1">` present

`tests/test_schemas.py`:
- Round-trip frozen dataclass → dict → dataclass
- `font_size_px` clamping boundaries

Fixtures: `fixtures/sample_ocr.json`, `fixtures/sample_enriched.json`

---

## API keys needed

| Key | Source | Where used |
|-----|--------|------------|
| `GEMINI_API_KEY` | Google AI Studio (aistudio.google.com) | OCR + enrichment — NEW |
| `REPLICATE_API_TOKEN` | replicate.com/account/api-tokens | LaMa inpainting — same as SlideTextRemover |

The Replicate token from `SlideTextRemover/config.txt` can be reused directly.
A new Gemini API key is required — replaces Google Vision. Anthropic key not used.

---

## Verification

1. `python -m pytest tests/` — all unit tests pass with no API calls
2. Create `config.toml` with real keys
3. `python -m slide_text_replacer Digital_Climate_Command.pptx test_output.pptx`
4. Open `test_output.pptx` in PowerPoint:
   - Images look clean (text erased)
   - Click any text — it's selectable/editable
   - Hebrew text renders right-to-left in correct font

---

## What NOT to do

- Do not add Google Vision API or Anthropic API — rejected per spec
- Do not use `async`/`await` — `ThreadPoolExecutor` + `requests` only
- Do not embed fonts — cloud fonts cover the target user base
- Do not add a wrapper class around the Gemini client — module-level functions only
- Do not change the font palette without testing cloud font availability
