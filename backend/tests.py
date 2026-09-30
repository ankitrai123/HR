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
from llm_providers import AnthropicProvider
from hybrid_assessment_engine import (INTERPRETATIONS, AssessmentInput, ClaudeInterpreter, HybridReportGenerator, LLMInterpreter,
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


ADMIN_EMAIL, ADMIN_PASSWORD = "admin@example.com", "Correct-Horse-9"


def api_client(cfg, generator=None, login: bool = True) -> TestClient:
    """A TestClient signed in as an admin (session cookie + CSRF header)."""
    from api_server import create_app

    db = Database(cfg)
    client = TestClient(create_app(cfg, db=db, generator=generator or make_generator(cfg)))
    if login:
        res = client.post("/api/auth/setup", json={"name": "Admin", "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert res.status_code == 200, res.text
        client.headers["X-CSRF-Token"] = res.json()["csrf_token"]
    return client


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
    assert not any("ADMIN_API_KEY" in p for p in problems)  # optional now: people sign in with accounts
    assert any("https" in p for p in dataclasses.replace(prod, public_base_url="http://x").validate())


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
    assert call["fallbacks"] == "default" and call["betas"] == [AnthropicProvider.FALLBACK_BETA]
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


def test_admin_endpoints_require_sign_in_or_api_key(cfg):
    locked = dataclasses.replace(cfg, admin_api_key="admin-secret")
    client = api_client(locked, login=False)
    for method, path in (("get", "/api/analytics"), ("get", "/api/results/x"), ("post", "/api/assess"),
                         ("get", "/api/admin/invitations"), ("get", "/api/admin/llm")):
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/api/analytics", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/analytics", headers={"X-API-Key": "admin-secret"}).status_code == 200
    # Scripts can still score directly with the API key.
    res = client.post("/api/assess", json=assess_body(4), headers={"X-API-Key": "admin-secret"})
    assert res.status_code == 200 and res.json()["status"] == "Completed"


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


# ---------------------------------------------------------------------------
# Multi-provider LLM support (NVIDIA NIM, OpenAI, Gemini, ... + dashboard config)
# ---------------------------------------------------------------------------

import llm_providers  # noqa: E402
from llm_providers import (LLMUnavailable, OpenAICompatibleProvider, PROVIDERS, build_provider,  # noqa: E402
                           extract_json, validate_schema)


class MockCompatServer:
    """An OpenAI-compatible endpoint (behaves like NVIDIA NIM) on httpx.MockTransport."""

    def __init__(self, valid_key: str = "nvapi-good-key-1234", json_mode: bool = True, fence: bool = True):
        self.valid_key, self.json_mode, self.fence = valid_key, json_mode, fence
        self.requests: list[httpx.Request] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("Authorization") != f"Bearer {self.valid_key}":
            return httpx.Response(401, json={"error": {"message": "Invalid API key"}})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": "meta/llama-3.3-70b-instruct"},
                                                                          {"id": "nvidia/nemotron-4-340b"}]})
        body = json.loads(request.content)
        if "response_format" in body and not self.json_mode:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        system = body["messages"][0]["content"]  # dispatch on the schema's property names
        if '"ok": {' in system:
            payload = {"ok": True}
        elif '"executive_summary": {' in system:
            payload = {"executive_summary": "NIM summary.", "coaching_insights": ["NIM insight"]}
        elif '"observations": {' in system:
            payload = {"summary": "NIM cohort summary.", "observations": ["o1"], "recommendations": ["r1"]}
        else:
            payload = {"interpretation": "NIM interpretation.", "development_actions": ["n1", "n2", "n3"],
                       "coaching_insight": "NIM coaching."}
        text = json.dumps(payload)
        if self.fence:  # many open models wrap JSON in fences and/or emit reasoning first
            text = f"<think>planning the answer</think>\n```json\n{text}\n```"
        return httpx.Response(200, json={
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 210, "completion_tokens": 90},
        })


def test_extract_json_and_schema_validation():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('<think>hmm {"no": 1}</think> Sure! {"a": [1]} hope that helps') == {"a": [1]}
    with pytest.raises(LLMUnavailable):
        extract_json("no json here")
    schema = {"type": "object", "properties": {"s": {"type": "string"}, "l": {"type": "array", "items": {"type": "string"}}},
              "required": ["s", "l"]}
    assert validate_schema({"s": "x", "l": ["y"], "extra": 1}, schema) == {"s": "x", "l": ["y"]}
    for bad in ({"s": "x"}, {"s": 1, "l": []}, {"s": "x", "l": [1]}):
        with pytest.raises(LLMUnavailable):
            validate_schema(bad, schema)


def test_provider_catalog_includes_nvidia_and_major_providers():
    for pid in ("anthropic", "nvidia", "openai", "google", "groq", "mistral", "deepseek", "openrouter", "ollama", "custom"):
        assert pid in PROVIDERS
    assert PROVIDERS["nvidia"].base_url == "https://integrate.api.nvidia.com/v1"


def test_openai_compatible_provider_request_and_parsing(cfg):
    server = MockCompatServer()
    nim = build_provider(cfg, "nvidia", "nvapi-good-key-1234", "meta/llama-3.3-70b-instruct", http_client=server.client)
    gen = HybridReportGenerator(cfg=cfg, interpreter=LLMInterpreter(cfg, provider=nim))
    data = candidate(9)
    report = gen.premium_report(data)

    pf = report["premium_features"]
    assert pf["content_source"] == "llm" and pf["executive_summary"] == "NIM summary."
    assert pf["generated_by"]["provider"] == "nvidia" and pf["generated_by"]["model"] == "meta/llama-3.3-70b-instruct"
    assert gen.interpreter.usage.input_tokens == 210 * pf["api_calls_made"]

    req = server.requests[0]
    assert str(req.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
    body = server.bodies()[0]
    assert body["model"] == "meta/llama-3.3-70b-instruct"
    assert body["response_format"] == {"type": "json_object"} and body["max_tokens"] == cfg.llm_compat_max_tokens
    sent = json.dumps(server.bodies())
    for secret in (data.name, data.email, data.test_taker_id):
        assert secret not in sent

    # OpenAI uses max_completion_tokens.
    oa = MockCompatServer(valid_key="sk-openai-key-5678")
    build_provider(cfg, "openai", "sk-openai-key-5678", "some-model", http_client=oa.client).generate_json(
        "s", "p", {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})
    assert "max_completion_tokens" in oa.bodies()[0] and "max_tokens" not in oa.bodies()[0]


def test_openai_compatible_retries_without_json_mode(cfg):
    server = MockCompatServer(json_mode=False)
    p = build_provider(cfg, "groq", "nvapi-good-key-1234", "m", http_client=server.client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    assert p.generate_json("reply ok", "go", schema).data == {"ok": True}
    assert len(server.bodies()) == 2 and "response_format" not in server.bodies()[1]
    p.generate_json("reply ok", "go", schema)
    assert len(server.bodies()) == 3  # remembers that JSON mode is unsupported


def test_openai_compatible_errors_fall_back(cfg):
    server = MockCompatServer()
    bad_key = build_provider(cfg, "nvidia", "nvapi-wrong", "m", http_client=server.client)
    with pytest.raises(LLMUnavailable, match="rejected the API key"):
        bad_key.generate_json("s", "p", {"type": "object", "properties": {}, "required": []})
    gen = HybridReportGenerator(cfg=cfg, interpreter=LLMInterpreter(cfg, provider=bad_key))
    assert gen.premium_report(candidate(1))["premium_features"]["content_source"] == "fallback"

    with pytest.raises(ValueError):
        build_provider(cfg, "nvidia", None, "m")  # key required
    with pytest.raises(ValueError):
        build_provider(cfg, "custom", None, "m", base_url="ftp://x")
    assert build_provider(cfg, "ollama", None, "llama3.1").base_url == "http://localhost:11434/v1"


def test_cache_is_separated_by_provider(cfg):
    fake, server = FakeClaude(), MockCompatServer()
    cache = LLMInterpretationCache()
    claude_gen = make_generator(cfg, client=fake, cache=cache)
    claude_gen.premium_report(candidate(2))
    nim = build_provider(cfg, "nvidia", "nvapi-good-key-1234", "meta/llama-3.3-70b-instruct", http_client=server.client)
    nim_gen = HybridReportGenerator(cfg=cfg, interpreter=LLMInterpreter(cfg, provider=nim), cache=cache)
    report = nim_gen.premium_report(candidate(2))
    assert report["premium_features"]["executive_summary"] == "NIM summary."  # not Claude's cached text


@pytest.fixture
def nim_server(monkeypatch):
    """Route every provider the API builds through the mock server."""
    import api_server

    server = MockCompatServer()
    real = llm_providers.build_provider
    monkeypatch.setattr(api_server, "build_provider",
                        lambda *a, **k: real(*a, **{**k, "http_client": server.client}))
    return server


def test_dashboard_llm_configuration_flow(cfg, nim_server):
    locked = dataclasses.replace(cfg, admin_api_key="admin-secret")
    client = api_client(locked, login=False)
    h = {"X-API-Key": "admin-secret"}

    assert client.get("/api/admin/llm").status_code == 401
    info = client.get("/api/admin/llm", headers=h).json()
    assert info["current"]["available"] is False
    assert any(p["id"] == "nvidia" and p["label"] == "NVIDIA NIM" for p in info["providers"])

    models = client.post("/api/admin/llm/models", headers=h,
                         json={"provider": "nvidia", "api_key": "nvapi-good-key-1234"}).json()
    assert "meta/llama-3.3-70b-instruct" in models["models"]

    bad = client.put("/api/admin/llm", headers=h, json={"provider": "nvidia", "model": "m", "api_key": "nvapi-wrong"})
    assert bad.status_code == 400 and "Connection test failed" in bad.json()["detail"]
    assert client.get("/api/admin/llm", headers=h).json()["current"]["available"] is False  # not saved

    ok = client.put("/api/admin/llm", headers=h, json={
        "provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "api_key": "nvapi-good-key-1234",
        "input_price_per_mtok": 0.5, "output_price_per_mtok": 1.5})
    assert ok.status_code == 200, ok.text
    current = ok.json()["current"]
    assert current["provider"] == "nvidia" and current["source"] == "dashboard" and current["key_hint"] == "…1234"
    assert "nvapi-good-key-1234" not in client.get("/api/admin/llm", headers=h).text  # never echoed

    # The key is encrypted at rest.
    from database_models import LLMSettings
    with client.app.state.db.session() as s:
        assert b"nvapi-good-key-1234" not in s.get(LLMSettings, 1).api_key_ciphertext

    # Saving without re-pasting the key reuses the stored one (same endpoint).
    again = client.put("/api/admin/llm", headers=h, json={"provider": "nvidia", "model": "nvidia/nemotron-4-340b"})
    assert again.status_code == 200 and again.json()["current"]["model"] == "nvidia/nemotron-4-340b"
    # ...but not for a different endpoint.
    moved = client.put("/api/admin/llm", headers=h, json={"provider": "custom", "model": "x",
                                                          "base_url": "https://attacker.example/v1"})
    assert moved.status_code == 400  # no key sent -> mock rejects it

    aid = client.post("/api/assess", headers=h, json=assess_body(30)).json()["assessment_id"]
    premium = client.post("/api/generate-premium-report", headers=h, json={"test_id": aid}).json()
    assert premium["premium_features"]["generated_by"]["provider"] == "nvidia"
    assert premium["premium_features"]["estimated_cost_usd"] > 0

    listed = client.get("/api/admin/assessments", headers=h).json()["assessments"]
    assert listed[0]["assessment_id"] == aid and listed[0]["has_premium"] is True

    cohort = client.post("/api/admin/cohort-analysis", headers=h).json()
    assert cohort["content_source"] == "llm" and cohort["summary"] == "NIM cohort summary."
    cohort_body = next(b for b in nim_server.bodies() if '"observations": {' in b["messages"][0]["content"])
    assert "Candidate 30" not in json.dumps(cohort_body)  # aggregated only

    cleared = client.delete("/api/admin/llm", headers=h).json()["current"]
    assert cleared["available"] is False and cleared["source"] == "none"


def test_cohort_analysis_fallback_and_empty(cfg):
    client = api_client(cfg)
    assert client.post("/api/admin/cohort-analysis").status_code == 409
    for i in range(3):
        client.post("/api/assess", json=assess_body(40 + i))
    cohort = client.post("/api/admin/cohort-analysis").json()
    assert cohort["content_source"] == "fallback" and cohort["candidates"] == 3
    assert "provisional" in cohort["summary"]


def test_provider_from_environment(cfg):
    env_nim = dataclasses.replace(cfg, llm_provider="nvidia", llm_api_key="nvapi-env", llm_model="meta/llama-3.3-70b-instruct")
    interp = LLMInterpreter(env_nim)
    assert interp.provider.id == "nvidia" and interp.source == "environment"
    assert LLMInterpreter(dataclasses.replace(cfg, llm_provider="nvidia")).provider is None  # no key


# ---------------------------------------------------------------------------
# Platform: admin accounts, employee links, candidate flow
# ---------------------------------------------------------------------------

from auth import hash_password, password_problem, verify_password  # noqa: E402


def candidate_answers(seed: int) -> dict:
    return {"responses": {str(k): v for k, v in random_responses(seed).items()}}


def test_password_hashing_and_policy():
    h = hash_password("Correct-Horse-9")
    assert h.startswith("scrypt$") and "Correct-Horse-9" not in h
    assert verify_password("Correct-Horse-9", h) and not verify_password("wrong", h)
    assert hash_password("Correct-Horse-9") != h  # salted
    assert password_problem("short1A") and password_problem("alllowercase123") and not password_problem("Good-Pass-123")


def test_first_run_setup_login_logout(cfg):
    client = api_client(cfg, login=False)
    assert client.get("/api/auth/status").json()["setup_required"] is True
    weak = client.post("/api/auth/setup", json={"name": "A", "email": "a@example.com", "password": "password"})
    assert weak.status_code == 422
    ok = client.post("/api/auth/setup", json={"name": "Asha", "email": "Asha@Example.com", "password": ADMIN_PASSWORD})
    assert ok.status_code == 200 and ok.json()["admin"]["email"] == "asha@example.com"
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.post("/api/auth/setup", json={"name": "B", "email": "b@example.com",
                                                "password": ADMIN_PASSWORD}).status_code == 409

    csrf = ok.json()["csrf_token"]
    assert client.get("/api/auth/me").json()["admin"]["name"] == "Asha"
    # Writes need the CSRF token even with a valid session.
    assert client.post("/api/admin/invitations", json={"employee_name": "X"}).status_code == 403
    assert client.post("/api/admin/invitations", json={"employee_name": "X"},
                       headers={"X-CSRF-Token": csrf}).status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "asha@example.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ASHA@example.com", "password": ADMIN_PASSWORD}).status_code == 200


def test_setup_token_required_in_production(cfg):
    prod = dataclasses.replace(cfg, environment="production", response_encryption_key=__import__(
        "cryptography.fernet").fernet.Fernet.generate_key().decode(), admin_setup_token="setup-123")
    client = api_client(prod, login=False)
    body = {"name": "A", "email": "a@example.com", "password": ADMIN_PASSWORD}
    assert client.post("/api/auth/setup", json=body).status_code == 403
    assert client.post("/api/auth/setup", json={**body, "setup_token": "setup-123"}).status_code == 200


def test_login_rate_limit(cfg):
    client = api_client(cfg)
    client.post("/api/auth/logout")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 429


def test_admin_user_management_and_password_change(cfg):
    client = api_client(cfg)
    me = client.get("/api/auth/me").json()["admin"]
    added = client.post("/api/admin/users", json={"name": "Ravi", "email": "ravi@example.com", "password": "Another-Pass-7"})
    assert added.status_code == 200
    assert client.post("/api/admin/users", json={"name": "Dup", "email": "RAVI@example.com",
                                                 "password": "Another-Pass-7"}).status_code == 422
    assert len(client.get("/api/admin/users").json()["users"]) == 2
    assert client.delete(f"/api/admin/users/{me['id']}").status_code == 400  # not yourself
    assert client.delete(f"/api/admin/users/{added.json()['id']}").status_code == 200

    assert client.post("/api/auth/change-password", json={"current_password": "wrong",
                                                          "new_password": "Brand-New-Pass-1"}).status_code == 403
    assert client.post("/api/auth/change-password", json={"current_password": ADMIN_PASSWORD,
                                                          "new_password": "Brand-New-Pass-1"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "Brand-New-Pass-1"}).status_code == 200


def test_employee_link_lifecycle_and_report_only_for_admin(cfg):
    admin = api_client(cfg)
    inv = admin.post("/api/admin/invitations", json={
        "employee_name": "Meera Iyer", "email": "meera@example.com", "employee_code": "E-1001",
        "department": "Engineering"}).json()
    assert inv["status"] == "sent" and "/t/" in inv["link"] and inv["link"].startswith("http://testserver/t/")
    token = inv["link"].rsplit("/", 1)[1]

    employee = TestClient(admin.app)  # no admin cookie
    opened = employee.get(f"/api/invite/{token}").json()
    assert opened["status"] == "sent" and opened["candidate"]["name"] == "Meera Iyer"
    assert "scores" not in json.dumps(opened)
    assert employee.get("/api/invite/not-a-real-token-123456").status_code == 404
    assert admin.get("/api/admin/invitations").json()["invitations"][0]["status"] == "opened"

    started = employee.post(f"/api/invite/{token}/start").json()
    assert started["duration_minutes"] == cfg.test_duration_minutes
    assert employee.post(f"/api/invite/{token}/start").json()["started_at"] == started["started_at"]  # idempotent

    bad = employee.post(f"/api/invite/{token}/submit", json={"responses": {"1": 9}})
    assert bad.status_code == 422  # malformed input doesn't burn the link
    res = employee.post(f"/api/invite/{token}/submit", json=candidate_answers(1))
    assert res.status_code == 200 and res.json() == {"status": "received"}  # no results for the employee
    assert employee.post(f"/api/invite/{token}/submit", json=candidate_answers(2)).status_code == 409
    assert employee.get(f"/api/invite/{token}").json() == {
        "status": "completed", "organization": cfg.organization_name,
        "support": {"email": cfg.support_email, "phone": cfg.support_phone}}

    # Employees can't reach any report endpoint.
    for method, path in (("get", "/api/results/E-1001"), ("get", "/api/admin/assessments"),
                         ("post", "/api/export/E-1001?format=pdf")):
        assert getattr(employee, method)(path).status_code == 401

    row = admin.get("/api/admin/invitations").json()["invitations"][0]
    assert row["status"] == "completed" and row["assessment_id"]
    report = admin.get(f"/api/results/{row['assessment_id']}").json()
    assert report["name"] == "Meera Iyer" and len(report["scores"]) == 11
    assert admin.post(f"/api/admin/invitations/{row['id']}/revoke").status_code == 409  # already completed


def test_revoke_extend_and_expiry(cfg):
    admin = api_client(cfg)
    inv = admin.post("/api/admin/invitations", json={"employee_name": "Kiran", "valid_days": 1}).json()
    token = inv["link"].rsplit("/", 1)[1]
    assert inv["employee_code"].startswith("EMP-")

    revoked = admin.post(f"/api/admin/invitations/{inv['id']}/revoke").json()
    assert revoked["status"] == "revoked"
    assert admin.get(f"/api/invite/{token}").json()["status"] == "revoked"
    assert admin.post(f"/api/invite/{token}/submit", json=candidate_answers(3)).status_code == 410

    extended = admin.post(f"/api/admin/invitations/{inv['id']}/extend", json={"days": 7}).json()
    assert extended["status"] == "sent"  # extending also re-opens a revoked link

    db = admin.app.state.db
    from datetime import timedelta as td
    from database_models import utcnow as now
    db.update_invitation(inv["id"], expires_at=now() - td(minutes=1))
    assert admin.get(f"/api/invite/{token}").json()["status"] == "expired"
    assert admin.post(f"/api/invite/{token}/start").status_code == 410

    # Someone who started before the link expired can still submit within the time limit.
    db.update_invitation(inv["id"], started_at=now() - td(minutes=10))
    assert admin.post(f"/api/invite/{token}/submit", json=candidate_answers(3)).status_code == 200


def test_late_submission_is_flagged(cfg):
    admin = api_client(cfg)
    inv = admin.post("/api/admin/invitations", json={"employee_name": "Late Larry"}).json()
    token = inv["link"].rsplit("/", 1)[1]
    from datetime import timedelta as td
    from database_models import utcnow as now
    admin.app.state.db.update_invitation(inv["id"], started_at=now() - td(minutes=cfg.test_duration_minutes + 30))
    assert admin.post(f"/api/invite/{token}/submit", json=candidate_answers(4)).status_code == 200
    row = admin.get("/api/admin/invitations").json()["invitations"][0]
    assert row["submitted_late"] is True
    assert "Submitted after the time limit." in admin.get(f"/api/results/{row['assessment_id']}").json()["quality_flags"]


def test_bulk_invitations_search_and_link_base(cfg):
    branded = dataclasses.replace(cfg, public_base_url="https://assess.example.com")
    admin = api_client(branded)
    res = admin.post("/api/admin/invitations/bulk", json={"valid_days": 30, "employees": [
        {"employee_name": "Anil", "email": "anil@example.com"}, {"employee_name": "Bina", "employee_code": "B-2"}]})
    rows = res.json()["invitations"]
    assert len(rows) == 2 and all(r["link"].startswith("https://assess.example.com/t/") for r in rows)
    assert len({r["link"] for r in rows}) == 2
    found = admin.get("/api/admin/invitations?search=bina").json()["invitations"]
    assert [r["employee_name"] for r in found] == ["Bina"]
    assert admin.get("/api/admin/invitations").json()["counts"] == {"sent": 2}

    # Tokens are stored hashed + encrypted, never in plaintext.
    from database_models import Invitation as Inv
    token = rows[0]["link"].rsplit("/", 1)[1]
    with admin.app.state.db.session() as s:
        stored = s.query(Inv).first()
        assert token not in stored.token_hash and token.encode() not in stored.token_ciphertext


def test_security_headers_and_spa_routes(cfg, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    client = api_client(dataclasses.replace(cfg, frontend_dist=dist), login=False)
    for path in ("/", "/admin", "/admin/employees", "/t/some-token"):
        res = client.get(path)
        assert res.status_code == 200 and "id=root" in res.text, path
        assert res.headers["referrer-policy"] == "no-referrer" and res.headers["x-frame-options"] == "DENY"
    assert client.get("/api/auth/status").headers["cache-control"] == "no-store"
