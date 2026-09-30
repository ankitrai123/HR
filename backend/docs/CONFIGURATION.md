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

The easiest way to choose a provider is the **AI provider** card in the admin dashboard (`/admin`). A provider saved there overrides the environment variables below. Removing it (**Disconnect**) reverts to them.

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `nvidia`, `openai`, `google`, `groq`, `mistral`, `deepseek`, `together`, `openrouter`, `fireworks`, `xai`, `perplexity`, `ollama` or `custom` |
| `ANTHROPIC_API_KEY` | – | Key when `LLM_PROVIDER=anthropic` |
| `LLM_API_KEY` | – | Key for any other provider (e.g. an `nvapi-…` key for NVIDIA NIM) |
| `LLM_BASE_URL` | – | Only for `ollama` / `custom` (e.g. `http://localhost:11434/v1`) |
| `LLM_COMPAT_MAX_TOKENS` | `4096` | Output ceiling for OpenAI-compatible providers |
| `LLM_ENABLED` | `true` | Kill switch |
| `LLM_MODEL` | `claude-opus-5` | Model id for the chosen provider (e.g. `meta/llama-3.3-70b-instruct` on NVIDIA NIM) |
| `LLM_EFFORT` | `medium` | Claude only: `low` / `medium` / `high` / `xhigh` / `max` (ignored for Haiku 4.5) |
| `LLM_MAX_TOKENS` | `16000` | Output ceiling per call |
| `LLM_TIMEOUT_SECONDS` | `60` | Per request; the SDK also retries twice |
| `LLM_USE_FALLBACKS` | `true` | Server-side refusal fallback on Opus 5 / Fable models (Claude API only; set `false` on Bedrock, Vertex or Foundry) |
| `LLM_PROMPT_VERSION` | `v1` | Bump to invalidate cached generations after changing prompts |
| `LLM_INPUT_PRICE_PER_MTOK` / `LLM_OUTPUT_PRICE_PER_MTOK` | `5` / `25` | Cost estimates for the environment-configured provider (the dashboard has its own optional price fields) |
| `LLM_CACHE_MAX_ENTRIES` | `5000` | In-memory LRU size (the database cache is unbounded) |

Model-specific behaviour is handled automatically: `effort` is omitted for Haiku 4.5 (which rejects it), and the server-side refusal fallback is only requested on the Opus 5 / Fable tier. Changing `LLM_MODEL` also changes the cache key, so earlier generations aren't reused across models.

## Security

| Variable | Default | Notes |
|---|---|---|
| `RESPONSE_ENCRYPTION_KEY` | – | Fernet key for answers at rest. Required in production; in development a key is generated at `data/.dev_encryption_key` |
| `ADMIN_SETUP_TOKEN` | – | Needed to create the first admin from the browser in production (or use `python manage.py create-admin`) |
| `ADMIN_API_KEY` | – | Optional. Lets scripts call admin endpoints with the `X-API-Key` header instead of signing in |

## Platform

| Variable | Default | Notes |
|---|---|---|
| `PUBLIC_BASE_URL` | the address the admin is using | Base of employee links, e.g. `https://assess.example.com` |
| `ORGANIZATION_NAME` | `Acme Corporation` | Shown to employees and in the admin console |
| `SUPPORT_EMAIL` / `SUPPORT_PHONE` | placeholders | Help contacts shown to employees |
| `INVITATION_DEFAULT_DAYS` | `14` | Default link validity (admins can choose 3–90 days per invite) |
| `TEST_DURATION_MINUTES` | `45` | Timer length; the server records the start time |
| `SUBMISSION_GRACE_MINUTES` | `5` | Submissions later than the timer plus this are accepted but flagged "late" |
| `FRONTEND_DIST` | `../dist` | Built web app served at `/`, `/admin` and `/t/<token>` |

## Security of provider keys

Keys pasted in the admin console are sent only to the admin API (signed-in admins only), stored Fernet-encrypted with `RESPONSE_ENCRYPTION_KEY`, and never returned by any endpoint. The dashboard only shows the last four characters. A saved key is only reused for the same provider and base URL, so it can't be redirected to another server. The `custom` and `ollama` options let an admin point the server at any URL, so only give admin accounts to people you trust with that.

## Accounts and sessions

- Passwords are hashed with scrypt, and must be at least 10 characters with mixed case and a number.
- Signing in creates a server-side session: an HttpOnly, `SameSite=Strict` cookie that expires after 12 hours of inactivity. Writes also require the per-session CSRF token that the admin app sends as `X-CSRF-Token`.
- Five failed sign-ins for the same email and address lock that combination out for 15 minutes.
- Changing a password signs out the admin's other sessions.
