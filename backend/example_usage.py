"""Worked examples for the hybrid assessment engine.

    python example_usage.py

1. Load sample responses (data/sample_responses.json)
2. Run the assessment and print the standard report
3. Generate a premium report (uses Claude when ANTHROPIC_API_KEY is set,
   otherwise falls back to pre-written text)
4. Export text, JSON and PDF to ./output/
5. Show cache behaviour on a second, similar candidate
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import exporters
from config import settings
from hybrid_assessment_engine import AssessmentInput, HybridReportGenerator

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"


def main() -> None:
    sample = json.loads((HERE / "data" / "sample_responses.json").read_text())
    data = AssessmentInput(sample["test_taker_id"], sample["name"], sample.get("email"),
                           {int(k): v for k, v in sample["responses"].items()})
    gen = HybridReportGenerator()

    print("== Standard report (deterministic, no API calls) ==")
    report = gen.standard_report(data)
    print(f"status={report['status']} quality={report['response_quality']} "
          f"time={report['completion_time_ms']} ms api_calls={report['api_calls_made']}")
    for dim, s in report["scores"].items():
        print(f"  {dim:26s} sten {s['sten_score']:>2}  {s['level']:<8}  P{s['percentile']:>5}")
    print("  strengths:", report["strengths"] or "-")
    print("  development:", report["areas_of_development"] or "-")
    print("  summary:", report["profile_summary"])

    print("\n== Premium report ==")
    if not settings.llm_available:
        print("  (ANTHROPIC_API_KEY not set - premium sections use the pre-written fallback)")
    start = time.perf_counter()
    premium = gen.premium_report(data, standard=report)
    pf = premium["premium_features"]
    print(f"  source={pf['content_source']} api_calls={pf['api_calls_made']} "
          f"cost=${pf['estimated_cost_usd']:.4f} time={(time.perf_counter() - start) * 1000:.0f} ms")
    print("  executive summary:", pf["executive_summary"][:300], "..." if len(pf["executive_summary"]) > 300 else "")

    OUT.mkdir(exist_ok=True)
    stem = f"report_{data.test_taker_id}"
    (OUT / f"{stem}.txt").write_text(exporters.to_text(premium), encoding="utf-8")
    (OUT / f"{stem}.json").write_text(exporters.to_json(premium), encoding="utf-8")
    (OUT / f"{stem}.pdf").write_bytes(exporters.to_pdf(premium))
    print(f"\n== Exported to {OUT.relative_to(HERE)}/{stem}.{{txt,json,pdf}} ==")

    print("\n== Cache: same candidate profile again ==")
    again = gen.premium_report(data, standard=report)["premium_features"]
    print(f"  api_calls={again['api_calls_made']} time={again['generation_time_ms']} ms")
    print("  engine stats:", json.dumps(gen.stats()))


if __name__ == "__main__":
    main()
