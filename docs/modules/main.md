# __main__

CLI entry point. Handles argument parsing, tkinter file dialogs, logging setup, and pipeline invocation. Not part of the processing pipeline itself.

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
| 0      | Input and output selected via tkinter dialogs.     |
| 1      | Input from CLI, output via save-as dialog.         |
| 2      | Both from CLI — fully headless.                    |
| 3+     | Prints usage, exits with code 1.                   |

### Exit codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| 0    | Success, or user cancelled a dialog.       |
| 1    | Usage error, missing file, or non-`.pptx`. |

### Execution flow

1. `_setup_logging()` — configures console (INFO) + file (DEBUG) handlers.
2. Parse args / open dialogs.
3. Validate input file exists and ends with `.pptx`.
4. `load_config()` → `Config`.
5. `run_pipeline(input_pptx, output_pptx, config)`.

## Logging setup (`_setup_logging`)

| Handler | Level   | Format                                          | Destination |
|---------|---------|-------------------------------------------------|-------------|
| Console | `INFO`  | `LEVEL message`                                 | stderr      |
| File    | `DEBUG` | `timestamp LEVEL    [module] message`            | `logs/YYYY-MM-DD_HHMMSS.log` |

Log directory: `logs/` at project root. Created automatically.

## Dependencies

`config` (load_config), `pipeline` (run_pipeline), stdlib `logging`, `sys`, `datetime`, `pathlib`, `tkinter`.
