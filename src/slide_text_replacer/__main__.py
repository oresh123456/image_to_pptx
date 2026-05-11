"""
Module: __main__
================
GUI entry point for slide_text_replacer.

Usage:
    python -m slide_text_replacer
        Launches tkinter GUI. On first run (no config.toml or empty keys),
        shows a key-entry dialog. After keys are set, shows the main window.

    python -m slide_text_replacer <input.pptx> <output.pptx>
        Fully headless — no GUI. Useful for scripting.

Pipeline role: the outer shell. Wires user input to run_pipeline().
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from slide_text_replacer.config import (
    has_valid_config,
    load_config,
    save_config,
)
from slide_text_replacer.pipeline import run_pipeline

log = logging.getLogger(__name__)

def _setup_logging() -> Path:
    """Configure logging with console (INFO) and per-run file (DEBUG) handlers."""
    if getattr(sys, "frozen", False):
        logs_dir = Path(sys.executable).parent / "logs"
    else:
        logs_dir = Path(__file__).resolve().parents[2] / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = logs_dir / f"{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root_logger.addHandler(console)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
    )
    root_logger.addHandler(file_handler)

    return log_file


def _run_headless(input_pptx: str, output_pptx: str) -> None:
    """Run pipeline in headless (2-arg CLI) mode."""
    log_file = _setup_logging()
    log.info("Log file: %s", log_file)

    if not Path(input_pptx).exists():
        print(f"Error: input file not found: {input_pptx}")
        sys.exit(1)
    if not input_pptx.lower().endswith(".pptx"):
        print("Error: input must be a .pptx file.")
        sys.exit(1)

    config = load_config()
    if config is None:
        print("Error: config.toml missing or API keys not set.")
        sys.exit(1)
    run_pipeline(input_pptx, output_pptx, config)


def _run_gui(input_path: str | None = None) -> None:
    """Launch the tkinter GUI application.

    Args:
        input_path: Optional pre-filled input .pptx path (from 1-arg mode).
    """
    import tkinter as tk
    from tkinter import filedialog, messagebox

    log_file = _setup_logging()
    log.info("Log file: %s", log_file)

    root = tk.Tk()
    root.title("Slide Text Replacer")
    root.resizable(False, False)

    # --- First-run key dialog ---
    if not has_valid_config():
        _show_key_dialog(root)
        # After key dialog, check again
        if not has_valid_config():
            root.destroy()
            return

    # Load config for defaults
    config = load_config()
    if config is None:
        messagebox.showerror("Error", "Failed to load config after key setup.")
        root.destroy()
        return

    # --- Main window ---
    frame = tk.Frame(root, padx=20, pady=20)
    frame.pack()

    # Input / output variables
    input_var = tk.StringVar()
    output_var = tk.StringVar()

    # Pre-fill if provided (1-arg / context-menu mode)
    if input_path:
        input_var.set(input_path)
        stem = Path(input_path).stem
        output_var.set(str(Path(input_path).parent / f"{stem}_reconstructed.pptx"))

    # Input file selection
    tk.Label(frame, text="Input PPTX:").grid(row=0, column=0, sticky="w")
    input_entry = tk.Entry(frame, textvariable=input_var, width=50, state="readonly")
    input_entry.grid(row=0, column=1, padx=5)

    def browse_input():
        path = filedialog.askopenfilename(
            title="Select input PPTX",
            filetypes=[("PowerPoint files", "*.pptx"), ("All files", "*.*")],
        )
        if path:
            input_var.set(path)
            stem = Path(path).stem
            out = Path(path).parent / f"{stem}_reconstructed.pptx"
            output_var.set(str(out))

    tk.Button(frame, text="Browse...", command=browse_input).grid(row=0, column=2)

    # Output path (auto-derived, shown read-only)
    tk.Label(frame, text="Output:").grid(row=1, column=0, sticky="w", pady=(5, 0))
    tk.Entry(frame, textvariable=output_var, width=50, state="readonly").grid(
        row=1, column=1, padx=5, pady=(5, 0)
    )

    # OCR Candidates spinbox
    tk.Label(frame, text="OCR Candidates (1-10):").grid(
        row=2, column=0, sticky="w", pady=(10, 0)
    )
    candidates_var = tk.IntVar(value=config.gemini_ocr_candidates)
    candidates_spin = tk.Spinbox(
        frame, from_=1, to=10, textvariable=candidates_var, width=5
    )
    candidates_spin.grid(row=2, column=1, sticky="w", padx=5, pady=(10, 0))

    # Top-K spinbox
    tk.Label(frame, text="Slides to generate (1-candidates):").grid(
        row=3, column=0, sticky="w", pady=(5, 0)
    )
    topk_var = tk.IntVar(value=config.gemini_ocr_top_k)
    topk_spin = tk.Spinbox(
        frame, from_=1, to=10, textvariable=topk_var, width=5
    )
    topk_spin.grid(row=3, column=1, sticky="w", padx=5, pady=(5, 0))

    # Status label
    status_var = tk.StringVar(value="Idle")
    status_label = tk.Label(frame, textvariable=status_var, fg="gray")
    status_label.grid(row=5, column=0, columnspan=3, pady=(10, 0))

    # Run button
    def on_run():
        inp = input_var.get()
        out = output_var.get()
        if not inp:
            messagebox.showwarning("Warning", "Select an input file first.")
            return
        if not Path(inp).exists():
            messagebox.showerror("Error", f"File not found: {inp}")
            return

        cands = min(max(candidates_var.get(), 1), 10)
        topk = min(max(topk_var.get(), 1), cands)

        # Save updated config with user's choices
        cfg = load_config()
        save_config(
            gemini_key=cfg.gemini_api_key,
            replicate_token=cfg.replicate_token,
            ocr_candidates=cands,
            ocr_top_k=topk,
        )
        # Reload with new params
        cfg = load_config()

        # Disable controls
        run_btn.config(state="disabled")
        candidates_spin.config(state="disabled")
        topk_spin.config(state="disabled")
        status_var.set("Processing...")
        status_label.config(fg="blue")

        def worker():
            try:
                run_pipeline(inp, out, cfg)
                root.after(0, lambda: _on_done(None))
            except Exception as e:
                root.after(0, lambda err=e: _on_done(err))

        def _on_done(error):
            run_btn.config(state="normal")
            candidates_spin.config(state="normal")
            topk_spin.config(state="normal")
            if error:
                status_var.set(f"Error: {error}")
                status_label.config(fg="red")
                log.error("Pipeline failed: %s", error, exc_info=True)
            else:
                status_var.set(f"Done! Output: {out}")
                status_label.config(fg="green")

        threading.Thread(target=worker, daemon=True).start()

    run_btn = tk.Button(frame, text="Run", command=on_run, width=15)
    run_btn.grid(row=4, column=0, columnspan=3, pady=(15, 0))

    root.mainloop()


def _show_key_dialog(root: "tk.Tk") -> None:
    """Show a modal dialog for first-run API key entry."""
    import tkinter as tk

    dialog = tk.Toplevel(root)
    dialog.title("First-Run Setup — Enter API Keys")
    dialog.grab_set()
    dialog.resizable(False, False)

    frame = tk.Frame(dialog, padx=20, pady=20)
    frame.pack()

    tk.Label(frame, text="Gemini API Key:").grid(row=0, column=0, sticky="w")
    gemini_entry = tk.Entry(frame, width=50)
    gemini_entry.grid(row=0, column=1, padx=5, pady=5)

    tk.Label(frame, text="Replicate Token:").grid(row=1, column=0, sticky="w")
    replicate_entry = tk.Entry(frame, width=50)
    replicate_entry.grid(row=1, column=1, padx=5, pady=5)

    def _paste(event):
        w = event.widget
        try:
            text = w.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            if w.selection_present():
                w.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        w.insert("insert", text)
        return "break"

    def _select_all(event):
        event.widget.select_range(0, "end")
        event.widget.icursor("end")
        return "break"

    for entry in (gemini_entry, replicate_entry):
        entry.bind("<Control-v>", _paste)
        entry.bind("<Control-a>", _select_all)

    tk.Label(
        frame,
        text="Get keys at: aistudio.google.com/apikey & replicate.com/account/api-tokens",
        fg="gray",
    ).grid(row=2, column=0, columnspan=2, pady=(5, 10))

    def on_save():
        g = gemini_entry.get().strip()
        r = replicate_entry.get().strip()
        if not g or not r:
            from tkinter import messagebox
            messagebox.showwarning("Missing keys", "Both keys are required.", parent=dialog)
            return
        save_config(gemini_key=g, replicate_token=r, ocr_candidates=10, ocr_top_k=2)
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    btn_frame = tk.Frame(frame)
    btn_frame.grid(row=3, column=0, columnspan=2)
    tk.Button(btn_frame, text="Save", command=on_save, width=10).pack(side="left", padx=5)
    tk.Button(btn_frame, text="Cancel", command=on_cancel, width=10).pack(side="left", padx=5)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    root.wait_window(dialog)


def main() -> None:
    """Entry point: headless with 2 args, 1-arg opens GUI pre-filled, 0-arg GUI."""
    argc = len(sys.argv) - 1

    if argc == 2:
        _run_headless(sys.argv[1], sys.argv[2])
    elif argc == 1:
        path = sys.argv[1]
        if not path.lower().endswith(".pptx"):
            print("Error: input must be a .pptx file.")
            sys.exit(1)
        if not Path(path).exists():
            print(f"Error: file not found: {path}")
            sys.exit(1)
        _run_gui(input_path=path)
    elif argc == 0:
        _run_gui()
    else:
        print("Usage: python -m slide_text_replacer [<input.pptx> [<output.pptx>]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
