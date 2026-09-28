"""Unit and integration tests.  Run:  pytest tests.py -q

The Anthropic API is never called: LLM tests inject FakeClaude, which records
requests and returns canned structured output.
"""
from __future__ import annotations

import dataclasses
import json
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from config import load_settings, validate_api_key_format
from database_models import Database, DatabaseCacheStore, Response
from hybrid_assessment_engine import (INTERPRETATIONS, AssessmentInput, ClaudeInterpreter, HybridReportGenerator,
                                      HybridScoringEngine, LLMInterpretationCache, QuestionBank, ResponseValidator,
                                      level_for_sten, z_to_percentile, z_to_sten)

ROOT = Path(__file__).resolve().parent
FRONTEND_TEST_JSON = ROOT.parent / "src" / "data" / "test.json"


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path):
    base = load_settings()
    return dataclasses.replace(
        base, environment="test", database_url=f"sqlite:///{tmp_path / 'test.db'}",
        dev_key_path=tmp_path / "key", norms_path=tmp_path / "no-norms.json",
        anthropic_api_key=None, admin_api_key=None, response_encryption_key=None,
    )


@pytest.fixture
def bank(cfg):
    return QuestionBank.load(cfg.question_bank_path)


class FakeClaude:
    """Stands in for anthropic.Anthropic(); only beta.messages.create is used."""

    def __init__(self, fail_with: Exception | None = None, stop_reason: str = "end_turn", delay: float = 0.0):
        self.calls: list[dict] = []
        self.fail_with = fail_with
        self.stop_reason = stop_reason
        self.delay = delay
        self._lock = threading.Lock()
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        if self.fail_with:
            raise self.fail_with
        schema = kwargs["output_config"]["format"]["schema"]
        if "executive_summary" in schema["properties"]:
            payload = {"executive_summary": "LLM summary.", "coaching_insights": ["LLM insight A", "LLM insight B"]}
        else:
            payload = {"interpretation": "LLM interpretation.", "development_actions": ["a1", "a2", "a3"],
                       "coaching_insight": "LLM coaching."}
        text = json.dumps(payload) if self.stop_reason == "end_turn" else ""
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=text)] if text else [],
            usage=SimpleNamespace(input_tokens=400, output_tokens=300),
        )


def make_generator(cfg, client=None, cache=None) -> HybridReportGenerator:
    return HybridReportGenerator(cfg=cfg, interpreter=ClaudeInterpreter(cfg, client=client), cache=cache)


def random_responses(seed: int, scale: int = 6, n: int = 175) -> dict[int, int]:
    rng = random.Random(seed)
    # A plausible genuine respondent on a 6-point scale: uses every option,
    # leans towards agreement (mean ~4.1) and sits in the middle two
    # options well under half the time.
    weights = [0.06, 0.10, 0.17, 0.22, 0.27, 0.18]
    assert scale == len(weights)
    return {i: rng.choices(range(1, scale + 1), weights)[0] for i in range(1, n + 1)}


def candidate(seed: int, **overrides) -> AssessmentInput:
    base = AssessmentInput(f"cand-{seed}", f"Candidate {seed}", f"c{seed}@example.com", random_responses(seed))
    return dataclasses.replace(base, **overrides)


def api_client(cfg, generator=None) -> TestClient:
    from api_server import create_app

    db = Database(cfg)
    return TestClient(create_app(cfg, db=db, generator=generator or make_generator(cfg)))


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


def test_question_bank_covers_all_items_and_dimensions(bank):
    assert len(bank) == 175
    assert len(bank.dimension_names) == 11
    assert set(INTERPRETATIONS) == set(bank.dimension_names)
    for dim in bank.dimension_names:
        items = bank.items_for(dim)
        assert len(items) >= 10, f"{dim} has too few items for a reliable score"
        assert any(it.reverse_keyed for it in items), f"{dim} has no reverse-keyed items"


@pytest.mark.skipif(not FRONTEND_TEST_JSON.exists(), reason="frontend not present")
def test_question_bank_matches_frontend_questions(bank):
    test = json.loads(FRONTEND_TEST_JSON.read_text(encoding="utf-8"))
    frontend = {q["id"]: q["questionText"] for s in test["sections"] for q in s["questions"]}
    assert frontend == {i: it.text for i, it in bank.items.items()}
    options = test["sections"][0]["questions"][0]["options"]
    assert len(options) == load_settings().scale_points


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_sten_normalization():
    # Band edges: sten bands are half an SD wide, centred on 5.5.
    assert z_to_sten(-3.0) == 1
    assert z_to_sten(-2.0) == 2
    assert z_to_sten(-0.01) == 5
    assert z_to_sten(0.0) == 6
    assert z_to_sten(1.99) == 9
    assert z_to_sten(2.0) == 10
    assert z_to_sten(5.0) == 10
    stens = [z_to_sten(z / 100) for z in range(-300, 301)]
    assert stens == sorted(stens), "sten must be monotonic in z"
    assert [level_for_sten(s) for s in range(1, 11)] == ["Low"] * 4 + ["Moderate"] * 2 + ["High"] * 4
    assert z_to_percentile(0.0) == 50.0
    assert z_to_percentile(1.0) == pytest.approx(84.1, abs=0.1)
    assert z_to_percentile(-1.0) == pytest.approx(15.9, abs=0.1)


def test_raw_score_calculation(cfg, bank):
    engine = HybridScoringEngine(bank, cfg, norms={})
    # Everyone answers "Strongly Agree" (6): normal items key to 6, reverse items to 1.
    scores = engine.score({i: 6 for i in bank.items})
    for dim, s in scores.items():
        items = bank.items_for(dim)
        expected = sum(1 if it.reverse_keyed else 6 for it in items) / len(items)
        assert s.raw_score == pytest.approx(expected, abs=1e-3)
        assert s.proportion == pytest.approx((expected - 1) / 5, abs=1e-3)
        assert s.items_answered == len(items)


def test_scores_use_norms(cfg, bank):
    all_mid = {i: 4 for i in bank.items}
    dim = bank.dimension_names[0]
    prop = HybridScoringEngine(bank, cfg, norms={}).score(all_mid)[dim].proportion
    # A norm centred just below this candidate puts them at z ~ +0.01 -> sten 6, ~50th percentile.
    engine = HybridScoringEngine(bank, cfg, norms={dim: {"mean": prop - 0.001, "sd": 0.1}})
    s = engine.score(all_mid)[dim]
    assert s.sten_score == 6 and s.percentile == pytest.approx(50.0, abs=1.0)
    assert engine.norms_status == "calibrated"


def test_compute_norms(cfg, bank):
    engine = HybridScoringEngine(bank, cfg, norms={})
    rows = [{d: s.proportion for d, s in engine.score(random_responses(i)).items()} for i in range(40)]
    norms = HybridScoringEngine.compute_norms(rows, min_sample=30)
    first = bank.dimension_names[0]
    vals = [r[first] for r in rows]
    assert norms["dimensions"][first]["mean"] == pytest.approx(statistics.mean(vals), abs=1e-4)
    assert norms["dimensions"][first]["sd"] == pytest.approx(statistics.stdev(vals), abs=1e-4)
    with pytest.raises(ValueError):
        HybridScoringEngine.compute_norms(rows[:5], min_sample=30)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_response_validation(cfg, bank):
    v = ResponseValidator(bank, cfg)

    genuine = v.validate(random_responses(1))
    assert genuine.complete and genuine.quality == "Genuine" and genuine.flags == []

    incomplete = v.validate({i: 3 for i in range(1, 101)})
    assert not incomplete.complete
    assert any("Only 100 of 175" in f for f in incomplete.flags)

    rng = random.Random(0)
    two_options = v.validate({i: rng.choice([2, 5]) for i in bank.items})
    assert [c.name for c in two_options.checks if not c.passed] == ["response_variety"]

    all_agree = v.validate({i: {0: 4, 1: 5}.get(i % 10, 6) for i in bank.items})
    assert [c.name for c in all_agree.checks if not c.passed] == ["social_desirability"]

    fence_sitter = v.validate({i: [3, 4, 3, 4, 1, 6][i % 6] for i in bank.items})
    assert [c.name for c in fence_sitter.checks if not c.passed] == ["central_tendency"]


def test_middle_options_depend_on_scale(cfg, bank):
    assert ResponseValidator(bank, cfg).middle_options() == {3, 4}
    five = dataclasses.replace(cfg, scale_points=5)
    assert ResponseValidator(bank, five).middle_options() == {3}
    # Social-desirability ceiling of 0.75 == 4.0 on a 1-5 scale, as specified.
    assert 1 + five.max_mean_fraction * (5 - 1) == 4.0


@pytest.mark.parametrize("responses", [{"999": 3}, {"1": 7}, {"1": 0}, {"x": 3}, {"1": "3"}, {"1": True}])
def test_invalid_responses_rejected(cfg, bank, responses):
    with pytest.raises(ValueError):
        ResponseValidator(bank, cfg).normalise(responses)


def test_incomplete_assessment_is_not_scored(cfg):
    gen = make_generator(cfg)
    report = gen.standard_report(candidate(1, responses={i: 4 for i in range(1, 50)}))
    assert report["status"] == "Incomplete"
    assert report["scores"] == {} and report["api_calls_made"] == 0


# ---------------------------------------------------------------------------
# Config / API key
# ---------------------------------------------------------------------------


def test_api_key_validation(cfg):
    assert validate_api_key_format("sk-ant-api03-" + "x" * 40)
    assert not validate_api_key_format("sk-proj-" + "x" * 40)
    assert not validate_api_key_format("sk-ant-short")
    assert not validate_api_key_format(" sk-ant-api03-" + "x" * 40)

    assert any("ANTHROPIC_API_KEY" in p for p in dataclasses.replace(cfg, anthropic_api_key="nope").validate())
    assert dataclasses.replace(cfg, anthropic_api_key="sk-ant-api03-" + "x" * 40).validate() == []
    assert not cfg.llm_available  # no key -> premium features use fallbacks, never crash

    prod = dataclasses.replace(cfg, environment="production")
    problems = prod.validate()
    assert any("RESPONSE_ENCRYPTION_KEY" in p for p in problems)
    assert any("ADMIN_API_KEY" in p for p in problems)


# ---------------------------------------------------------------------------
# LLM layer
# ---------------------------------------------------------------------------


def test_llm_interpretation_generation(cfg):
    fake = FakeClaude()
    gen = make_generator(cfg, client=fake)
    data = candidate(7)
    report = gen.premium_report(data)

    premium = report["premium_features"]
    assert premium["content_source"] == "llm"
    assert premium["executive_summary"] == "LLM summary."
    assert premium["api_calls_made"] == len(fake.calls) == 12  # 11 dimensions + 1 profile
    assert premium["estimated_cost_usd"] > 0
    assert set(premium["dimension_insights"]) == set(report["scores"])
    assert premium["development_plan"] and all(p["actions"] == ["a1", "a2", "a3"] for p in premium["development_plan"])

    call = fake.calls[0]
    assert call["model"] == cfg.llm_model
    assert call["output_config"]["effort"] == cfg.llm_effort
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and call["betas"] == [ClaudeInterpreter.FALLBACK_BETA]
    assert "thinking" not in call and "temperature" not in call

    # Cheaper models: Haiku gets no effort param; non-Opus-5 models get no server fallback.
    haiku = FakeClaude()
    make_generator(dataclasses.replace(cfg, llm_model="claude-haiku-4-5"), client=haiku).premium_report(data)
    assert "effort" not in haiku.calls[0]["output_config"] and "fallbacks" not in haiku.calls[0]
    sonnet = FakeClaude()
    make_generator(dataclasses.replace(cfg, llm_model="claude-sonnet-5"), client=sonnet).premium_report(data)
    assert sonnet.calls[0]["output_config"]["effort"] == cfg.llm_effort and "fallbacks" not in sonnet.calls[0]

    # Privacy: no candidate identifiers or raw answers are sent to the API.
    sent = json.dumps([c["messages"] for c in fake.calls]) + json.dumps([c["system"] for c in fake.calls])
    for secret in (data.name, data.email, data.test_taker_id):
        assert secret not in sent


def test_fallback_mechanism(cfg):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    for failure in (anthropic.APIConnectionError(request=request),
                    anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None),
                    RuntimeError("unexpected")):
        gen = make_generator(cfg, client=FakeClaude(fail_with=failure))
        report = gen.premium_report(candidate(3))
        premium = report["premium_features"]
        assert premium["content_source"] == "fallback"
        assert premium["executive_summary"] == report["profile_summary"]
        assert all(premium["dimension_insights"][d] == INTERPRETATIONS[d][s["level"]]
                   for d, s in report["scores"].items())

    # No API key at all: fallback without attempting a call.
    gen = make_generator(cfg)
    report = gen.premium_report(candidate(3))
    assert report["premium_features"]["content_source"] == "fallback"
    assert report["premium_features"]["api_calls_made"] == 0


def test_refusal_and_truncation_fall_back(cfg):
    for stop_reason in ("refusal", "max_tokens"):
        fake = FakeClaude(stop_reason=stop_reason)
        report = make_generator(cfg, client=fake).premium_report(candidate(4))
        assert report["premium_features"]["content_source"] == "fallback"
        assert fake.calls  # attempted, then fell back


def test_failed_generations_are_not_cached(cfg):
    fake = FakeClaude(fail_with=anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")))
    gen = make_generator(cfg, client=fake)
    gen.premium_report(candidate(5))
    fake.fail_with = None
    report = gen.premium_report(candidate(5))
    assert report["premium_features"]["content_source"] == "llm"


def test_cache_efficiency(cfg):
    fake = FakeClaude()
    gen = make_generator(cfg, client=fake)
    reports = [gen.premium_report(candidate(i)) for i in range(50)]

    stats = gen.cache.stats()
    assert stats["hit_rate"] >= 0.8, stats
    # Dimension insights are keyed on (dimension, level): at most 33 ever.
    dimension_calls = [c for c in fake.calls if "executive_summary" not in c["output_config"]["format"]["schema"]["properties"]]
    assert len(dimension_calls) <= 33
    assert sum(r["api_calls_made"] for r in reports) == len(fake.calls)

    # A candidate with an identical level profile costs nothing.
    repeat = gen.premium_report(candidate(0))
    assert repeat["premium_features"]["api_calls_made"] == 0


def test_warm_cache_then_zero_dimension_calls(cfg):
    fake = FakeClaude()
    gen = make_generator(cfg, client=fake)
    assert gen.warm_cache() == 33
    assert gen.warm_cache() == 0
    report = gen.premium_report(candidate(11))
    assert report["premium_features"]["api_calls_made"] == 1  # just the profile narrative


def test_cache_single_flight_under_concurrency():
    cache = LLMInterpretationCache()
    calls = []

    def factory():
        calls.append(1)
        time.sleep(0.05)
        return {"v": 1}

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: cache.get_or_create("k", "dimension", "m", factory), range(8)))
    assert len(calls) == 1
    assert all(v == {"v": 1} for v, _ in results)
    assert cache.stats()["hits"] == 7


def test_cache_lru_eviction():
    cache = LLMInterpretationCache(max_entries=2)
    for key in ("a", "b", "c"):
        cache.get_or_create(key, "dimension", "m", lambda k=key: {"k": k})
    assert cache.stats()["entries_in_memory"] == 2
    _, cached = cache.get_or_create("a", "dimension", "m", lambda: {"k": "a2"})
    assert not cached  # "a" was evicted


def test_persistent_cache_survives_restart(cfg):
    db = Database(cfg)
    db.create_all()
    fake = FakeClaude()
    first = make_generator(cfg, client=fake, cache=LLMInterpretationCache(store=DatabaseCacheStore(db)))
    first.premium_report(candidate(21))
    calls_after_first = len(fake.calls)

    second = make_generator(cfg, client=fake, cache=LLMInterpretationCache(store=DatabaseCacheStore(db)))
    report = second.premium_report(candidate(21))
    assert len(fake.calls) == calls_after_first
    assert report["premium_features"]["api_calls_made"] == 0


# ---------------------------------------------------------------------------
# Persistence & API
# ---------------------------------------------------------------------------


def assess_body(seed: int, **extra) -> dict:
    return {"test_taker_id": f"cand-{seed}", "name": f"Candidate {seed}", "email": f"c{seed}@example.com",
            "responses": {str(k): v for k, v in random_responses(seed).items()}, **extra}


def test_end_to_end_assessment(cfg):
    fake = FakeClaude()
    client = api_client(cfg, make_generator(cfg, client=fake))

    res = client.post("/api/assess", json=assess_body(1))
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["status"] == "Completed" and report["api_calls_made"] == 0
    assert len(report["scores"]) == 11 and "_proportions" not in report
    for s in report["scores"].values():
        assert set(s) >= {"sten_score", "level", "percentile", "interpretation"}
    aid = report["assessment_id"]

    assert client.get(f"/api/results/{aid}").json()["assessment_id"] == aid
    assert client.get("/api/results/cand-1").json()["assessment_id"] == aid  # lookup by test-taker id
    assert client.get("/api/results/nope").status_code == 404

    premium = client.post("/api/generate-premium-report", json={"test_id": aid}).json()
    assert premium["premium_features"]["content_source"] == "llm"
    assert "premium_features" in client.get(f"/api/results/{aid}").json()

    pdf = client.post(f"/api/export/{aid}?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "Executive summary" not in pdf.text  # binary PDF, content compressed
    text = client.post(f"/api/export/{aid}?format=text").text
    assert "EXECUTIVE SUMMARY" in text and "Candidate 1" in text
    exported = client.post(f"/api/export/{aid}?format=json").json()
    assert exported["assessment_id"] == aid

    analytics = client.get("/api/analytics").json()
    assert analytics["assessments"]["total"] == 1
    assert analytics["assessments"]["premium_reports"] == 1
    assert len(analytics["dimensions"]) == 11
    assert client.get("/admin").status_code == 200


def test_assess_with_premium_flag_and_validation_errors(cfg):
    client = api_client(cfg, make_generator(cfg, client=FakeClaude()))
    res = client.post("/api/assess", json=assess_body(2, premium=True))
    assert res.json()["premium_features"]["api_calls_made"] == 12

    bad = assess_body(3)
    bad["responses"]["1"] = 9
    assert client.post("/api/assess", json=bad).status_code == 422
    bad["responses"] = {"500": 3}
    assert client.post("/api/assess", json=bad).status_code == 422


def test_admin_endpoints_require_api_key(cfg):
    locked = dataclasses.replace(cfg, admin_api_key="admin-secret")
    client = api_client(locked)
    aid = client.post("/api/assess", json=assess_body(4)).json()["assessment_id"]  # candidates don't need a key
    assert client.get(f"/api/results/{aid}").status_code == 401
    assert client.get("/api/analytics", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/analytics", headers={"X-API-Key": "admin-secret"}).status_code == 200


def test_responses_encrypted_at_rest(cfg):
    client = api_client(cfg)
    body = assess_body(5)
    aid = client.post("/api/assess", json=body).json()["assessment_id"]

    db = client.app.state.db
    with db.session() as s:
        stored = s.query(Response).filter_by(assessment_id=aid).one()
        ciphertext, digest = stored.ciphertext, stored.sha256
    assert b'"1":' not in ciphertext and b"cand-5" not in ciphertext
    decrypted = db.get_responses(aid)
    assert decrypted == {int(k): v for k, v in body["responses"].items()}
    assert digest == db.cipher.digest(decrypted)


def test_concurrent_assessments(cfg):
    fake = FakeClaude(delay=0.01)
    gen = make_generator(cfg, client=fake)
    with ThreadPoolExecutor(8) as pool:
        reports = list(pool.map(lambda i: gen.premium_report(candidate(i % 5)), range(40)))
    assert all(r["premium_features"]["content_source"] == "llm" for r in reports)
    # Only 5 distinct candidates: concurrent duplicates must not trigger duplicate calls.
    distinct_keys = gen.cache.stats()["misses"]
    assert len(fake.calls) == distinct_keys

    client = api_client(cfg)
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda i: client.post("/api/assess", json=assess_body(100 + i)).status_code, range(24)))
    assert codes == [200] * 24
    assert client.get("/api/analytics").json()["assessments"]["total"] == 24


def test_performance_metrics(cfg):
    gen = make_generator(cfg, client=FakeClaude())
    data = [candidate(i) for i in range(200)]
    start = time.perf_counter()
    for d in data:
        gen.standard_report(d)
    per_report_ms = (time.perf_counter() - start) * 1000 / len(data)
    assert per_report_ms < 100, per_report_ms

    gen.premium_report(data[0])  # fill cache
    start = time.perf_counter()
    report = gen.premium_report(data[0])
    assert (time.perf_counter() - start) * 1000 < 500
    assert report["premium_features"]["api_calls_made"] == 0
