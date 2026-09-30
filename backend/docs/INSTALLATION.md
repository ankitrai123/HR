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
5. Set `DATABASE_URL` to a managed Postgres database (`pip install "psycopg[binary]"`). SQLite is fine for a single instance at low volume.
6. Run with multiple workers, e.g. `uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 4`. Sessions, invitations and the LLM cache live in the database, so any worker can serve any request. The login rate limiter is per worker, so put a reverse-proxy rate limit on `/api/auth/login` as well.
7. Replace the provisional scoring key and calibrate norms (see ARCHITECTURE.md) before scores inform decisions.
8. Back up the database, and keep the encryption key separate from the backups.

`Base.metadata.create_all()` creates tables on startup. For schema changes after launch, add Alembic migrations.
