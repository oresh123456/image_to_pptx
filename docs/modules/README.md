# Module I/O Reference

Per-module documentation specifying exact inputs, outputs, types, and error behavior. Read only the module(s) you're working on — each doc is self-contained.

## Data flow

```
extraction → ocr → enrichment → masking → inpainting → reconstruction
                                   ↓                        ↑
                              schemas.py              pptx_helpers
```

## Modules

| Module | Doc | Purpose |
|--------|-----|---------|
| `schemas` | [schemas.md](schemas.md) | Frozen dataclasses: `Region`, `EnrichedRegion`, `SlideData` |
| `config` | [config.md](config.md) | Load `config.toml` + env vars → `Config` |
| `extraction` | [extraction.md](extraction.md) | PPTX → per-slide image bytes |
| `ocr` | [ocr.md](ocr.md) | Gemini OCR → `list[Region]` |
| `enrichment` | [enrichment.md](enrichment.md) | Gemini vision → `list[EnrichedRegion]` |
| `masking` | [masking.md](masking.md) | Bounding boxes → binary mask PNG |
| `inpainting` | [inpainting.md](inpainting.md) | Replicate LaMa → clean image bytes |
| `reconstruction` | [reconstruction.md](reconstruction.md) | Clean image + text overlays → modified slide |
| `pptx_helpers` | [pptx_helpers.md](pptx_helpers.md) | XML helpers for Hebrew fonts + RTL |
| `retry` | [retry.md](retry.md) | Shared retry with backoff + jitter |
| `pipeline` | [pipeline.md](pipeline.md) | Orchestration with ThreadPoolExecutor |
| `__main__` | [main.md](main.md) | CLI entry point + logging setup |
