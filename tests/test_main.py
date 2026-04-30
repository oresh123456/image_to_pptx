"""
Tests for __main__.py — CLI entry point and argument handling.

Verifies I/O contracts documented in docs/modules/main.md.
All tests are local — no API calls. tkinter dialogs bypassed via mocks.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from slide_text_replacer.__main__ import main


@pytest.fixture(autouse=True)
def _mock_logging(tmp_path):
    """Prevent _setup_logging from creating files during tests."""
    with patch(
        "slide_text_replacer.__main__._setup_logging",
        return_value=tmp_path / "test.log",
    ):
        yield


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_dummy_pptx(tmp_path: Path, name: str = "input.pptx") -> Path:
    p = tmp_path / name
    p.write_bytes(b"PK\x03\x04")  # minimal ZIP signature
    return p


# ── main(): 2 args (headless) — output contract ─────────────────────────────

@patch("slide_text_replacer.__main__.run_pipeline")
@patch("slide_text_replacer.__main__.load_config")
def test_main_two_args_calls_pipeline(mock_config, mock_pipeline, tmp_path, monkeypatch):
    """Input: 2 CLI args → Output: run_pipeline called with both paths."""
    input_path = _create_dummy_pptx(tmp_path)
    output_path = tmp_path / "output.pptx"
    monkeypatch.setattr(sys, "argv", ["prog", str(input_path), str(output_path)])
    mock_config.return_value = MagicMock()

    main()

    mock_config.assert_called_once()
    mock_pipeline.assert_called_once()
    args = mock_pipeline.call_args[0]
    assert args[0] == str(input_path)
    assert args[1] == str(output_path)


@patch("slide_text_replacer.__main__.run_pipeline")
@patch("slide_text_replacer.__main__.load_config")
def test_main_passes_config_to_pipeline(mock_config, mock_pipeline, tmp_path, monkeypatch):
    """Input: CLI args → Output: load_config() result forwarded to run_pipeline."""
    input_path = _create_dummy_pptx(tmp_path)
    output_path = tmp_path / "output.pptx"
    monkeypatch.setattr(sys, "argv", ["prog", str(input_path), str(output_path)])
    sentinel_config = MagicMock(name="sentinel_config")
    mock_config.return_value = sentinel_config

    main()

    mock_config.assert_called_once()
    pipeline_config = mock_pipeline.call_args[0][2]
    assert pipeline_config is sentinel_config


# ── main(): argument validation — error handling ─────────────────────────────

def test_main_too_many_args_exits_1(monkeypatch):
    """Input: 3+ args → Output: sys.exit(1)."""
    monkeypatch.setattr(sys, "argv", ["prog", "a.pptx", "b.pptx", "c.pptx"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_nonexistent_input_exits_1(monkeypatch, tmp_path):
    """Input: missing file path → Output: sys.exit(1)."""
    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path / "missing.pptx"), "out.pptx"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_non_pptx_exits_1(monkeypatch, tmp_path):
    """Input: .txt file → Output: sys.exit(1)."""
    txt_file = tmp_path / "input.txt"
    txt_file.write_text("not a pptx")
    monkeypatch.setattr(sys, "argv", ["prog", str(txt_file), "out.pptx"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


# ── main(): dialog cancellation — exit codes ─────────────────────────────────

@patch("slide_text_replacer.__main__._pick_input_file", return_value="")
def test_main_zero_args_cancelled_exits_0(mock_pick, monkeypatch):
    """Input: 0 args, user cancels input dialog → Output: sys.exit(0)."""
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


@patch("slide_text_replacer.__main__._pick_output_file", return_value="")
def test_main_one_arg_cancelled_output_exits_0(mock_pick, monkeypatch, tmp_path):
    """Input: 1 arg, user cancels output dialog → Output: sys.exit(0)."""
    input_path = _create_dummy_pptx(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", str(input_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
