# REST API

Interactive docs are at `http://localhost:8000/docs` when the server runs.

**Auth.** When `ADMIN_API_KEY` is set, every endpoint except `POST /api/assess`, `GET /health` and `GET /api/questions` requires the header `X-API-Key: <key>`. Without it you get `401`. The key is required in production.

**Ids.** `test_id` path parameters accept either an `assessment_id` (UUID) or a `test_taker_id`. A `test_taker_id` resolves to that candidate's latest assessment.

## POST /api/assess

Scores and stores a submission. Called by the candidate frontend.

```bash
curl -X POST localhost:8000/api/assess -H 'Content-Type: application/json' \
  -d @data/sample_responses.json
```

Request body:

| Field | Type | Notes |
|---|---|---|
| `test_taker_id` | string | required |
| `name` | string | required |
| `email` | string | optional |
| `responses` | object | `"<question id>": 1..scale_points`; missing or `null` = unanswered |
| `premium` | bool | default `false`; also generate the premium report |

Response `200` (abridged):

```json
{
  "test_id": "165943163",
  "assessment_id": "8f0c…",
  "name": "Ankit Kumar",
  "status": "Completed",
  "response_quality": "Genuine",
  "quality_flags": [],
  "questions_answered": 175,
  "norms": "provisional",
  "scoring_key": "provisional",
  "api_calls_made": 0,
  "completion_time_ms": 0.3,
  "scores": {
    "Ethical Propensity": {
      "category": "Personal", "sten_score": 5, "level": "Moderate", "percentile": 40.1,
      "raw_score": 4.18, "interpretation": "Somewhat likely to act in a trustworthy manner…"
    }
  },
  "strengths": ["Innovation"],
  "areas_of_development": ["Networking"],
  "profile_summary": "You show clear strengths in Innovation…"
}
```

`status` is `"Incomplete"` (with empty `scores`) when fewer than `MIN_ANSWERED` questions are answered. An unknown question id or out-of-range value returns `422`.

## GET /api/results/{test_id}  🔒

Returns the stored report, including `premium_features` if one was generated, plus `assessment_id` and `submitted_at`. Returns `404` if not found.

## POST /api/generate-premium-report  🔒

```json
{ "test_id": "8f0c…" }
```

Returns the full report with `premium_features`:

```json
"premium_features": {
  "executive_summary": "…",
  "development_plan": [{ "dimension": "Networking", "actions": ["…", "…", "…"] }],
  "coaching_insights": ["…"],
  "dimension_insights": { "Networking": "…" },
  "content_source": "llm",
  "api_calls_made": 1,
  "estimated_cost_usd": 0.0243,
  "generation_time_ms": 3100
}
```

`content_source` is `llm`, `fallback` (pre-written text; no key, or Claude unavailable) or `mixed`. The endpoint returns `409` if the assessment is incomplete.

## POST /api/export/{test_id}?format=pdf|json|text  🔒

Downloads the report as an attachment. The default is `pdf`.

## GET /api/analytics  🔒

Aggregates:

- **assessments:** totals, by status and quality, premium count, average scoring time
- **dimensions:** mean, min and max Sten and the level mix per dimension
- **sten_distribution**
- **llm_cache:** persistent entries and hits
- **engine:** API calls, failures, tokens, estimated cost, and in-memory cache hit rate since the server started
- **norms:** `provisional` or `calibrated`

The dashboard at `GET /admin` renders this data. It asks for the admin key and keeps it in `sessionStorage`.

## GET /api/norms/suggested?min_sample=30  🔒

Computes norms from stored genuine, completed assessments. Save the JSON to `data/norms.json` (or `NORMS_PATH`) and restart to use them. Returns `409` if there aren't enough assessments yet.

## GET /api/questions

Returns question ids, texts and `scale_points`. The scoring key is not exposed.

## GET /health

```json
{ "status": "ok", "llm_available": true, "norms": "provisional", "scoring_key": "provisional" }
```
