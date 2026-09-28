"""Performance and cache-efficiency benchmark.

    python benchmark.py [--candidates 1000]

Uses a stub LLM client (no network, no cost) so the numbers measure this
service, not the Anthropic API. Fresh-generation latency and real token
usage depend on the model and must be measured against the live API.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from types import SimpleNamespace

from config import settings
from hybrid_assessment_engine import AssessmentInput, ClaudeInterpreter, HybridReportGenerator

WEIGHTS = [0.06, 0.10, 0.17, 0.22, 0.27, 0.18]


class StubClaude:
    """Returns canned JSON with a fixed per-call token usage."""

    def __init__(self, input_tokens: int, output_tokens: int):
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        props = kwargs["output_config"]["format"]["schema"]["properties"]
        payload = ({"executive_summary": "s", "coaching_insights": ["i"]} if "executive_summary" in props else
                   {"interpretation": "i", "development_actions": ["a"], "coaching_insight": "c"})
        return SimpleNamespace(stop_reason="end_turn", usage=self.usage,
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def candidate(i: int, rng: random.Random) -> AssessmentInput:
    # Give each simulated candidate their own lean so profiles vary realistically.
    shift = rng.gauss(0, 0.8)
    w = [max(0.01, x * (1 + shift * (j - 2.5) / 5)) for j, x in enumerate(WEIGHTS)]
    return AssessmentInput(str(i), f"C{i}", None, {q: rng.choices(range(1, 7), w)[0] for q in range(1, 176)})


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(p / 100 * len(values)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=1000)
    ap.add_argument("--input-tokens", type=int, default=450, help="assumed input tokens per LLM call")
    ap.add_argument("--output-tokens", type=int, default=900, help="assumed output tokens per LLM call (incl. thinking)")
    args = ap.parse_args()

    rng = random.Random(42)
    people = [candidate(i, rng) for i in range(args.candidates)]
    gen = HybridReportGenerator(interpreter=ClaudeInterpreter(settings, client=StubClaude(args.input_tokens, args.output_tokens)))

    std_ms = []
    for p in people:
        t = time.perf_counter()
        gen.standard_report(p)
        std_ms.append((time.perf_counter() - t) * 1000)

    prem_ms, calls, levels = [], [], set()
    for p in people:
        t = time.perf_counter()
        r = gen.premium_report(p)
        prem_ms.append((time.perf_counter() - t) * 1000)
        calls.append(r["premium_features"]["api_calls_made"])
        levels.add(tuple(s["level"] for s in r["scores"].values()))

    cached_ms = [ms for ms, c in zip(prem_ms, calls) if c == 0]
    stats = gen.stats()
    n = len(people)
    print(f"candidates:                 {n}")
    print(f"standard report  p50/p95:   {statistics.median(std_ms):.2f} / {pct(std_ms, 95):.2f} ms")
    print(f"premium (all)    p50/p95:   {statistics.median(prem_ms):.2f} / {pct(prem_ms, 95):.2f} ms  (stub LLM, no network)")
    if cached_ms:
        print(f"premium (0 API calls) p50:  {statistics.median(cached_ms):.2f} ms  ({len(cached_ms)} reports)")
    print(f"distinct level profiles:    {len(levels)}")
    print(f"API calls total:            {stats['api_calls']}  ({stats['api_calls'] / n:.2f} per premium report)")
    print(f"cache hit rate:             {stats['cache']['hit_rate']:.1%}")
    print(f"est. LLM cost per report:   ${stats['estimated_cost_usd'] / n:.4f}  "
          f"(model {settings.llm_model}, ${settings.llm_input_price_per_mtok}/${settings.llm_output_price_per_mtok} per MTok, "
          f"{args.input_tokens} in / {args.output_tokens} out per call)")


if __name__ == "__main__":
    main()
