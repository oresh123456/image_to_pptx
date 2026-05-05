"""
Module: pipeline
================
Orchestrates the full slide-text-replacement pipeline using a thread pool.

Each slide gets one ThreadPoolExecutor future. Within that future:
  OCR fires 10 parallel Gemini calls → returns top-2 consensus-stabilized candidates →
  each candidate runs through enrichment → masking → inpainting independently.

After all futures complete, reconstruction runs on the main thread: candidate #1
rebuilds the original slide, candidate #2 gets a new blank slide. Slides are then
reordered to interleave [1a, 1b, 2a, 2b, ...] so the user can pick the better one.

Core functions (used by __main__.py):
  - run_pipeline(input_pptx, output_pptx, config) -> None:
    The single public entry point. Opens the PPTX, resolves the LaMa model
    version, dispatches one future per slide, waits for completion, runs
    reconstruction (2 slides per input), and saves the output file.

Helper functions (internal worker):
  - _process_slide(slide_input, version_id, config) -> list[(bytes, list[EnrichedRegion])]:
    Worker function executed inside each future. Runs OCR (returns 2 candidates),
    then enrichment + masking + inpainting for each candidate. Returns a list of
    2 tuples [(clean_bytes, enriched_regions), ...].

Pipeline role: this IS the pipeline. Called once by __main__.main() with the
  validated Config. It imports and calls all other processing modules.

Parallelism model:
  - One Future per slide; ThreadPoolExecutor with max_workers=config.max_concurrent.
  - Within each future, 10 OCR calls run in parallel (inner pool), then the 2
    selected candidates are processed sequentially through enrichment/masking/inpainting.
  - Reconstruction runs on the main thread after all futures complete.
  - Default max_concurrent=1 is safe on free-tier Replicate accounts. Increase
    to 5 in config.toml once the account has > $5 credit (notes.md §6.6).

Output: 2x slides per input slide (interleaved A/B versions).
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
) -> list[tuple[bytes, list[EnrichedRegion]]]:
    """
    Run the complete per-slide API pipeline for one slide (2 candidates).

    Called inside a ThreadPoolExecutor future. OCR returns top-2 candidates,
    then each is processed through enrichment → masking → inpainting.

    Args:
        slide_input: Dict from extraction.extract_slide_inputs() containing
                     at least "slide_idx", "image_bytes", and "mime_type".
        version_id:  Replicate LaMa model version ID from resolve_version().
        config:      Pipeline configuration.

    Returns:
        A list of 2 tuples [(clean_bytes, enriched_regions), ...] — one per
        candidate. Each clean_bytes is inpainted PNG, enriched_regions is the
        list of text regions with visual metadata.

    Raises:
        Any exception from OCR, masking, or inpainting that is not caught
        internally. Enrichment failures are handled internally with defaults.
        The caller in run_pipeline() catches all exceptions and logs them.
    """
    idx          = slide_input["slide_idx"]
    image_bytes  = slide_input["image_bytes"]
    mime_type    = slide_input["mime_type"]

    # Stage 1: OCR — returns top-k consensus-stabilized candidates.
    candidates = ocr.run(
        image_bytes, mime_type, config.gemini_api_key, config.gemini_model,
        thinking_budget=config.gemini_thinking_budget,
        candidates=config.gemini_ocr_candidates,
        top_k=config.gemini_ocr_top_k,
        timeout=config.gemini_timeout,
    )
    log.debug("Slide %d: OCR → %d candidates.", idx, len(candidates))

    results: list[tuple[bytes, list[EnrichedRegion]]] = []
    for i, regions in enumerate(candidates):
        # Stage 2: Enrichment
        enriched = enrichment.run(
            image_bytes, mime_type, regions, config.gemini_api_key, config.gemini_model,
            thinking_budget=config.gemini_thinking_budget,
            timeout=config.gemini_timeout,
        )
        log.debug("Slide %d candidate %d: enrichment → %d region(s).", idx, i, len(enriched))

        # Stage 3: Masking
        mask_bytes = masking.build_mask(
            image_bytes,
            enriched,
            padding_px=config.mask_padding_px,
            blur_radius=config.mask_blur_radius,
        )

        # Stage 4: Inpainting
        clean_bytes = inpainting.inpaint(
            version_id,
            image_bytes,
            mime_type,
            mask_bytes,
            token=config.replicate_token,
        )
        results.append((clean_bytes, enriched))

    log.debug("Slide %d: all candidates processed.", idx)
    return results


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
    results: dict[int, list[tuple[bytes, list[EnrichedRegion]]]] = {}

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
                candidate_results = future.result()
                results[idx] = candidate_results
                log.info("Slide %d: done (%d candidates).", idx, len(candidate_results))
            except Exception as exc:
                log.error("Slide %d: error — %s", idx, exc)

    # Step 4: Reconstruct on the main thread.
    # For each slide: rebuild original with candidate #1, add new slide with candidate #2.
    log.info("Reconstructing PPTX...")
    ok_count = 0
    added_slides = []  # track (original_idx, new_slide) for reordering

    for si in slide_inputs:
        idx = si["slide_idx"]
        if idx not in results:
            log.warning(
                "Slide %d: no result (see error above) — left unchanged.", idx
            )
            continue
        candidate_results = results[idx]

        # Candidate #1: rebuild on original slide
        clean_bytes_1, enriched_1 = candidate_results[0]
        try:
            reconstruction.rebuild_slide(
                si["slide"], si["pic"], clean_bytes_1, enriched_1, config
            )
            ok_count += 1
        except Exception as exc:
            log.error("Slide %d candidate 0: reconstruction error — %s", idx, exc)

        # Candidate #2: add a new blank slide after all originals
        if len(candidate_results) >= 2:
            clean_bytes_2, enriched_2 = candidate_results[1]
            try:
                new_slide = reconstruction.add_candidate_slide(
                    prs, clean_bytes_2, enriched_2,
                    si["slide"], config,
                )
                added_slides.append((idx, new_slide))
                ok_count += 1
            except Exception as exc:
                log.error("Slide %d candidate 1: reconstruction error — %s", idx, exc)

    # Step 5: Reorder slides to interleave [1a, 1b, 2a, 2b, ...].
    if added_slides:
        reconstruction.interleave_candidate_slides(prs, slide_inputs, added_slides)

    # Step 6: Save.
    prs.save(output_pptx)
    elapsed = time.time() - t0
    log.info(
        "Done in %.1fs — %d/%d slide-candidates reconstructed. Saved: %r",
        elapsed, ok_count, len(slide_inputs) * 2, output_pptx,
    )
