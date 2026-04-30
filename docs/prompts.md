# Prompts — slide_text_replacer

Prompts are versioned because they are **load-bearing**: they were tuned through
extensive testing on real NotebookLM Hebrew slides. Do not change them without
understanding the tradeoffs and updating the version table below.

The exact strings used in code live in `ocr.py` (constant `OCR_PROMPT`) and
`enrichment.py` (constant `_ENRICHMENT_PROMPT_TEMPLATE`). This file is the
human-readable reference and rationale document.

---

## Version history

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-04-27 | Initial prompts for OCR and enrichment passes |

---

## OCR Prompt — v1.0

Used in: `src/slide_text_replacer/ocr.py` → `OCR_PROMPT`

```
Detect every distinct text element in this slide image.

For each text element output a JSON object with these exact keys:
  "text"        : exact text content. IMPORTANT: preserve the space between every
                  Hebrew word — do not concatenate words. Preserve English, numbers,
                  symbols, and punctuation exactly as shown.
  "box_2d"      : [ymin, xmin, ymax, xmax] — four integers each in 0-1000,
                  where 0,0 is the image top-left and 1000,1000 is bottom-right.
  "font_size_px": integer — estimated rendered height of ONE line of text in pixels.
                  If the text wraps across multiple lines, estimate a single line's
                  height — NOT the full block height.

A "text element" is one visually-grouped region (a slide title, one bullet, one
label, a caption, a slide number). Do NOT merge visually-separate regions. Do NOT
split a visually-grouped region.

Respond with ONLY a valid JSON array. No markdown fences, no prose.
```

### Design notes

- **Hebrew space preservation**: Without the explicit instruction, Gemini 2.5 Pro
  occasionally concatenates adjacent Hebrew words (e.g., `"מהלךאסטרטגי"` instead
  of `"מהלך אסטרטגי"`). The `IMPORTANT:` prefix and the explicit contrast
  ("do not concatenate") reliably prevent this.

- **`box_2d` format**: Gemini's native coordinate format is `[ymin, xmin, ymax, xmax]`
  normalized to 0-1000. Using this directly avoids needing to know the internal
  server-side image rescale factor — unlike pixel coordinates, which change depending
  on how Gemini resizes the image for inference.

- **`font_size_px` = single line**: The most common failure mode is the model
  returning the full block height for multi-line text. The contrast ("ONE line …
  NOT the full block") was added after empirical testing showed it reduces this
  error significantly.

- **`"text element"` definition**: Explicitly listing examples (title, bullet, label,
  caption, slide number) reduces over-segmentation (splitting one heading into word-
  level regions) and under-segmentation (merging a title with body text).

---

## Enrichment Prompt — v1.0

Used in: `src/slide_text_replacer/enrichment.py` → `_ENRICHMENT_PROMPT_TEMPLATE`

The `{regions_json}` placeholder is replaced at call time with the serialised
OCR output for that slide.

```
You are given a slide image and a JSON array of text regions already detected in it.

For EACH region in the input array, identify the following visual properties and return
a JSON object with these exact keys:
  "text"        : copy the original text exactly, unchanged.
  "box_2d"      : [ymin, xmin, ymax, xmax] in 0-1000 integers. Refine if you can
                  improve accuracy; otherwise copy the original value.
  "font_size_px": single-line pixel height. Refine if you can improve it; otherwise copy.
  "font_family" : MUST be exactly one of: "Heebo", "Rubik", "Assistant",
                  "Frank Ruhl Libre", "Heebo Black". Pick the closest visual match.
  "font_weight" : exactly "regular" or "bold".
  "color"       : the primary text color in this region as "#RRGGBB" hex. Pick ONE
                  color even if multiple colors appear within the region.

Return a JSON array with one object per input region, IN THE SAME ORDER as the input.
The output array must have exactly the same number of items as the input.

Input regions:
{regions_json}

Respond with ONLY a valid JSON array. No markdown fences, no prose.
```

### Design notes

- **"copy the original text exactly, unchanged"**: Without this, the model sometimes
  corrects perceived OCR errors or paraphrases text. We want the exact OCR output
  preserved — any correction should happen in the OCR pass, not here.

- **Font palette constraint**: The list of exactly five fonts is critical. A larger
  or open-ended font list degrades classification accuracy significantly. The five
  fonts were chosen because they cover the full visual range of NotebookLM output
  AND are all available as Microsoft 365 cloud fonts (see `notes.md` §5).

- **"IN THE SAME ORDER"**: We match enrichment output to OCR input by index, not by
  text content. Without this constraint, the model sometimes reorders objects,
  causing misaligned overlay.

- **"exactly the same number of items"**: Explicitly required because the model
  occasionally drops regions it considers unimportant (decorative elements, slide
  numbers). Every region must appear in the output so callers can zip input and
  output lists safely.

- **"Refine if you can improve it; otherwise copy"**: For `box_2d` and `font_size_px`,
  this formulation gives the model permission to improve on the OCR pass without
  requiring it. Forcing refinement leads to random drift on already-accurate values.

---

## Changing a prompt

1. Test the new prompt on at least 3 representative slides before merging.
2. Update the prompt constant in code (`ocr.py` or `enrichment.py`).
3. Bump the version string in the table at the top of this file.
4. Add a row to the version history describing what changed and why.
5. If the change affects the JSON schema (adds/renames/removes fields), update
   `schemas.py` and any code that reads those fields.
