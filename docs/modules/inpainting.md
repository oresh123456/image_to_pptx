# inpainting

Client for the Replicate LaMa model. Erases masked text regions from slide images via inpainting.

## Public functions

### `resolve_version(model, token) -> str`

| Input   | Type  | Description                                   |
|---------|-------|-----------------------------------------------|
| `model` | `str` | Replicate model ID, e.g. `"allenhooo/lama"`.  |
| `token` | `str` | Replicate API token (Bearer auth).            |

| Output | Type  | Description                        |
|--------|-------|------------------------------------|
| return | `str` | Version ID (64-char hex hash).     |

| Raises         | When                                  |
|----------------|---------------------------------------|
| `RuntimeError` | Model lookup returns non-200 status.  |

Called once before the thread pool starts. Version ID is shared by all worker threads.

---

### `inpaint(version_id, image_bytes, image_mime, mask_bytes, token, ...) -> bytes`

| Input           | Type    | Default | Description                             |
|-----------------|---------|---------|-----------------------------------------|
| `version_id`    | `str`   | —       | LaMa version ID from `resolve_version()`. |
| `image_bytes`   | `bytes` | —       | Original slide image.                   |
| `image_mime`    | `str`   | —       | MIME type of image.                     |
| `mask_bytes`    | `bytes` | —       | PNG mask from `masking.build_mask()`.   |
| `token`         | `str`   | —       | Replicate API token.                    |
| `max_retries`   | `int`   | `6`     | Max 429 rate-limit retries.             |
| `poll_interval` | `float` | `1.0`   | Seconds between status polls.           |
| `max_poll_sec`  | `float` | `240.0` | Max total polling duration.             |

| Output | Type    | Description                      |
|--------|---------|----------------------------------|
| return | `bytes` | Inpainted result image (PNG).    |

| Raises           | When                                           |
|------------------|------------------------------------------------|
| `RuntimeError`   | Non-429 submit failure, prediction failed/canceled, poll timeout, download failure. |
| `RetryExhausted` | All 429 retries exhausted.                     |

### Retry behavior (submit phase)

- `max_retries + 1` attempts via `retry_call`.
- Only `RateLimitedError` (HTTP 429) is retryable. All other errors raise immediately.
- Uses server-directed `retry_after` from 429 response body + jitter.

### Polling phase (not retried)

- Polls status endpoint every `poll_interval` seconds.
- Succeeds on `"succeeded"` status.
- Raises `RuntimeError` on `"failed"` or `"canceled"`.
- Raises `RuntimeError` if elapsed time exceeds `max_poll_sec`.

## Rate limits

- Replicate free-tier allows ~6 predictions/minute. This is why `pipeline.py` defaults `max_concurrent=1`.
- Only `RateLimitedError` (HTTP 429) is retryable; server-directed `retry_after` is honored.

## Dependencies

`requests`, `retry` (retry_call, RateLimitedError), stdlib `base64`, `logging`, `time`.
