# Installation

## Requirements

- Python **3.10+**. The spec said 3.8+, but the current `anthropic` SDK (1.x) requires 3.10. Tested on 3.11.
- Node 20+ for the candidate frontend (repo root).

## Run the platform

The backend serves everything from one address: the admin console (`/admin`), employees' personal links (`/t/<token>`) and the API.

```bash
# 1. Build the web app (repo root)
npm install && npm run build

# 2. Install and start the backend
cd backend
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit; see CONFIGURATION.md
pytest tests.py -q
uvicorn api_server:app --port 8000
```

3. Open **http://localhost:8000/admin**. The first visit asks you to create the admin account. In production, either set `ADMIN_SETUP_TOKEN` and enter it on that screen, or create the account on the server with `python manage.py create-admin`.
4. Go to **Employees → Invite employees**, add one person or paste a list, and send each employee their link (**Copy link** or **Email**).
5. When an employee submits, their row shows **Completed** and **View report** opens the report. Employees only ever see a "submitted" confirmation.

API docs are at http://localhost:8000/docs.

### Developing the frontend

Run the backend as above, then `npm run dev` in the repo root and open http://localhost:5173/admin. Vite forwards `/api` to the backend, so sign-in cookies work the same as in production.

### Admin accounts from the command line

```bash
python manage.py create-admin          # prompts for email, name and password
python manage.py reset-password EMAIL  # forgotten password; signs that admin out everywhere
python manage.py list-admins
```

## Enabling AI analysis

**From the admin console (recommended).** Sign in at `/admin` and go to **Settings → AI provider**. There, pick a provider (Anthropic, NVIDIA NIM, OpenAI, Google Gemini, Groq, Mistral, DeepSeek, Together, OpenRouter, Fireworks, xAI, Perplexity, Ollama or a custom OpenAI-compatible URL). Paste the API key, click **Fetch models**, choose one, and click **Save & test connection**.

**From environment variables:** `ANTHROPIC_API_KEY` for Claude, or `LLM_PROVIDER` + `LLM_API_KEY` + `LLM_MODEL` for anything else. For example, NVIDIA NIM:

```bash
LLM_PROVIDER=nvidia LLM_API_KEY=nvapi-... LLM_MODEL=meta/llama-3.3-70b-instruct uvicorn api_server:app
```

Optionally pre-generate the 33 dimension insights so premium reports mostly cost one call:

```bash
python -c "from api_server import app; print(app.state.generator.warm_cache(), 'API calls')"
```

This writes to the database cache, so running servers and workers pick the text up too.

## Production checklist

1. Set `APP_ENV=production` and serve over HTTPS (session cookies are then marked `Secure`).
2. Set `RESPONSE_ENCRYPTION_KEY`, generated with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. It encrypts stored answers, employee link tokens and AI provider keys. Keep it in your secret manager: losing it makes that data unreadable.
3. Set `PUBLIC_BASE_URL` (e.g. `https://assess.example.com`) so employee links use your public address even behind a proxy.
4. Create the first admin with `python manage.py create-admin`, or set `ADMIN_SETUP_TOKEN` for browser setup.
5. Set `DATABASE_URL` to a managed Postgres database (the `psycopg` driver is in `requirements.txt`; `postgres://` and `postgresql://` URLs both work). SQLite is fine for a single instance at low volume.
6. Run with multiple workers, e.g. `uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 4`. Sessions, invitations and the LLM cache live in the database, so any worker can serve any request. The login rate limiter is per worker, so put a reverse-proxy rate limit on `/api/auth/login` as well.
7. Replace the provisional scoring key and calibrate norms (see ARCHITECTURE.md) before scores inform decisions.
8. Back up the database, and keep the encryption key separate from the backups.

`Base.metadata.create_all()` creates tables on startup. For schema changes after launch, add Alembic migrations.

## Deploy on Vercel

The repository is ready for Vercel: `vercel.json` builds the web app into `dist/` and serves it as static files, sends `/api/*` and `/health` to a Python function (`api/index.py`, which runs `backend/api_server.py`), and serves `index.html` for `/admin`, `/admin/*` and `/t/*`. The app and the API share one domain, so admin sign-in cookies work without CORS settings.

Vercel's filesystem is read-only and is reset between requests, so the app needs an external Postgres database and an encryption key from the environment. Without them every API call returns a 503 that names the missing variable. It never falls back to SQLite on Vercel.

### 1. Add a Postgres database

In the Vercel project, open **Storage**, choose **Create Database**, pick **Neon (Postgres)**, and connect it to the project for **Production** and **Preview**. This adds `DATABASE_URL` for you. If you use another Postgres provider, set `DATABASE_URL` yourself. Use the provider's pooled connection string when it has one (Neon's host contains `-pooler`). Both `postgres://` and `postgresql://` forms work, and the tables are created automatically on the first request.

### 2. Set environment variables

In **Settings, Environment Variables**, add:

| Variable | Value | Environments |
|---|---|---|
| `APP_ENV` | `production` | Production, Preview |
| `RESPONSE_ENCRYPTION_KEY` | Output of `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep a copy in a password manager: losing it makes stored answers, links and AI keys unreadable. | Production, Preview |
| `ADMIN_SETUP_TOKEN` | A long random string, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(24))"`. You type it once when creating the first admin. | Production, Preview |
| `DATABASE_URL` | Added by the Neon integration (step 1), otherwise your Postgres URL | Production, Preview |
| `PUBLIC_BASE_URL` | Your production address, e.g. `https://<your-project>.vercel.app` or your custom domain (no trailing slash). Used in employee links. | Production only, so preview links point at the preview |
| `ORGANIZATION_NAME` | Shown to employees and in reports, e.g. `Pasona` | Production, Preview |
| `SUPPORT_EMAIL` | Shown to employees for help | Production, Preview |
| `SUPPORT_PHONE` | Shown to employees for help | Production, Preview |
| `ANTHROPIC_API_KEY` *(optional)* | Enables AI analysis with Claude. You can instead paste a key under **Settings, AI provider** in the admin console. | Production, Preview |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` *(optional)* | Use another AI provider from the environment (see CONFIGURATION.md) | Production, Preview |

Preview and production share the database if both use the same `DATABASE_URL`. To keep test data out of production, use Neon's preview branching or a separate database for Preview.

### 3. Deploy and create the first admin

1. Redeploy (environment variables only apply to new deployments): **Deployments**, choose the latest one, then **Redeploy**.
2. Open `https://<your-domain>/health`. It should return `{"status":"ok", ...}`.
3. Open `https://<your-domain>/admin`, create the admin account, and enter `ADMIN_SETUP_TOKEN` when asked.

### Notes

- **Python version:** Vercel's default Python runtime (3.12) works. Vercel installs the packages in the root `requirements.txt`; `backend/requirements.txt` adds the local server and test tools.
- **Time limit:** the API function may run for up to 300 seconds (`maxDuration` in `vercel.json`), because an AI report makes up to 12 provider calls. This needs Fluid compute, which is on by default for new projects. If your project has it off and is on the Hobby plan, either turn it on (**Settings, Functions**) or lower `maxDuration` to 60.
- **Login rate limiting** is kept in memory per function instance, so it is weaker on Vercel than on a single server. Use strong admin passwords, and consider Vercel's firewall rate limiting on `/api/auth/login`.
- **Database connections:** on Vercel the app opens a connection per request instead of keeping a pool, which suits serverless functions and Neon's pooler.

