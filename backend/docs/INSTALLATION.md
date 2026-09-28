# Installation

## Requirements

- Python **3.10+**. The spec said 3.8+, but the current `anthropic` SDK (1.x) requires 3.10. Tested on 3.11.
- Node 20+ for the candidate frontend (repo root).

## Backend

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit; see CONFIGURATION.md
pytest tests.py -q
uvicorn api_server:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Analytics dashboard: http://localhost:8000/admin

The spec listed pandas and numpy. They aren't needed, because analytics use SQL aggregates and the statistics are a few lines of standard-library code. That keeps the install small.

## Connect the candidate frontend

```bash
# repo root
echo "VITE_ASSESSMENT_API_URL=http://localhost:8000" > .env.local
npm install && npm run dev      # http://localhost:5173
```

When a candidate finishes, the completion page POSTs their answers to `/api/assess` once. It shows whether the server received them and offers a retry if it didn't. Without the variable, the frontend works offline as before. Make sure the frontend's origin is listed in `CORS_ORIGINS`.

## Enabling AI analysis

**From the dashboard (recommended).** Open `/admin` and enter the dashboard admin key. In **AI provider**, pick a provider (Anthropic, NVIDIA NIM, OpenAI, Google Gemini, Groq, Mistral, DeepSeek, Together, OpenRouter, Fireworks, xAI, Perplexity, Ollama or a custom OpenAI-compatible URL). Paste the API key, click **Fetch models**, choose one, and click **Save & test connection**.

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

1. Set `APP_ENV=production`. The server then refuses to start without the next two settings.
2. Set `RESPONSE_ENCRYPTION_KEY`, generated with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Store it in your secret manager: losing it makes stored answers unreadable.
3. Set `ADMIN_API_KEY` to a long random string.
4. Set `DATABASE_URL` to a managed Postgres database (`pip install "psycopg[binary]"`). SQLite is fine for a single instance at low volume.
5. Run with multiple workers behind HTTPS, e.g. `uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 4`. The LLM cache is shared through the database, so workers reuse each other's generations.
6. Replace the provisional scoring key and calibrate norms (see ARCHITECTURE.md) before scores inform decisions.
7. Back up the database and keep the encryption key separate from the backups.

`Base.metadata.create_all()` creates tables on startup. For schema changes after launch, add Alembic migrations.
