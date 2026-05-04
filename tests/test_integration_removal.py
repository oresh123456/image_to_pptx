"""Integration tests — text removal (masking + inpainting).

Requires: real config keys, test_input.pptx in tests/fixtures/.
Outputs saved to tests/output/ for visual inspection.
"""

from pathlib import Path

import pytest
from PIL import Image

from slide_text_replacer.config import Config
from slide_text_replacer.extraction import extract_slide_inputs
from slide_text_replacer.ocr import run as ocr_run
from slide_text_replacer.enrichment import run as enrichment_run
from slide_text_replacer.masking import build_mask
from slide_text_replacer.inpainting import resolve_version, inpaint


pytestmark = pytest.mark.integration


def _ocr_and_enrich(slide_info: dict, config: Config):
    """Run OCR + enrichment for a single slide dict."""
    regions = ocr_run(
        slide_info["image_bytes"],
        slide_info["mime_type"],
        config.gemini_api_key,
        config.gemini_model,
    )
    enriched = enrichment_run(
        slide_info["image_bytes"],
        slide_info["mime_type"],
        regions,
        config.gemini_api_key,
        config.gemini_model,
    )
    return regions, enriched


class TestMaskGeneration:
    def test_mask_produces_visible_white(
        self, real_config, test_pptx_path, output_dir,
    ):
        """Mask has white pixels > 0 for every slide with detected text."""
        _prs, slides = extract_slide_inputs(str(test_pptx_path))
        assert slides, "No slides with pictures found"

        for s in slides:
            _regions, enriched = _ocr_and_enrich(s, real_config)
            if not enriched:
                continue
            mask_bytes = build_mask(
                s["image_bytes"], enriched,
                real_config.mask_padding_px, real_config.mask_blur_radius,
            )
            out = output_dir / f"slide_{s['slide_idx']}_mask.png"
            out.write_bytes(mask_bytes)

            mask_img = Image.open(out)
            white_px = sum(1 for px in mask_img.getdata() if px > 0)
            assert white_px > 0, f"Slide {s['slide_idx']}: mask is all-black"


class TestInpainting:
    def test_inpainting_produces_clean_image(
        self, real_config, test_pptx_path, output_dir,
    ):
        """Inpainted output is a valid PNG with same dimensions as input."""
        _prs, slides = extract_slide_inputs(str(test_pptx_path))
        assert slides, "No slides with pictures found"
        version_id = resolve_version(
            real_config.replicate_model, real_config.replicate_token,
        )

        for s in slides:
            _regions, enriched = _ocr_and_enrich(s, real_config)
            if not enriched:
                continue
            mask_bytes = build_mask(
                s["image_bytes"], enriched,
                real_config.mask_padding_px, real_config.mask_blur_radius,
            )
            clean_bytes = inpaint(
                version_id, s["image_bytes"], s["mime_type"],
                mask_bytes, real_config.replicate_token,
            )
            out = output_dir / f"slide_{s['slide_idx']}_clean.png"
            out.write_bytes(clean_bytes)

            orig = Image.open(__import__("io").BytesIO(s["image_bytes"]))
            clean = Image.open(out)
            assert clean.size == orig.size, (
                f"Slide {s['slide_idx']}: dimension mismatch "
                f"{clean.size} vs {orig.size}"
            )

    def test_inpainting_vs_original_differs(
        self, real_config, test_pptx_path, output_dir,
    ):
        """Inpainted bytes differ from original (text was removed)."""
        _prs, slides = extract_slide_inputs(str(test_pptx_path))
        assert slides, "No slides with pictures found"
        version_id = resolve_version(
            real_config.replicate_model, real_config.replicate_token,
        )

        for s in slides:
            _regions, enriched = _ocr_and_enrich(s, real_config)
            if not enriched:
                continue
            mask_bytes = build_mask(
                s["image_bytes"], enriched,
                real_config.mask_padding_px, real_config.mask_blur_radius,
            )
            clean_bytes = inpaint(
                version_id, s["image_bytes"], s["mime_type"],
                mask_bytes, real_config.replicate_token,
            )
            assert clean_bytes != s["image_bytes"], (
                f"Slide {s['slide_idx']}: inpainted image identical to original"
            )
