# Architecture

```
candidate frontend ──POST /api/assess──▶ api_server.py
                                          │
                     ┌────────────────────┴─────────────────────┐
                     ▼                                          ▼
          HybridReportGenerator                        database_models.py
   ┌─────────────────────────────────┐          (responses encrypted at rest,
   │ ResponseValidator  (4 checks)   │           results, reports, llm_cache)
   │ HybridScoringEngine (raw→Sten)  │
   │ INTERPRETATIONS (11 × 3)        │  ◀── standard report: no network, <1 ms
   ├─────────────────────────────────┤
   │ LLMInterpretationCache          │  ◀── premium report
   │   memory LRU → DB → Claude      │
   │ ClaudeInterpreter → fallback    │
   └─────────────────────────────────┘
```

## 1. Scoring pipeline (deterministic)

1. **Normalise.** Question ids are coerced to ints. Unknown ids, non-integers and out-of-range values are rejected with HTTP 422. Nulls count as unanswered.
2. **Validate** (`ResponseValidator`):

   | Check | Rule (default) | Effect when failed |
   |---|---|---|
   | Completeness | ≥ 170 of 175 answered | `status: "Incomplete"`, no scores |
   | Response variety | ≥ 3 distinct options used | `response_quality: "Questionable"` + flag |
   | Social desirability | raw mean ≤ 75% of the scale range (4.0 on 1–5, 4.75 on 1–6) | flag |
   | Central tendency | ≤ 50% of answers are middle options | flag |

   On an even (6-point) scale the "middle options" are the two innermost, *Somewhat Disagree* and *Somewhat Agree*. Those are real opinions, not a neutral answer, so review this threshold against pilot data (`MAX_MIDDLE_FRACTION`).
3. **Key.** Reverse-keyed items are flipped (`K + 1 − x`), so a higher keyed value always means more of the trait.
4. **Raw score.** A dimension's raw score is the mean keyed value of its answered items. It is rescaled to a 0–1 proportion, `(mean − 1) / (K − 1)`, so norms don't depend on the scale length.
5. **Sten.** `z = (proportion − norm_mean) / norm_sd`. `STEN_TABLE` bands are half an SD wide and centred on 5.5 (equivalent to `sten = ⌊2z + 5.5⌋`, clipped to 1–10). Percentile is `Φ(z)`.
6. **Level.** Sten 1–4 is Low, 5–6 is Moderate, 7–10 is High. Each dimension × level maps to one of 33 pre-written interpretations.
7. **Strengths / development areas** are the High / Low dimensions. `profile_summary` is templated from them.

### Provisional key and norms

- `data/question_bank.json` assigns each item to one dimension, with 11–22 items per dimension and reverse-keyed items in every dimension. The assignment is by item content, written for this project. It is **not** the publisher's key. To swap in a validated key, edit `KEY` in `data/build_question_bank.py` and re-run it.
- Norms default to a mean proportion of 0.62 (SD 0.13) for every dimension, a placeholder reflecting the usual positive skew of self-reports. Once ≥ 30 genuine assessments are stored, `GET /api/norms/suggested` returns per-dimension means and SDs. Save that JSON to `data/norms.json` and restart, and reports switch to `"norms": "calibrated"`. Larger samples (≥ 200 per comparison group) give more stable norms.

## 2. LLM layer (premium)

`ClaudeInterpreter` makes two kinds of call, both returning JSON constrained by a schema (`output_config.format`):

| Call | Input sent to Claude | Cache key | Distinct keys |
|---|---|---|---|
| Dimension insight | dimension, category, level, pre-written interpretation | `(dimension, level)` | 33 in total |
| Profile narrative | the 11 levels (no Sten numbers) | the level vector | grows with unique profiles |

**Privacy.** Names, emails, ids and raw answers are never sent. Only levels are sent (not exact Stens), so a cached narrative is correct for every candidate sharing that level vector.

**Cache.** `LLMInterpretationCache` checks an in-memory LRU first, then the `llm_cache` table (shared across restarts and workers), then calls Claude. A per-key lock gives single-flight behaviour: concurrent requests for the same key trigger one API call. Keys include the model and `LLM_PROMPT_VERSION`, so changing either invalidates old text. `generator.warm_cache()` pre-generates all 33 dimension insights.

**Fallback.** On a missing key, auth failure, rate limit, connection error, 5xx, refusal, truncation or invalid JSON, the report uses the pre-written interpretation and generic actions (`content_source: "fallback"` or `"mixed"`). Failed generations are never cached.

**Request shape.** The model is `claude-opus-5` by default (configurable). Effort defaults to `medium`. Thinking is left at the model default (adaptive). Server-side refusal fallback is enabled (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`; turn off with `LLM_USE_FALLBACKS=false` on platforms without it). The SDK retries 429s and 5xx twice before the app falls back.

## 3. Persistence

| Table | Contents |
|---|---|
| `test_takers` | external id, name, email |
| `assessments` | status, quality, flags, the standard report JSON, optional premium report JSON, timing |
| `responses` | Fernet-encrypted answers + SHA-256 digest (integrity, duplicate detection) |
| `results` | one row per dimension (raw, proportion, Sten, level, percentile) for analytics and norms |
| `llm_cache` | generated text keyed as above, with hit counts |

Raw answers are never logged, and never stored unencrypted. In production, `RESPONSE_ENCRYPTION_KEY` must be set. In development, a key is generated at `data/.dev_encryption_key` (gitignored).

## 4. Extending

- **New dimension:** add it to `DIMENSIONS` and `KEY` in `data/build_question_bank.py`, add three texts to `INTERPRETATIONS`, and re-run the builder. The test suite checks that every dimension has items and interpretations.
- **New interpretation wording:** edit `INTERPRETATIONS`. The LLM cache is unaffected, unless you also bump `LLM_PROMPT_VERSION` to regenerate.
- **Different scale:** set `ASSESSMENT_SCALE_POINTS`. Proportion-based norms and fractional quality thresholds adapt automatically.
