# extraction

Opens a PPTX file and extracts the largest background image from each slide. First pipeline stage. No API calls.

## Public functions

### `extract_slide_inputs(pptx_path: str) -> tuple[Presentation, list[dict]]`

| Input       | Type  | Description                  |
|-------------|-------|------------------------------|
| `pptx_path` | `str` | Path to input `.pptx` file.  |

| Output   | Type                              | Description |
|----------|-----------------------------------|-------------|
| `prs`    | `Presentation`                    | Open python-pptx Presentation object. Must stay alive until save. |
| `slides` | `list[dict]`                      | One dict per slide that has a picture (see schema below). |

Each dict in the output list:

| Key            | Type    | Description                              |
|----------------|---------|------------------------------------------|
| `slide_idx`    | `int`   | 1-based slide number.                    |
| `slide`        | `Slide` | python-pptx Slide object.               |
| `pic`          | `Shape` | Largest Picture shape on the slide.      |
| `image_bytes`  | `bytes` | Raw image data (PNG or JPEG).            |
| `mime_type`    | `str`   | `"image/png"` or `"image/jpeg"`.         |

| Raises                  | When                           |
|-------------------------|--------------------------------|
| `PackageNotFoundError`  | PPTX file not found or invalid. |

Slides without pictures are skipped silently (logged at INFO).

---

### `extract_slides(pptx_path: str) -> list[tuple[int, bytes, str]]`

Simplified wrapper. Returns `(slide_idx, image_bytes, mime_type)` tuples. Discards the Presentation and shape references.

| Input       | Type  | Description                 |
|-------------|-------|-----------------------------|
| `pptx_path` | `str` | Path to input `.pptx` file. |

| Output | Type                           | Description |
|--------|--------------------------------|-------------|
| return | `list[tuple[int, bytes, str]]` | `(slide_idx, image_bytes, mime_type)` per slide. |

## Dependencies

`python-pptx`, stdlib `logging`.

---

## Future alternatives

### win32com-based extraction (universal PPTX support)

The current approach finds the largest `Picture` shape per slide and extracts its embedded image bytes. This works perfectly for NotebookLM exports where each slide IS a single full-bleed image, but it cannot handle slides with mixed shapes, charts, SmartArt, or text-heavy layouts.

Using `win32com.client` to drive PowerPoint's own renderer via `Slide.Export()` would produce a pixel-perfect rasterization of any slide, regardless of content:

```python
import win32com.client

app = win32com.client.Dispatch("PowerPoint.Application")
prs = app.Presentations.Open(pptx_path, WithWindow=False)
for i, slide in enumerate(prs.Slides, 1):
    slide.Export(f"slide_{i}.png", "PNG", 1920, 1080)
prs.Close()
app.Quit()
```

**Why this would help:** Any PPTX — not just image-only NotebookLM exports — could be processed through the pipeline. Charts, grouped shapes, SmartArt, and complex layouts would all render correctly.

**What else would need to change:** The reconstruction module currently uses `old_pic` (the original Picture shape reference) to determine slide dimensions and position the cleaned background image. With win32com extraction there is no `old_pic` — reconstruction would need to read slide dimensions from the Presentation object directly and place the exported raster at full-slide size.

**Why not now:** The tool's current scope is NotebookLM exports, which are always single-image slides. The python-pptx approach is cross-platform (works on Linux/macOS), has no COM dependency, and is simpler. win32com requires a Windows machine with PowerPoint installed, which limits portability. Worth revisiting if the tool needs to support arbitrary PPTX files.
