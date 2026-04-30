# pipeline

Orchestrates the full slide-text-replacement pipeline using `ThreadPoolExecutor`. Single public entry point called by `__main__`.

## Public functions

### `run_pipeline(input_pptx, output_pptx, config) -> None`

| Input         | Type     | Description                            |
|---------------|----------|----------------------------------------|
| `input_pptx`  | `str`    | Path to input `.pptx` file.            |
| `output_pptx` | `str`    | Path where output `.pptx` will be written. |
| `config`      | `Config` | Validated config from `load_config()`. |

| Output | Type   | Description                       |
|--------|--------|-----------------------------------|
| return | `None` | Writes result to `output_pptx`.   |

| Raises         | When                                                   |
|----------------|--------------------------------------------------------|
| `RuntimeError` | Replicate model version lookup fails.                  |
| *(from extraction)* | Input file not found or invalid.                  |

Slide-level errors are caught and logged — the slide is left unchanged in the output.

### Execution flow

1. **Extract** — `extraction.extract_slide_inputs(input_pptx)` → `(Presentation, list[dict])`.
2. **Resolve version** — `inpainting.resolve_version()` → `str`. Called once, shared by all workers.
3. **Process slides** — `ThreadPoolExecutor(max_workers=config.max_concurrent)`. `max_concurrent` defaults to 1 for Replicate free-tier safety (~6 predictions/min). One future per slide. Within each future, sequential stages:
   - `ocr.run()` → `list[Region]`
   - `enrichment.run()` → `list[EnrichedRegion]`
   - `masking.build_mask()` → `bytes`
   - `inpainting.inpaint()` → `bytes`
4. **Reconstruct** — Main thread. `reconstruction.rebuild_slide()` for each successful slide.
5. **Save** — `prs.save(output_pptx)`.

### Early exit

If no slides contain pictures: saves an unchanged copy and returns.

## Dependencies

`extraction`, `ocr`, `enrichment`, `masking`, `inpainting`, `reconstruction`, `config` (Config), `schemas` (EnrichedRegion), stdlib `logging`, `time`, `concurrent.futures`.
