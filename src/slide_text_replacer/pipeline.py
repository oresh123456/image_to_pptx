"""
Module: pipeline
================
Orchestrates the full slide-text-replacement pipeline using a thread pool.

Each slide gets one ThreadPoolExecutor future. Within that future, the stages
run sequentially: OCR → enrichment → masking → inpainting. After all futures
complete, reconstruction runs on the main thread (python-pptx is not thread-safe)
and the PPTX is saved.

Core functions (used by __main__.py):
  - run_pipeline(input_pptx, output_pptx, config) -> None:
    The single public entry point. Opens the PPTX, resolves the LaMa model
    version, dispatches one future per slide, waits for completion, runs
    reconstruction, and saves the output file.

Helper functions (internal worker):
  - _process_slide(slide_input, version_id, config) -> (bytes, list[EnrichedRegion]):
    Worker function executed inside each future. Runs OCR, enrichment, masking,
    and inpainting for one slide. Returns (clean_bytes, enriched_regions) on
    success, or raises on unrecoverable error.

Pipeline role: this IS the pipeline. Called once by __main__.main() with the
  validated Config. It imports and calls all other processing modules.

Parallelism model (from plan.md):
  - One Future per slide; ThreadPoolExecutor with max_workers=config.max_concurrent.
  - Within each future, stages run sequentially (simpler than nested parallelism;
    the bottleneck is the remote APIs, not Python threading overhead).
  - Reconstruction runs on the main thread after all futures complete.
  - Default max_concurrent=1 is safe on free-tier Replicate accounts. Increase
    to 5 in config.toml once the account has > $5 credit (notes.md §6.6).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from slide_text_replacer import extraction, ocr, enrichment, masking, inpainting, reconstruction
from slide_text_replacer.config import Config
from slide_text_replacer.schemas import EnrichedRegion

log = logging.getLogger(__name__)


def _process_slide(
    slide_input: dict,
    version_id: str,
    config: Config,
) -> tuple[bytes, list[EnrichedRegion]]:
    """
    Run the complete per-slide API pipeline for one slide.

    Called inside a ThreadPoolExecutor future. Stages run sequentially:
      1. OCR (Gemini) — detect text regions with bounding boxes.
      2. Enrichment (Gemini) — add font family, weight, color.
      3. Masking (local) — build binary PNG mask from regions.
      4. Inpainting (Replicate) — erase text from the image.

    Args:
        slide_input: Dict from extraction.extract_slide_inputs() containing
                     at least "slide_idx", "image_bytes", and "mime_type".
        version_id:  Replicate LaMa model version ID from resolve_version().
        config:      Pipeline configuration.

    Returns:
        A 2-tuple (clean_bytes, enriched_regions) where:
          - clean_bytes is the inpainted image bytes (PNG).
          - enriched_regions is the list of text regions with visual metadata.

    Raises:
        Any exception from OCR, masking, or inpainting that is not caught
        internally. Enrichment failures are handled internally with defaults.
        The caller in run_pipeline() catches all exceptions and logs them.
    """
    idx          = slide_input["slide_idx"]
    image_bytes  = slide_input["image_bytes"]
    mime_type    = slide_input["mime_type"]

    # Stage 1: OCR.
    regions = ocr.run(image_bytes, mime_type, config.gemini_api_key, config.gemini_model)
    log.debug("Slide %d: OCR → %d region(s).", idx, len(regions))

    # Stage 2: Enrichment (adds font/color metadata; falls back to defaults on error).
    enriched = enrichment.run(
        image_bytes, mime_type, regions, config.gemini_api_key, config.gemini_model
    )
    log.debug("Slide %d: enrichment complete (%d region(s)).", idx, len(enriched))

    # Stage 3: Build mask from enriched regions (uses box_2d, skips watermarks).
    mask_bytes = masking.build_mask(
        image_bytes,
        enriched,
        padding_px=config.mask_padding_px,
        blur_radius=config.mask_blur_radius,
    )
    log.debug("Slide %d: mask built.", idx)

    # Stage 4: Inpaint — erase the masked text regions.
    clean_bytes = inpainting.inpaint(
        version_id,
        image_bytes,
        mime_type,
        mask_bytes,
        token=config.replicate_token,
    )
    log.debug("Slide %d: inpainting done.", idx)

    return clean_bytes, enriched


def run_pipeline(input_pptx: str, output_pptx: str, config: Config) -> None:
    """
    Run the complete slide-text-replacement pipeline from input to output PPTX.

    Steps:
      1. Open the PPTX and collect all slides that contain a picture.
      2. Resolve the Replicate LaMa model version (one API call, shared by all workers).
      3. Process slides in parallel via ThreadPoolExecutor.
      4. Reconstruct all slides on the main thread (python-pptx thread safety).
      5. Save the output PPTX.

    Progress is logged at INFO level (slide N started / done). Slide-level
    errors are logged and the slide is left unchanged in the output file.

    Args:
        input_pptx:  Path to the input .pptx file.
        output_pptx: Path where the output .pptx will be written.
        config:      Validated Config from load_config().

    Returns:
        None. Writes the result to output_pptx.

    Raises:
        RuntimeError: If the Replicate model version lookup fails.
        Any exception that propagates from extraction (e.g. file not found).
    """
    t0 = time.time()

    # Step 1: Extract — open PPTX and collect slide image data.
    prs, slide_inputs = extraction.extract_slide_inputs(input_pptx)
    log.info(
        "Opened %r — %d slide(s) with a picture.", input_pptx, len(slide_inputs)
    )

    if not slide_inputs:
        log.warning("No picture slides found — saving unchanged copy.")
        prs.save(output_pptx)
        return

    # Step 2: Resolve model version once (shared across all worker futures).
    log.info("Resolving LaMa model version...")
    version_id = inpainting.resolve_version(config.replicate_model, config.replicate_token)
    log.info("LaMa version: %s...", version_id[:16])

    # Step 3: Process slides in parallel.
    results: dict[int, tuple[bytes, list[EnrichedRegion]]] = {}

    log.info(
        "Processing %d slide(s) (%d at a time)...",
        len(slide_inputs), config.max_concurrent,
    )
    with ThreadPoolExecutor(max_workers=config.max_concurrent) as executor:
        futures = {
            executor.submit(_process_slide, si, version_id, config): si["slide_idx"]
            for si in slide_inputs
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                clean_bytes, enriched = future.result()
                results[idx] = (clean_bytes, enriched)
                log.info("Slide %d: done.", idx)
            except Exception as exc:
                log.error("Slide %d: error — %s", idx, exc)

    # Step 4: Reconstruct on the main thread.
    log.info("Reconstructing PPTX...")
    ok_count = 0
    for si in slide_inputs:
        idx = si["slide_idx"]
        if idx not in results:
            log.warning(
                "Slide %d: no result (see error above) — left unchanged.", idx
            )
            continue
        clean_bytes, enriched = results[idx]
        try:
            reconstruction.rebuild_slide(
                si["slide"], si["pic"], clean_bytes, enriched, config
            )
            ok_count += 1
        except Exception as exc:
            log.error("Slide %d: reconstruction error — %s", idx, exc)

    # Step 5: Save.
    prs.save(output_pptx)
    elapsed = time.time() - t0
    log.info(
        "Done in %.1fs — %d/%d slides reconstructed. Saved: %r",
        elapsed, ok_count, len(slide_inputs), output_pptx,
    )
