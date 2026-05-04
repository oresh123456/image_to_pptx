"""
Tests for pipeline.py — orchestration with ThreadPoolExecutor.

Verifies I/O contracts documented in docs/modules/pipeline.md.
All tests are local — no API calls. All stage modules mocked.
"""

import io
from unittest.mock import patch, MagicMock, call

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

from slide_text_replacer.config import Config
from slide_text_replacer.schemas import EnrichedRegion


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_config(**overrides) -> Config:
    defaults = dict(gemini_api_key="k", replicate_token="t")
    defaults.update(overrides)
    return Config(**defaults)


def _make_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _enriched_region(text: str = "test") -> EnrichedRegion:
    return EnrichedRegion(
        text=text, box_2d=(100, 100, 200, 500), font_size_px=20.0,
        font_family="Heebo", font_weight="regular", color="#000000",
    )


# ── _process_slide(): output contract ────────────────────────────────────────
# Input: slide_input dict, version_id, config → Output: (clean_bytes, list[EnrichedRegion]).

@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
def test_process_slide_calls_all_stages(mock_ocr, mock_enrich, mock_masking, mock_inpaint):
    """Input: slide_input → Output: all 4 stages called (OCR, enrichment, masking, inpainting)."""
    from slide_text_replacer.pipeline import _process_slide
    from slide_text_replacer.schemas import Region

    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"
    mock_inpaint.inpaint.return_value = b"clean"

    slide_input = {"slide_idx": 1, "image_bytes": b"img", "mime_type": "image/png"}
    _process_slide(slide_input, "v1", _make_config())

    mock_ocr.run.assert_called_once()
    mock_enrich.run.assert_called_once()
    mock_masking.build_mask.assert_called_once()
    mock_inpaint.inpaint.assert_called_once()


@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
def test_process_slide_passes_config_params(mock_ocr, mock_enrich, mock_masking, mock_inpaint):
    """Input: config with custom params → Output: correct params forwarded to stages."""
    from slide_text_replacer.pipeline import _process_slide
    from slide_text_replacer.schemas import Region

    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"
    mock_inpaint.inpaint.return_value = b"clean"

    config = _make_config(mask_padding_px=20, mask_blur_radius=3.0)
    slide_input = {"slide_idx": 1, "image_bytes": b"img", "mime_type": "image/png"}
    _process_slide(slide_input, "v1", config)

    ocr_args = mock_ocr.run.call_args
    assert ocr_args[0][2] == "k"              # api_key
    assert ocr_args[0][3] == "gemini-2.5-flash"  # model

    mask_kwargs = mock_masking.build_mask.call_args
    assert mask_kwargs[1]["padding_px"] == 20
    assert mask_kwargs[1]["blur_radius"] == 3.0


# ── run_pipeline(): output contract ──────────────────────────────────────────
# Input: input_pptx, output_pptx, config → Output: saves output PPTX.

@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_saves_output(mock_extract, mock_ocr, mock_enrich, mock_masking, mock_inpaint, mock_recon, tmp_path):
    """Input: valid PPTX → Output: prs.save() called with output path."""
    from slide_text_replacer.pipeline import run_pipeline
    from slide_text_replacer.schemas import Region

    mock_prs = MagicMock()
    mock_slide_input = {
        "slide_idx": 1, "slide": MagicMock(), "pic": MagicMock(),
        "image_bytes": b"img", "mime_type": "image/png",
    }
    mock_extract.extract_slide_inputs.return_value = (mock_prs, [mock_slide_input])
    mock_inpaint.resolve_version.return_value = "v1"
    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"
    mock_inpaint.inpaint.return_value = b"clean"

    output = str(tmp_path / "output.pptx")
    run_pipeline("input.pptx", output, _make_config())
    mock_prs.save.assert_called_once_with(output)


@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_no_slides_saves_unchanged(mock_extract, mock_inpaint, mock_recon, tmp_path):
    """Input: no picture slides → Output: saves unchanged copy, no processing."""
    from slide_text_replacer.pipeline import run_pipeline

    mock_prs = MagicMock()
    mock_extract.extract_slide_inputs.return_value = (mock_prs, [])

    output = str(tmp_path / "output.pptx")
    run_pipeline("input.pptx", output, _make_config())
    mock_prs.save.assert_called_once_with(output)
    mock_inpaint.resolve_version.assert_not_called()


@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_resolves_version_once(mock_extract, mock_ocr, mock_enrich, mock_masking, mock_inpaint, mock_recon, tmp_path):
    """Input: 3 slides → Output: resolve_version called exactly once (shared)."""
    from slide_text_replacer.pipeline import run_pipeline
    from slide_text_replacer.schemas import Region

    slides = [
        {"slide_idx": i, "slide": MagicMock(), "pic": MagicMock(), "image_bytes": b"img", "mime_type": "image/png"}
        for i in range(1, 4)
    ]
    mock_prs = MagicMock()
    mock_extract.extract_slide_inputs.return_value = (mock_prs, slides)
    mock_inpaint.resolve_version.return_value = "v1"
    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"
    mock_inpaint.inpaint.return_value = b"clean"

    output = str(tmp_path / "output.pptx")
    run_pipeline("input.pptx", output, _make_config())
    mock_inpaint.resolve_version.assert_called_once()


@patch("slide_text_replacer.pipeline.ThreadPoolExecutor")
@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_max_concurrent_forwarded(mock_extract, mock_inpaint, mock_recon, mock_tpe_class, tmp_path):
    """Input: config.max_concurrent=5 → Output: ThreadPoolExecutor(max_workers=5)."""
    from slide_text_replacer.pipeline import run_pipeline

    mock_prs = MagicMock()
    slide = {"slide_idx": 1, "slide": MagicMock(), "pic": MagicMock(), "image_bytes": b"img", "mime_type": "image/png"}
    mock_extract.extract_slide_inputs.return_value = (mock_prs, [slide])
    mock_inpaint.resolve_version.return_value = "v1"

    mock_executor = MagicMock()
    mock_tpe_class.return_value.__enter__ = MagicMock(return_value=mock_executor)
    mock_tpe_class.return_value.__exit__ = MagicMock(return_value=False)
    mock_executor.submit.return_value = MagicMock()

    with patch("slide_text_replacer.pipeline.as_completed", return_value=[]):
        output = str(tmp_path / "output.pptx")
        run_pipeline("input.pptx", output, _make_config(max_concurrent=5))
    mock_tpe_class.assert_called_once_with(max_workers=5)


# ── run_pipeline(): error handling ───────────────────────────────────────────
# Per-slide errors don't abort the pipeline. Reconstruction errors don't prevent save.

@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_per_slide_error_continues(mock_extract, mock_ocr, mock_enrich, mock_masking, mock_inpaint, mock_recon, tmp_path):
    """Input: slide 1 fails, slide 2 succeeds → Output: save still called, slide 2 reconstructed."""
    from slide_text_replacer.pipeline import run_pipeline
    from slide_text_replacer.schemas import Region

    slide1 = {"slide_idx": 1, "slide": MagicMock(), "pic": MagicMock(), "image_bytes": b"img1", "mime_type": "image/png"}
    slide2 = {"slide_idx": 2, "slide": MagicMock(), "pic": MagicMock(), "image_bytes": b"img2", "mime_type": "image/png"}
    mock_prs = MagicMock()
    mock_extract.extract_slide_inputs.return_value = (mock_prs, [slide1, slide2])
    mock_inpaint.resolve_version.return_value = "v1"
    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"

    call_count = [0]
    def inpaint_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("inpaint error on slide 1")
        return b"clean"
    mock_inpaint.inpaint.side_effect = inpaint_side_effect

    output = str(tmp_path / "output.pptx")
    run_pipeline("input.pptx", output, _make_config())
    mock_prs.save.assert_called_once()
    assert mock_recon.rebuild_slide.call_count >= 1


@patch("slide_text_replacer.pipeline.reconstruction")
@patch("slide_text_replacer.pipeline.inpainting")
@patch("slide_text_replacer.pipeline.masking")
@patch("slide_text_replacer.pipeline.enrichment")
@patch("slide_text_replacer.pipeline.ocr")
@patch("slide_text_replacer.pipeline.extraction")
def test_run_pipeline_reconstruction_error_still_saves(mock_extract, mock_ocr, mock_enrich, mock_masking, mock_inpaint, mock_recon, tmp_path):
    """Input: rebuild_slide raises → Output: save still called."""
    from slide_text_replacer.pipeline import run_pipeline
    from slide_text_replacer.schemas import Region

    slide = {"slide_idx": 1, "slide": MagicMock(), "pic": MagicMock(), "image_bytes": b"img", "mime_type": "image/png"}
    mock_prs = MagicMock()
    mock_extract.extract_slide_inputs.return_value = (mock_prs, [slide])
    mock_inpaint.resolve_version.return_value = "v1"
    mock_ocr.run.return_value = [Region(text="x", box_2d=(0, 0, 100, 100), font_size_px=16.0)]
    mock_enrich.run.return_value = [_enriched_region()]
    mock_masking.build_mask.return_value = b"mask"
    mock_inpaint.inpaint.return_value = b"clean"
    mock_recon.rebuild_slide.side_effect = RuntimeError("reconstruction error")

    output = str(tmp_path / "output.pptx")
    run_pipeline("input.pptx", output, _make_config())
    mock_prs.save.assert_called_once()
