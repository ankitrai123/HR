"""FastAPI server for the hybrid assessment system.

Run:  uvicorn api_server:app --reload        (or: python api_server.py)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

import exporters
from config import Settings, settings as default_settings
from database_models import Assessment, Database, DatabaseCacheStore
from hybrid_assessment_engine import (AssessmentInput, HybridReportGenerator, HybridScoringEngine,
                                      LLMInterpretationCache, public_report)

log = logging.getLogger("assessment.api")
ADMIN_PAGE = Path(__file__).resolve().parent / "static" / "admin.html"


class AssessRequest(BaseModel):
    test_taker_id: str = Field(min_length=1, max_length=64, examples=["165943163"])
    name: str = Field(min_length=1, max_length=200, examples=["Ankit Kumar"])
    email: str | None = Field(default=None, max_length=320, examples=["ankit@example.com"])
    responses: dict[str, int | None] = Field(
        description="Question id -> response (1..scale_points). Unanswered questions may be omitted or null.",
        examples=[{"1": 2, "2": 4, "3": 5}],
        max_length=1000,
    )
    premium: bool = Field(default=False, description="Also generate the LLM-enhanced premium report.")


class PremiumRequest(BaseModel):
    test_id: str = Field(description="Assessment id, or a test-taker id (uses their latest assessment).")


def create_app(cfg: Settings = default_settings, db: Database | None = None,
               generator: HybridReportGenerator | None = None) -> FastAPI:
    problems = cfg.validate()
    if problems and cfg.is_production:
        raise RuntimeError("invalid configuration: " + "; ".join(problems))
    for p in problems:
        log.warning("config: %s", p)
    if not cfg.admin_api_key:
        log.warning("ADMIN_API_KEY not set: results, analytics and exports are unauthenticated (development only)")

    db = db or Database(cfg)
    db.create_all()
    if generator is None:
        cache = LLMInterpretationCache(cfg.cache_max_entries, store=DatabaseCacheStore(db))
        generator = HybridReportGenerator(cfg=cfg, cache=cache)

    app = FastAPI(title="Hybrid Psychometric Assessment API", version="1.0.0",
                  description="Deterministic Sten scoring with optional Claude-enhanced premium reports.")
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])
    app.state.db, app.state.generator, app.state.cfg = db, generator, cfg

    def require_admin(x_api_key: str | None = Header(default=None)) -> None:
        if cfg.admin_api_key and not (x_api_key and secrets.compare_digest(x_api_key, cfg.admin_api_key)):
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")

    def find_assessment(test_id: str) -> Assessment:
        a = db.get_assessment(test_id)
        if a is None:
            a = db.latest_for_test_taker(test_id)
        if a is None:
            raise HTTPException(status_code=404, detail=f"no assessment found for {test_id!r}")
        return a

    def full_report(a: Assessment) -> dict[str, Any]:
        report = dict(a.report)
        if a.premium_report:
            report = a.premium_report
        return {**report, "assessment_id": a.id, "submitted_at": a.submitted_at.isoformat()}

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "llm_available": generator.interpreter.available,
                "norms": generator.engine.norms_status, "scoring_key": generator.bank.key_status}

    @app.get("/api/questions")
    def questions() -> dict[str, Any]:
        """Question texts and scale (no scoring key)."""
        return {"scale_points": cfg.scale_points,
                "questions": [{"id": it.id, "text": it.text} for it in generator.bank.items.values()]}

    @app.post("/api/assess")
    def assess(body: AssessRequest) -> dict[str, Any]:
        data = AssessmentInput(body.test_taker_id, body.name, body.email,
                               {k: v for k, v in body.responses.items() if v is not None})
        report = generator.standard_report(data)
        responses = generator.validator.normalise(data.responses)
        assessment_id = db.save_assessment(
            test_taker_id=body.test_taker_id, name=body.name, email=body.email,
            instrument=generator.bank.instrument, scale_points=cfg.scale_points,
            responses=responses, report=public_report(report), proportions=report.get("_proportions", {}),
        )
        if body.premium and report["status"] == "Completed":
            report = generator.premium_report(data, standard=report)
            db.save_premium_report(assessment_id, public_report(report))
        return {**public_report(report), "assessment_id": assessment_id}

    @app.get("/api/results/{test_id}", dependencies=[Depends(require_admin)])
    def results(test_id: str) -> dict[str, Any]:
        return full_report(find_assessment(test_id))

    @app.post("/api/generate-premium-report", dependencies=[Depends(require_admin)])
    def generate_premium(body: PremiumRequest) -> dict[str, Any]:
        a = find_assessment(body.test_id)
        if a.status != "Completed":
            raise HTTPException(status_code=409, detail="premium reports need a completed assessment")
        data = AssessmentInput(a.test_taker.external_id, a.test_taker.name, a.test_taker.email, {})
        report = generator.premium_report(data, standard=dict(a.report))
        db.save_premium_report(a.id, public_report(report))
        return {**public_report(report), "assessment_id": a.id}

    @app.post("/api/export/{test_id}", dependencies=[Depends(require_admin)])
    def export(test_id: str, format: Literal["pdf", "json", "text"] = Query("pdf")) -> Response:
        a = find_assessment(test_id)
        report = full_report(a)
        stem = f"assessment_{a.test_taker.external_id}_{a.id[:8]}"
        if format == "json":
            return Response(exporters.to_json(report), media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})
        if format == "text":
            return PlainTextResponse(exporters.to_text(report),
                                     headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'})
        return Response(exporters.to_pdf(report), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'})

    @app.get("/api/analytics", dependencies=[Depends(require_admin)])
    def analytics() -> dict[str, Any]:
        stats = db.analytics()
        stats["engine"] = generator.stats()
        stats["norms"] = generator.engine.norms_status
        return stats

    @app.get("/api/norms/suggested", dependencies=[Depends(require_admin)])
    def suggested_norms(min_sample: int = Query(30, ge=2)) -> dict[str, Any]:
        """Norms computed from stored genuine assessments. Save the result to
        NORMS_PATH (data/norms.json) and restart to use calibrated norms."""
        try:
            return HybridScoringEngine.compute_norms(db.proportion_rows(), min_sample=min_sample)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_page() -> str:
        return ADMIN_PAGE.read_text(encoding="utf-8")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000)
