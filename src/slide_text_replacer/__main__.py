"""
Module: __main__
================
CLI entry point for slide_text_replacer.

Usage:
    python -m slide_text_replacer
        Opens a file-open dialog to select the input PPTX, then a save-as
        dialog to choose the output location. Both dialogs must be confirmed;
        cancelling either exits cleanly with a message.

    python -m slide_text_replacer <input.pptx>
        Input given on the command line. Opens a save-as dialog for the output.

    python -m slide_text_replacer <input.pptx> <output.pptx>
        Fully headless — no dialogs. Useful for scripting or CI.

Core functions:
  - main() -> None:
    Parses arguments, opens dialogs as needed, validates inputs, loads config,
    and calls run_pipeline(). Logging is configured here.

Helper functions:
  - _pick_input_file() -> str:
    Open a tkinter file-open dialog and return the selected path, or "".
  - _pick_output_file(input_path) -> str:
    Open a tkinter save-as dialog pre-filled with <stem>_reconstructed.pptx
    and return the chosen path, or "".

Pipeline role: the outer shell. Wires user input to run_pipeline(). Not part
  of the processing pipeline itself.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from slide_text_replacer.config import load_config
from slide_text_replacer.pipeline import run_pipeline

log = logging.getLogger(__name__)

# logs/ directory lives in the project root (two levels above this file).
_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"


def _setup_logging() -> Path:
    """
    Configure logging with console (INFO) and per-run file (DEBUG) handlers.

    Creates a timestamped log file in the logs/ directory at the project root.
    The directory is created if it does not exist.

    Returns:
        Path to the created log file.
    """
    _LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = _LOGS_DIR / f"{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console: INFO, compact format.
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root_logger.addHandler(console)

    # File: DEBUG, full timestamps and module names.
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
    )
    root_logger.addHandler(file_handler)

    return log_file


def _pick_input_file() -> str:
    """
    Open a file-open dialog for the user to select the input PPTX.

    Uses tkinter from the Python standard library. The root window is created
    hidden and destroyed immediately after the dialog closes, so no persistent
    window appears.

    Args:
        None.

    Returns:
        The selected file path as a string, or an empty string if the user
        cancelled the dialog.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Select input PPTX",
        filetypes=[("PowerPoint files", "*.pptx"), ("All files", "*.*")],
    )
    root.destroy()
    return path or ""


def _pick_output_file(input_path: str) -> str:
    """
    Open a save-as dialog for the user to choose the output PPTX location.

    Pre-fills the dialog with the input file's stem plus "_reconstructed.pptx"
    as a sensible default. The user can change both the filename and directory.

    Args:
        input_path: Path to the selected input PPTX. Used only to derive the
                    default output filename; the file is not opened.

    Returns:
        The chosen save path as a string, or an empty string if the user
        cancelled the dialog.
    """
    import tkinter as tk
    from tkinter import filedialog

    stem = Path(input_path).stem
    default_name = f"{stem}_reconstructed.pptx"

    root = tk.Tk()
    root.withdraw()
    path = filedialog.asksaveasfilename(
        title="Save output PPTX as",
        initialfile=default_name,
        defaultextension=".pptx",
        filetypes=[("PowerPoint files", "*.pptx"), ("All files", "*.*")],
    )
    root.destroy()
    return path or ""


def main() -> None:
    """
    Parse arguments or open dialogs, validate inputs, and run the pipeline.

    Argument modes:
      - 0 args: both input and output selected via dialog boxes.
      - 1 arg:  input from CLI, output from save-as dialog.
      - 2 args: both from CLI — no dialogs opened.

    Exits with code 0 on success or clean user cancellation (dialog dismissed).
    Exits with code 1 on usage errors or missing input files.

    Args:
        None (reads sys.argv).

    Returns:
        None.
    """
    log_file = _setup_logging()
    log.info("Log file: %s", log_file)

    argc = len(sys.argv) - 1  # exclude the module name

    if argc == 0:
        input_pptx = _pick_input_file()
        if not input_pptx:
            print("No input file selected.")
            sys.exit(0)
        output_pptx = _pick_output_file(input_pptx)
        if not output_pptx:
            print("No output location selected.")
            sys.exit(0)

    elif argc == 1:
        input_pptx = sys.argv[1]
        output_pptx = _pick_output_file(input_pptx)
        if not output_pptx:
            print("No output location selected.")
            sys.exit(0)

    elif argc == 2:
        input_pptx, output_pptx = sys.argv[1], sys.argv[2]

    else:
        print("Usage: python -m slide_text_replacer [<input.pptx> [<output.pptx>]]")
        sys.exit(1)

    if not Path(input_pptx).exists():
        print(f"Error: input file not found: {input_pptx}")
        sys.exit(1)
    if not input_pptx.lower().endswith(".pptx"):
        print("Error: input must be a .pptx file.")
        sys.exit(1)

    config = load_config()
    run_pipeline(input_pptx, output_pptx, config)


if __name__ == "__main__":
    main()
