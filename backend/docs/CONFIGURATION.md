# Configuration

Settings are read from environment variables. A `backend/.env` file is also loaded, but real environment variables take precedence. See `config.py`.

## General

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` enforces the security settings below |
| `DATABASE_URL` | `sqlite:///backend/data/assessments.db` | Any SQLAlchemy URL |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated frontend origins |

## Instrument & scoring

| Variable | Default | Notes |
|---|---|---|
| `QUESTION_BANK_PATH` | `data/question_bank.json` | Items, dimensions, reverse keys |
| `NORMS_PATH` | `data/norms.json` | Calibrated norms; provisional norms are used if the file is absent |
| `ASSESSMENT_SCALE_POINTS` | `6` | Likert points (the frontend uses 6; set 5 for a 1–5 instrument) |

## Response quality checks

| Variable | Default | Meaning |
|---|---|---|
| `MIN_ANSWERED` | `170` | Below this, the assessment is `Incomplete` and not scored |
| `MIN_DISTINCT_OPTIONS` | `3` | Flag if fewer distinct options are used |
| `MAX_MEAN_FRACTION` | `0.75` | Flag if the raw mean exceeds this fraction of the scale range (0.75 = 4.0 on 1–5) |
| `MAX_MIDDLE_FRACTION` | `0.50` | Flag if more than this share of answers are middle options |

## LLM (premium reports)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Unset: premium sections use the pre-written fallback |
| `LLM_ENABLED` | `true` | Kill switch |
| `LLM_MODEL` | `claude-opus-5` | e.g. `claude-sonnet-5` or `claude-haiku-4-5` for lower cost |
| `LLM_EFFORT` | `medium` | `low` / `medium` / `high` / `xhigh` / `max` (ignored for Haiku 4.5) |
| `LLM_MAX_TOKENS` | `16000` | Output ceiling per call |
| `LLM_TIMEOUT_SECONDS` | `60` | Per request; the SDK also retries twice |
| `LLM_USE_FALLBACKS` | `true` | Server-side refusal fallback on Opus 5 / Fable models (Claude API only; set `false` on Bedrock, Vertex or Foundry) |
| `LLM_PROMPT_VERSION` | `v1` | Bump to invalidate cached generations after changing prompts |
| `LLM_INPUT_PRICE_PER_MTOK` / `LLM_OUTPUT_PRICE_PER_MTOK` | `5` / `25` | Used only for cost estimates; update if you change model |
| `LLM_CACHE_MAX_ENTRIES` | `5000` | In-memory LRU size (the database cache is unbounded) |

Model-specific behaviour is handled automatically: `effort` is omitted for Haiku 4.5 (which rejects it), and the server-side refusal fallback is only requested on the Opus 5 / Fable tier. Changing `LLM_MODEL` also changes the cache key, so earlier generations aren't reused across models.

## Security

| Variable | Default | Notes |
|---|---|---|
| `RESPONSE_ENCRYPTION_KEY` | – | Fernet key for answers at rest. Required in production; in development a key is generated at `data/.dev_encryption_key` |
| `ADMIN_API_KEY` | – | Required header `X-API-Key` for results, exports, analytics and norms. Required in production |
