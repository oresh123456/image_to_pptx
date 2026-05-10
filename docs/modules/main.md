# __main__

GUI entry point. Handles argument parsing, tkinter GUI (main window + first-run key dialog), logging setup, and pipeline invocation. Not part of the processing pipeline itself.

## Public functions

### `main() -> None`

| Input  | Type | Description                     |
|--------|------|---------------------------------|
| *(none)* | — | Reads `sys.argv`.              |

| Output | Type   | Description                                   |
|--------|--------|-----------------------------------------------|
| return | `None` | Exits via `sys.exit()` on error/cancellation.  |

### Argument modes

| `argc` | Behavior                                           |
|--------|----------------------------------------------------|
| 0      | Launches GUI (first-run key dialog if needed).     |
| 1      | Launches GUI pre-filled with input path (context menu / drag-drop). |
| 2      | Fully headless — no GUI.                           |
| 3+     | Prints usage, exits with code 1.                   |

### Exit codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| 0    | Success, or user cancelled a dialog.       |
| 1    | Usage error, missing file, or non-`.pptx`. |

### Execution flow

1. `main()` dispatches by `argc`:
   - 0 args → `_run_gui()`
   - 1 arg → validate `.pptx` extension + existence → `_run_gui(input_path=path)`
   - 2 args → `_run_headless(input, output)`
2. `_setup_logging()` — configures console (INFO) + file (DEBUG) handlers. Log dir is computed inside the function body: `Path(sys.executable).parent / "logs"` when frozen, `Path(__file__).parents[2] / "logs"` otherwise.
3. `_run_gui()`:
   - Checks `has_valid_config()` → if false, shows `_show_key_dialog()` for first-run API key entry.
   - Loads config, builds main window with input/output fields, OCR candidates + top-k spinboxes.
   - Runs pipeline in a background thread; updates status label on completion/error.
4. `_run_headless()`:
   - `load_config()` → exit if `None`.
   - `run_pipeline(input, output, config)`.

## Logging setup (`_setup_logging`)

| Handler | Level   | Format                                          | Destination |
|---------|---------|-------------------------------------------------|-------------|
| Console | `INFO`  | `LEVEL message`                                 | stderr      |
| File    | `DEBUG` | `timestamp LEVEL    [module] message`            | `logs/YYYY-MM-DD_HHMMSS.log` |

Log directory: computed inside `_setup_logging()` — exe dir when frozen (`sys.frozen`), project root otherwise. Created automatically.

## Dependencies

`config` (`load_config`, `has_valid_config`, `save_config`), `pipeline` (`run_pipeline`), stdlib `logging`, `sys`, `threading`, `datetime`, `pathlib`, `tkinter`.
