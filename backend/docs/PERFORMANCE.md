# Performance

## Measured

`python benchmark.py` runs simulated candidates through the real engine with a stub LLM client. The numbers measure this service, not network or model latency. Measured on the development container (Python 3.11, one core):

| Metric | 1,000 candidates | 10,000 candidates | Target |
|---|---|---|---|
| Standard report p50 / p95 | 0.18 / 0.35 ms | similar | < 100 ms ✅ |
| Premium report, served from cache, p50 | 2.2 ms | similar | < 500 ms ✅ |
| Distinct level profiles | 751 | 3,691 | – |
| API calls per premium report | 0.78 | 0.37 | – |
| LLM cache hit rate | **93.5%** | **96.9%** | ≥ 80% ✅ |

The API adds roughly 5–10 ms per request (validation, encryption, database write); see `avg_scoring_time_ms` in `/api/analytics`.

**Not measured here:** fresh generation latency and real token counts, because they need a live API key. Expect a few seconds per fresh call. The up to 11 dimension calls for a new profile run in parallel, so a cold premium report costs about one or two round-trips. After `warm_cache()`, a new profile needs only the single narrative call. Check real figures with `example_usage.py` and `/api/analytics` once a key is configured.

## Why the hit rate is high

- **Dimension insights** are keyed only on (dimension, level), so there are at most **33** in total. They are paid for once (or up front with `warm_cache()`), then reused by every candidate.
- **Profile narratives** are keyed on the 11 levels. The number of distinct profiles grows much more slowly than the number of candidates, because most people cluster around Moderate. This is the only recurring cost.
- The cache lives in the database, so restarts and multiple workers share it. Concurrent requests for the same key are de-duplicated (single-flight).

## Cost model

This is an estimate: tokens per call are assumed (about 450 input and 900 output, including thinking at `medium` effort). Measure with a live key before budgeting.

| Model | $ / call | $ / report @ 1k | $ / report @ 10k | ~$ / month @ 10k reports |
|---|---|---|---|---|
| `claude-opus-5` (default) | 0.025 | 0.019 | 0.009 | ~95 |
| `claude-sonnet-5` | 0.010 | 0.008 | 0.004 | ~40 |
| `claude-haiku-4-5` | 0.005 | 0.004 | 0.002 | ~20 |

The spec's $0.001–0.01 per report is met at volume on every model, and from the start on Sonnet 5 or Haiku 4.5. Standard reports cost nothing.

## Tuning

- **Lower cost:** set `LLM_MODEL` to a cheaper model, or `LLM_EFFORT=low`. Check output quality on a sample first.
- **Pre-warm:** call `warm_cache()` after deploying or after changing the model or prompt version.
- **Coarser narrative keys:** keying narratives on strengths and development areas only (instead of all 11 levels) would raise reuse further, at the cost of less specific summaries.
- **Throughput:** scoring is CPU-bound and sub-millisecond, so one worker scores thousands of reports per second. Add workers for concurrency; SQLite becomes the bottleneck well before scoring does, so use Postgres for multi-worker deployments.
- **Bulk re-scoring** (e.g. after calibrating norms) doesn't need the LLM. Recompute from `results.proportion`, or decrypt the stored responses and re-run `standard_report`.
