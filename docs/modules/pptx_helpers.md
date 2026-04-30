# pptx_helpers

Low-level XML helpers for python-pptx. Enable correct Hebrew rendering via complex-script fonts and RTL paragraph attributes.

## Public functions

### `set_run_font(run, font_name) -> None`

| Input       | Type  | Description                           |
|-------------|-------|---------------------------------------|
| `run`       | `Run` | python-pptx Run object from `paragraph.add_run()`. |
| `font_name` | `str` | Font name, e.g. `"Heebo"`.           |

| Output | Type   | Description                     |
|--------|--------|---------------------------------|
| return | `None` | Modifies run's XML in place.    |

### Behavior

1. Removes any existing `<a:latin>`, `<a:cs>`, `<a:ea>` child elements from run properties.
2. Appends `<a:latin typeface="font_name">` — required for English characters.
3. Appends `<a:cs typeface="font_name">` — required for Hebrew characters.
4. Sets `lang="he-IL"` on run properties for correct bidi shaping.

Why both elements: python-pptx only exposes `<a:latin>`. Hebrew text requires `<a:cs>` (complex-script) to render with the correct font. Without it, PowerPoint falls back to a system default.

---

### `set_paragraph_rtl(paragraph) -> None`

| Input       | Type        | Description                     |
|-------------|-------------|---------------------------------|
| `paragraph` | `Paragraph` | python-pptx Paragraph object.  |

| Output | Type   | Description                          |
|--------|--------|--------------------------------------|
| return | `None` | Modifies paragraph's XML in place.   |

### Behavior

Sets `rtl="1"` on the paragraph's `<a:pPr>` element. Idempotent — safe to call multiple times. Essential for correct Hebrew visual order.

## Dependencies

`lxml` (etree), `pptx.oxml.ns` (qn).
