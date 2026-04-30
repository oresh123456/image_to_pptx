# instructions.md

> **Audience:** This document is for Claude Code (or any AI assistant or human
> developer) picking up the `slide_text_replacer` project mid-stream. Read it
> in full before writing any code. The decisions described here were arrived
> at through extensive testing, and reversing them without understanding why
> will cost time.

---

## 1. What this project does

The tool takes a PowerPoint (`.pptx`) where every slide is a single
flattened image — typically the output of Google's NotebookLM, which
exports decks as one rasterized PNG per slide with no editable text — and
produces a new `.pptx` where:

1. The original slide images are kept as backgrounds, but with all baked-in
   text **erased** (inpainted to match surrounding visuals).
2. **Native, editable PowerPoint text boxes** are overlaid in the same
   positions, with matched fonts, colors, and sizes, containing the same
   text as the original.

The result looks visually identical to the input, but every text element is
fully editable in PowerPoint.

### Concrete use case

The author works at a strategic consulting firm whose clients include
Israeli government ministries. Decks are drafted in NotebookLM (which
produces visually polished but image-only PPTX files) and then need to be
extensively edited before delivery. Manual rebuild of every slide is
prohibitive — hence this tool.

The content is in **Hebrew** with **embedded English fragments** (acronyms
like ConTech, BIM, POC, Living Lab; product names; technical terms). Any
solution must handle:

- Right-to-left (RTL) Hebrew rendering
- Mixed-script paragraphs (bidirectional text)
- Hebrew "complex-script" font substitution rules in PowerPoint

---

## 2. Tech stack

### Core dependencies

- **Python 3.10+** (uses modern type hints, `tomllib` from 3.11 if available)
- **`python-pptx`** for PPTX read/write. We sometimes drop into the
  underlying `lxml` for XML manipulation when python-pptx's high-level API
  doesn't expose what we need (specifically: complex-script font setting
  and RTL paragraph properties).
- **`Pillow`** for image manipulation (mask generation, color sampling).
- **`requests`** for all HTTP — no async, no httpx. Keep it simple.

### External services

| Service | Purpose | Why this one |
|---|---|---|
| **Google Gemini API** (2.5 Pro) | OCR pass + vision-enrichment pass | Best Hebrew text quality at reasonable cost. Returns structured JSON with normalized `box_2d` coords. |
| **Replicate** (`allenhooo/lama`) | Text removal via LaMa inpainting | Open-source SOTA inpainting; ~$0.0005/slide; reconstructs grid-paper backgrounds cleanly. |
| **PowerPoint cloud fonts** | Render fonts at file-open time | Empirically verified: PowerPoint downloads Heebo/Rubik/Assistant/Frank Ruhl Libre on demand for users signed into Microsoft 365. **No font embedding needed.** See §6.4. |

### Services explicitly NOT used (and why)

- **Google Vision API** — fast and cheap, but Hebrew text quality is
  unusable: it strips spaces between Hebrew words ("מהלךאסטרטגיאקלים"
  instead of "מהלך אסטרטגי אקלים"). Tested and rejected.
- **Mistral OCR** — does not return per-text bounding boxes; only image/figure
  bboxes. Architectural mismatch with our pipeline.
- **Anthropic Claude** — comparable text quality to Gemini but more expensive
  and slower for our task. Kept as a backup option (the prompt structure is
  nearly identical).
- **Google Slides API** — could replace large parts of our pipeline by using
  Slides as the rendering backend. Rejected because (a) it adds OAuth/service
  account complexity for end users, (b) requires Drive API and image hosting,
  (c) introduces network latency on every operation. Our approach keeps the
  tool self-contained.
- **PyInstaller / single-exe distribution** — adds antivirus false positives
  in corporate environments. The current `setup.bat` + `run.bat` approach is
  more transparent and trustworthy for the target users.

---

## 3. The pipeline (high level)

```
Input PPTX (each slide = 1 image)
        │
        ▼
┌───────────────┐
│  Extraction   │   pull image bytes per slide via python-pptx
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   OCR pass    │   Gemini 2.5 Pro returns text + bboxes + estimated font_size
│   (per slide) │   This is the "rough hint" for downstream stages.
└───────┬───────┘
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
┌────────────────┐           ┌────────────────┐
│ Vision         │           │ Mask building  │   white rects over each bbox,
│ enrichment     │           │ (local, free)  │   12px padding, slight blur
│ (per slide)    │           └───────┬────────┘
│ refines bbox,  │                   │
│ adds font,     │                   ▼
│ color, size    │           ┌────────────────┐
└───────┬────────┘           │ LaMa inpaint   │   Replicate API; ~2s/slide
        │                    │ (per slide)    │
        │                    └───────┬────────┘
        │                            │
        └────────────┬───────────────┘
                     ▼
            ┌───────────────────┐
            │   Reconstruction  │   python-pptx assembly:
            │                   │   clean images + editable text overlays
            └─────────┬─────────┘
                      ▼
                 Output PPTX
```

**Parallelism model:** OCR is the shared prerequisite. Once OCR finishes for
a slide, vision enrichment and mask-building-then-inpainting fork and run
in parallel for that slide. Reconstruction waits for both branches to
complete for all slides, then runs once at the end.

Use `concurrent.futures.ThreadPoolExecutor`. Async would be cleaner in
theory but harder to debug, and our network calls are the bottleneck
either way.

---

## 4. The data shape (JSON)

The single source of truth between stages is a per-slide JSON object. Each
stage **adds** fields, never overwrites. Final shape after enrichment:

```json
{
  "slide_number": 18,
  "image_size": [1707, 960],
  "regions": [
    {
      "text": "ציר חדשנות וטכנולוגיה (ClimateTech) | תמחור ערך",
      "box_2d": [77, 95, 124, 1291],
      "font_family": "Heebo",
      "font_weight": "bold",
      "font_size_px": 38,
      "color": "#1a3a8a"
    }
  ]
}
```

### Field semantics

- **`text`** — extracted text content. Preserves Hebrew, English, numbers,
  punctuation, and **inter-word spaces**. The OCR prompt explicitly
  requests space preservation; without this, Gemini sometimes joins Hebrew
  words.
- **`box_2d`** — `[ymin, xmin, ymax, xmax]` normalized to 0-1000. This is
  Gemini's native format. Document `image_size` lets us denormalize when
  needed.
- **`font_family`** — picked by the enrichment model from a fixed list
  (see §6.3). Per-region; a single slide can mix fonts.
- **`font_weight`** — `"regular"` or `"bold"`. We don't carry italic as a
  separate field; if italic is needed in future, font_family becomes
  `"Rubik Italic"` etc.
- **`font_size_px`** — single integer estimate. For multi-line text, this
  is the per-line size, NOT the bbox height. The enrichment prompt is
  explicit about this; it's the most common bug.
- **`color`** — primary text color in this region as `#RRGGBB`. The
  enrichment prompt asks the model to pick ONE color even if there are
  multiple — we don't try to handle multi-colored runs within a region.

### Stages add fields in this order:

1. **OCR pass** writes: `text`, `box_2d`, `font_size_px`
2. **Enrichment pass** overwrites: `box_2d`, `font_size_px`; adds
   `font_family`, `font_weight`, `color`
3. **Reconstruction** reads all of the above, makes no further additions

### Why per-region font, not deck-level

Initial design considered a deck-level palette (one primary font, one
secondary font). Rejected after looking at real NotebookLM output: a
single slide often uses 3+ visually distinct fonts (impact title, body,
labels, callouts). Per-region matching preserves the visual hierarchy.

---

## 5. The font palette (locked)

The vision-enrichment model picks from exactly these five options:

- **Heebo** — modern geometric sans, default for body and most titles
- **Rubik** — slightly rounded, friendlier, used for labels and callouts
- **Assistant** — neutral humanist sans, alternative body font
- **Frank Ruhl Libre** — serif, for editorial or formal slides
- **Heebo Black** — heavy display weight, for hero titles

All five are **Google Fonts** under SIL Open Font License. All five are in
**Microsoft 365's Cloud Font catalog**, which means PowerPoint downloads
them on demand at file-open time when a user is signed into Microsoft 365.

**Do not add fonts to this list without testing.** The list is small on
purpose: a smaller answer space gives the model better classification
accuracy than an open-ended "what font is this."

**Do not add fonts that aren't Microsoft 365 cloud fonts.** Verified
working: Heebo, Rubik, Assistant, Frank Ruhl Libre, Heebo Black. If you
add a font outside this set, the file will appear correct on the
developer's machine and fail silently on recipients' machines.

---

## 6. Critical implementation details

### 6.1 Hebrew rendering in PowerPoint requires `<a:cs>`

When setting a font on a text run, you must set BOTH `<a:latin>` and
`<a:cs>` (complex-script) typefaces. python-pptx's high-level API only
exposes Latin. If you set only Latin, Hebrew text falls back to whatever
the user's default complex-script font is (often David, sometimes Arial),
regardless of what you intended.

The helper looks like:

```python
from pptx.oxml.ns import qn
from lxml import etree

def set_run_font(run, font_name: str) -> None:
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:cs", "a:ea"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
    latin = etree.SubElement(rPr, qn("a:latin"))
    latin.set("typeface", font_name)
    cs = etree.SubElement(rPr, qn("a:cs"))
    cs.set("typeface", font_name)
    rPr.set("lang", "he-IL")
```

Test this in a unit test — XML changes in python-pptx would silently break
Hebrew rendering otherwise.

### 6.2 RTL paragraph attribute

Each paragraph containing Hebrew needs `rtl="1"` set on its `<a:pPr>`
element. python-pptx doesn't expose this either:

```python
def set_paragraph_rtl(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("rtl", "1")
```

Combined with `paragraph.alignment = PP_ALIGN.RIGHT`, this makes Hebrew
display in correct logical order with appropriate alignment.

### 6.3 Font sizing: trust the model, not the bbox

Earlier versions of the pipeline computed font size from `bbox_height_px *
0.7`. This breaks on multi-line text — the bbox is the height of the
*entire block*, but the font size we want is the height of *one line*.

The enrichment model is asked to estimate `font_size_px` directly. Its
estimates are noticeably better than geometric inference, especially for
multi-line text and small labels.

Conversion: `pt = px * 0.75` (96 DPI convention; 1 CSS pixel = 0.75
points). Clamp to `[8, 60]`.

### 6.4 Why we don't embed fonts

Empirically tested: a PPTX that *names* Heebo/Rubik/Frank Ruhl Libre but
does NOT embed them renders correctly in PowerPoint when the user is
signed into Microsoft 365. PowerPoint's Cloud Font feature downloads them
on demand.

This was not theoretical — confirmed by:
1. Google Slides exporting decks with these fonts embeds them as
   `.fntdata` files (as seen in `ppt/fonts/`).
2. A test PPTX generated by `python-pptx` *without* embedding still
   renders correctly on machines that don't have these fonts locally
   installed, because cloud fonts kick in.

For this tool's user base (Israeli consulting + ministry recipients, all
on Microsoft 365), this is sufficient.

If you ever need to support recipients on standalone Office (2019, 2021)
or offline use, you'll need to add font embedding. The mechanism is
documented in OOXML spec §17.8.2 and involves:
1. Adding `.fntdata` font files to `/ppt/fonts/` in the PPTX archive
2. Registering them in `/ppt/presentation.xml` under `<p:embeddedFontLst>`
3. Wrapping each font file's first 32 bytes with the standard XOR
   obfuscation key derived from a GUID

This is non-trivial. Don't add it speculatively.

### 6.5 LaMa mask generation

For text erasure to look clean:

- **Pad each bbox by 12px** in every direction. LaMa handles oversized
  masks well; under-masking leaves visible text fragments.
- **Apply Gaussian blur with radius ~2** to the mask. Soft edges blend
  better than hard rectangles.
- **Filter out the NotebookLM watermark** by text content (case-insensitive
  match on "notebooklm"). It always lives at fixed coordinates near the
  bottom-right.

### 6.6 Replicate rate limits

Accounts with under $5 credit are throttled to **6 predictions/minute,
burst 1**. The script must:

1. Honor `retry_after` from 429 responses (Replicate provides it).
2. Default `MAX_CONCURRENT = 1` for safety. Raise to 5+ once the user has
   paid credit.
3. Retry up to 6 times on 429 before giving up on a slide.

Don't make this configurable in the user-facing config — it should "just
work" regardless of the user's credit level.

### 6.7 Gemini occasional timeouts

Gemini 2.5 Pro is a "thinking" model. On geometrically complex slides
(multi-column layouts with leader lines, dense scales with callouts),
internal reasoning can exceed 180 seconds, presenting as an HTTP read
timeout. Mitigations:

1. Set HTTP timeout to **300 seconds**, not 180.
2. Implement retry-on-failure (one retry is usually enough).
3. If a slide consistently times out, skip it gracefully — the rest of
   the deck should still complete.

Do NOT use `thinkingConfig.thinkingBudget = 0` to disable reasoning. Empirically,
Gemini's thinking *does* improve quality on these slides, even though it
makes timing unpredictable.

### 6.8 Microsoft Store Python alias trap

On modern Windows, `python.exe` and `py.exe` are App Execution Aliases
that redirect to the Microsoft Store rather than calling installed
Python. The setup script must:

1. Try `py -3 -c "import sys; print(sys.executable)"` first
2. Fall back to `where python` but **filter out paths under `WindowsApps\`**
3. Fall back to probing standard install locations directly

See `setup.bat` for the working incantation.

### 6.9 Venvs are not portable

A venv created on machine A will not work on machine B because it
hardcodes the path to A's Python interpreter. The build/install pipeline
must:

1. Never ship a venv inside the distribution package.
2. `setup.bat` must validate any existing venv and recreate it if it's
   broken (typical when a folder was copied between machines).

---

## 7. Project structure (the layout to build to)

```
slide_text_replacer/
├── pyproject.toml          # build metadata, deps, entry points
├── README.md               # user-facing setup + usage
├── LICENSE                 # MIT or Apache-2.0
├── .gitignore
├── config.example.toml     # template for user's config.toml
├── src/
│   └── slide_text_replacer/
│       ├── __init__.py
│       ├── __main__.py     # CLI entry: python -m slide_text_replacer
│       ├── config.py       # load + validate config.toml / env vars
│       ├── pipeline.py     # orchestration + parallelism
│       ├── extraction.py   # PPTX -> per-slide image bytes
│       ├── ocr.py          # Gemini OCR call
│       ├── enrichment.py   # Gemini vision enrichment call
│       ├── masking.py      # bboxes -> binary mask
│       ├── inpainting.py   # Replicate LaMa client
│       ├── reconstruction.py  # python-pptx assembly
│       ├── pptx_helpers.py # XML helpers (RTL, complex-script font)
│       └── schemas.py      # frozen dataclasses for inter-stage JSON
├── tests/
│   ├── __init__.py
│   ├── test_masking.py     # deterministic, no API
│   ├── test_pptx_helpers.py
│   ├── test_schemas.py
│   ├── test_extraction.py
│   └── fixtures/
│       ├── sample_slide.png
│       ├── sample_ocr.json
│       └── sample_enriched.json
├── docs/
│   ├── architecture.md     # diagrams + data flow
│   ├── api_setup.md        # how to obtain API credentials
│   ├── prompts.md          # exact prompts (versioned)
│   └── decisions.md        # ADRs for major choices (font palette etc.)
└── scripts/
    ├── setup.bat           # Windows one-time install
    └── run.bat             # Windows launcher
```

### Style guidelines

- **Module-level functions, not classes** for behavior. The author
  prefers functional Python.
- **`@dataclass(frozen=True)`** for inter-stage data shapes (Region,
  EnrichedRegion, SlideData). Treated as data, not behavior, so the
  "no OOP" intent is respected.
- **Google-style docstrings** on every public function: Args, Returns,
  Raises sections.
- **Type hints everywhere.** Modern syntax (`list[Region]`, not
  `List[Region]`).
- **No `print` for user-facing progress in library code.** Use the
  `logging` module. The CLI entry point sets up a friendly handler.
- **No hidden state.** Every function takes its dependencies explicitly;
  no module-level globals other than `logger` and constants.

### Testing approach

- **Unit-test the deterministic stages** with no API calls: masking, XML
  helpers, schema serialization, color sampling, extraction.
- **Mock HTTP in tests for API-dependent code** using `unittest.mock`
  patching `requests.post`. Never hit live APIs from tests.
- **Provide one end-to-end smoke test** that uses cached fixtures (pre-saved
  OCR JSONs, pre-saved Replicate responses) to exercise the full pipeline
  without spending API credit.
- **Don't aim for 100% coverage.** Aim for coverage of the gnarly bits:
  XML manipulation, mask geometry, retry logic on 429s.

---

## 8. Configuration

Use a `config.toml` next to the package, with structure:

```toml
[api_keys]
gemini = ""           # Google AI Studio or Cloud Console
replicate = ""        # https://replicate.com/account/api-tokens

[behavior]
gemini_model = "gemini-2.5-pro"
max_concurrent = 1    # raise to 5 once Replicate has $5+ credit
mask_padding_px = 12
mask_blur_radius = 2

[output]
suffix = "_reconstructed"   # output file: <input><suffix>.pptx
```

Environment variables override config file. Missing keys must produce a
clear error message pointing to the config file path.

---

## 9. Process for working on this codebase

### Order of work for an agent picking this up cold

If you are starting from this `instructions.md` with no prior context:

1. **Read `docs/architecture.md`** for visual overview of the pipeline.
2. **Read `docs/prompts.md`** to understand exactly what we ask the
   models. The prompts are versioned because they're load-bearing.
3. **Run the test suite** to verify your environment is set up.
4. **Run the smoke test** — it processes one fixture slide end-to-end with
   mocked APIs. This proves the pipeline still assembles correctly.
5. **Only then make changes.**

### When making changes

- **Stages are independent.** You can iterate on `enrichment.py` without
  touching `inpainting.py`. The JSON contract between them is the boundary.
- **Don't break the JSON shape** without bumping a schema version. Any
  cached intermediate JSONs from previous runs would silently break.
- **Don't change the prompts** without explicit user instruction. They've
  been tuned through extensive testing. If you want to experiment, do it
  in a feature branch and document why.
- **Don't add new external services** without justification. Each new API
  is an additional credential the user has to manage and an additional
  failure mode in production. The user has explicitly rejected several
  services we considered.

### What the user values (from extended pairing sessions)

- **Honest tradeoff analysis** — when there are options, lay them out with
  costs and pitfalls. Do not pretend a tool is the obvious choice when
  it's a judgment call.
- **Concrete cost numbers** for any API-using change.
- **Pushback when the user is wrong** — don't reflexively agree. The user
  explicitly values being told when an idea has issues.
- **Preserve simple UX for non-technical users** — the team using this
  tool double-clicks `run.bat`. Architecture changes that complicate that
  experience should be flagged loudly.
- **No premature abstraction.** This is a focused tool, not a framework.

### Anti-patterns to avoid

- "Let me make this configurable" — most things should not be
  configurable. Hard-code defaults that work; expose only what users
  actually need to change.
- "I'll add a wrapper for that" — every wrapper class is one more layer
  to read through to understand what's happening.
- Reaching for async/await — `requests` + `ThreadPoolExecutor` is enough.
- Adding logging that isn't actionable — log at INFO level for stage
  starts/completes; DEBUG for everything else.

---

## 10. Open work / known issues

- The pipeline does not currently retry vision-enrichment on timeout. If
  Gemini times out on enrichment, that slide's text is reconstructed with
  default font/color. Acceptable for now; flagged as a future improvement.
- Color sampling from pixels (as fallback when the model returns invalid
  hex) is not implemented. Currently, invalid colors fall back to
  `#000000`. Adding pixel sampling is the cleanest improvement.
- Font weight is binary (regular/bold). Some slides have semi-bold or
  light weights that get squashed to one of these. Acceptable for now.
- No support for italic text. Add a `font_style: "italic"` field if a real
  use case appears.
- LaMa occasionally leaves faint ghosting on slides with very dark text on
  light backgrounds. Padding the mask further (16px instead of 12px)
  helps; not yet tuned.

---

## 11. Where to ask for clarification

If something in this document contradicts code you find in the repo, the
**code is wrong** unless you can prove this document is wrong. Ask the
human user before changing either.

If something in this document is unclear, ask. Don't guess. The cost of a
clarifying question is far less than the cost of a refactor that
misunderstood the design.