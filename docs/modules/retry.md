# retry

Shared retry utility with exponential backoff, jitter, and server-directed delay support. Used by `ocr`, `enrichment`, and `inpainting`.

## Public classes

### `RetryExhausted(Exception)`

Raised by `retry_call()` when all attempts fail and `max_attempts > 1`.

| Attribute    | Type        | Description                        |
|--------------|-------------|------------------------------------|
| `last_error` | `Exception` | Exception from the final attempt.  |
| `attempts`   | `int`       | Total number of attempts made.     |

### `RateLimitedError(Exception)`

Carries a server-directed delay hint. Used by `inpainting` for HTTP 429 responses.

| Attribute     | Type    | Description                           |
|---------------|---------|---------------------------------------|
| `retry_after` | `float` | Seconds the server asked us to wait.  |

## Public functions

### `retry_call(fn, *, max_attempts, base_delay, backoff_factor, max_delay, jitter, retryable, context) -> T`

| Input            | Type                                  | Default | Description |
|------------------|---------------------------------------|---------|-------------|
| `fn`             | `Callable[[], T]`                     | —       | Zero-argument callable to invoke. |
| `max_attempts`   | `int`                                 | `2`     | Total attempts including the first. |
| `base_delay`     | `float`                               | `1.0`   | Initial delay in seconds. |
| `backoff_factor` | `float`                               | `2.0`   | Multiplier per retry. |
| `max_delay`      | `float`                               | `60.0`  | Cap on calculated delay. |
| `jitter`         | `float`                               | `0.0`   | Max random seconds added to delay. |
| `retryable`      | `Callable[[Exception], bool] \| None` | `None`  | Predicate to filter retryable exceptions. `None` = all retryable. |
| `context`        | `str`                                 | `""`    | Label for log messages. |

| Output | Type | Description                              |
|--------|------|------------------------------------------|
| return | `T`  | Return value of `fn()` on first success. |

| Raises           | When                                                      |
|------------------|-----------------------------------------------------------|
| `RetryExhausted` | All `max_attempts` failed (only when `max_attempts > 1`). |
| original exception | `max_attempts == 1`, or exception not retryable.        |

### Delay formula

```
delay = min(base_delay * backoff_factor ^ attempt, max_delay) + uniform(0, jitter)
```

If the caught exception has a `retry_after` attribute (e.g. `RateLimitedError`), its value replaces the calculated delay (jitter still added).

### Logging

Each retry logs at WARNING: `"Attempt N/M failed [context] (error) — retrying in Xs."`

## Dependencies

stdlib `logging`, `random`, `time`, `typing`.
