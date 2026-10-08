"""FastAPI server for the hybrid assessment system.

Run:  uvicorn api_server:app --reload        (or: python api_server.py)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

import exporters
from auth import SESSION_COOKIE, SESSION_TTL, AdminIdentity, AuthService
from config import Settings, settings as default_settings
from database_models import Assessment, Database, DatabaseCacheStore, Invitation, as_utc, utcnow
from hybrid_assessment_engine import (AssessmentInput, HybridReportGenerator, HybridScoringEngine,
                                      LLMInterpretationCache, public_report)
from llm_providers import PROVIDERS, LLMUnavailable, build_provider, catalog, mask_key

log = logging.getLogger("assessment.api")


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


class LLMConfigRequest(BaseModel):
    provider: str = Field(examples=["nvidia"], description="Provider id from GET /api/admin/llm")
    model: str = Field(min_length=1, max_length=200, examples=["meta/llama-3.3-70b-instruct"])
    api_key: str | None = Field(default=None, max_length=500,
                                description="Omit to keep the key already stored for this provider.")
    base_url: str | None = Field(default=None, max_length=500, description="Only for Ollama / custom endpoints.")
    input_price_per_mtok: float | None = Field(default=None, ge=0,
                                               description="USD per million input tokens, for cost estimates. "
                                                           "Omit to keep the stored value.")
    output_price_per_mtok: float | None = Field(default=None, ge=0)
    test: bool = Field(default=True, description="Make a tiny test call before saving.")


class ModelListRequest(BaseModel):
    provider: str
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)


TEST_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
               "additionalProperties": False}


class SetupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    setup_token: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class NewAdminRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class InvitationRequest(BaseModel):
    employee_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    employee_code: str | None = Field(default=None, max_length=64, description="Employee ID; generated if omitted.")
    department: str | None = Field(default=None, max_length=120)
    valid_days: int | None = Field(default=None, ge=1, le=90)


class BulkInvitationRequest(BaseModel):
    employees: list[InvitationRequest] = Field(min_length=1, max_length=500)
    valid_days: int | None = Field(default=None, ge=1, le=90)


class ExtendRequest(BaseModel):
    days: int = Field(ge=1, le=90)


class CandidateSubmission(BaseModel):
    responses: dict[str, int | None] = Field(max_length=1000)


class PremiumRequest(BaseModel):
    test_id: str = Field(description="Assessment id, or a test-taker id (uses their latest assessment).")


def create_app(cfg: Settings = default_settings, db: Database | None = None,
               generator: HybridReportGenerator | None = None) -> FastAPI:
    problems = cfg.validate()
    if problems and (cfg.is_production or cfg.on_vercel):
        raise RuntimeError("invalid configuration: " + "; ".join(problems))
    for p in problems:
        log.warning("config: %s", p)
    db = db or Database(cfg)
    db.create_all()
    auth = AuthService(db)
    if generator is None:
        cache = LLMInterpretationCache(cfg.cache_max_entries, store=DatabaseCacheStore(db))
        generator = HybridReportGenerator(cfg=cfg, cache=cache)

    app = FastAPI(title="Hybrid Psychometric Assessment API", version="1.0.0",
                  description="Deterministic Sten scoring with optional LLM-enhanced premium reports "
                              "(Claude, NVIDIA NIM, OpenAI, Gemini and other OpenAI-compatible providers).")
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])
    app.state.db, app.state.generator, app.state.cfg, app.state.auth = db, generator, cfg, auth

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Employee links carry a secret token in the URL: never leak it via Referer.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # The interpreter's initial provider (from environment variables or an
    # injected test client) is the baseline restored when the dashboard
    # setting is removed.
    baseline = (generator.interpreter.provider, generator.interpreter.source,
                generator.interpreter.input_price, generator.interpreter.output_price)
    app.state.llm_version = None

    def sync_llm() -> None:
        """Apply the dashboard-configured provider if it changed (cheap
        timestamp check, so every worker converges on the same setting)."""
        version = db.llm_settings_version()
        if version == app.state.llm_version:
            return
        app.state.llm_version = version
        stored = db.get_llm_settings()
        if stored is None:
            generator.interpreter.set_provider(baseline[0], baseline[1], baseline[2], baseline[3])
            return
        try:
            provider = build_provider(cfg, stored.provider, stored.api_key, stored.model, stored.base_url)
        except ValueError as exc:
            log.error("stored LLM settings are invalid (%s); keeping the previous provider", exc)
            return
        generator.interpreter.set_provider(provider, "dashboard", stored.input_price_per_mtok,
                                           stored.output_price_per_mtok)

    def llm_status() -> dict[str, Any]:
        stored = db.get_llm_settings()
        interp = generator.interpreter
        info = interp.describe()
        info.update(key_hint=stored.key_hint if stored and info["source"] == "dashboard" else None,
                    base_url=stored.base_url if stored and info["source"] == "dashboard" else None,
                    input_price_per_mtok=interp.input_price, output_price_per_mtok=interp.output_price,
                    updated_at=stored.updated_at.isoformat() if stored else None)
        return info

    def resolve_key(provider: str, api_key: str | None, base_url: str | None) -> str | None:
        """A pasted key wins; otherwise reuse the stored or environment key for
        the same provider. A stored key is only reused for the same endpoint,
        so it can't be redirected to a different server."""
        if api_key:
            return api_key.strip()
        stored = db.get_llm_settings()
        if stored and stored.provider == provider and stored.api_key and stored.base_url == base_url:
            return stored.api_key
        if provider == "anthropic" and cfg.anthropic_api_key:
            return cfg.anthropic_api_key
        if provider == cfg.llm_provider and cfg.llm_api_key:
            return cfg.llm_api_key
        return None

    sync_llm()

    def require_admin(request: Request, admin_session: str | None = Cookie(default=None),
                      x_api_key: str | None = Header(default=None),
                      x_csrf_token: str | None = Header(default=None)) -> AdminIdentity:
        """A signed-in admin (session cookie + CSRF header on writes), or a
        script using ADMIN_API_KEY."""
        if admin_session:
            identity = auth.resolve_session(admin_session)
            if identity is not None:
                if request.method not in ("GET", "HEAD", "OPTIONS") and not (
                        x_csrf_token and secrets.compare_digest(x_csrf_token, identity.csrf_token or "")):
                    raise HTTPException(status_code=403, detail="missing or invalid CSRF token")
                return identity
        if x_api_key and cfg.admin_api_key and secrets.compare_digest(x_api_key, cfg.admin_api_key):
            return AdminIdentity(None, "api-key", "API key")
        raise HTTPException(status_code=401, detail="Please sign in.")

    def set_session_cookie(response: Response, request: Request, token: str) -> None:
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/",
                            secure=cfg.is_production or request.url.scheme == "https",
                            max_age=int(SESSION_TTL.total_seconds()))

    def client_id(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def link_base(request: Request) -> str:
        return cfg.public_base_url or str(request.base_url).rstrip("/")

    def invitation_view(inv: Invitation, request: Request) -> dict[str, Any]:
        return {
            "id": inv.id, "employee_name": inv.employee_name, "email": inv.email,
            "employee_code": inv.employee_code, "department": inv.department, "status": inv.status(),
            "link": f"{link_base(request)}/t/{db.invitation_token(inv)}",
            "created_at": as_utc(inv.created_at).isoformat(), "expires_at": as_utc(inv.expires_at).isoformat(),
            "opened_at": inv.opened_at and as_utc(inv.opened_at).isoformat(),
            "started_at": inv.started_at and as_utc(inv.started_at).isoformat(),
            "submitted_at": inv.submitted_at and as_utc(inv.submitted_at).isoformat(),
            "submitted_late": inv.submitted_late, "assessment_id": inv.assessment_id,
        }

    def create_invitation(body: InvitationRequest, admin: AdminIdentity, valid_days: int | None) -> Invitation:
        inv, _ = db.create_invitation(
            employee_name=body.employee_name.strip(), email=body.email, department=(body.department or "").strip() or None,
            employee_code=(body.employee_code or "").strip() or f"EMP-{uuid.uuid4().hex[:8].upper()}",
            valid_days=body.valid_days or valid_days or cfg.invitation_default_days, created_by=admin.id)
        return inv

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

    @app.post("/api/assess", dependencies=[Depends(require_admin)])
    def assess(body: AssessRequest) -> dict[str, Any]:
        """Score a submission directly (integrations / bulk import). Employees
        use their personal link instead and never see results."""
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
            sync_llm()
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
        sync_llm()
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
        sync_llm()
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

    # -- LLM provider settings (admin dashboard) -----------------------------

    @app.get("/api/admin/llm", dependencies=[Depends(require_admin)])
    def get_llm_config() -> dict[str, Any]:
        """Current provider (the API key is never returned) and the provider catalog."""
        sync_llm()
        return {"current": llm_status(), "providers": catalog()}

    @app.put("/api/admin/llm", dependencies=[Depends(require_admin)])
    def put_llm_config(body: LLMConfigRequest) -> dict[str, Any]:
        if body.provider not in PROVIDERS:
            raise HTTPException(status_code=422, detail=f"unknown provider {body.provider!r}")
        base_url = (body.base_url or "").strip() or None
        api_key = resolve_key(body.provider, body.api_key, base_url)
        try:
            provider = build_provider(cfg, body.provider, api_key, body.model.strip(), base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.test:
            try:
                result = provider.generate_json("You are a connectivity check. Reply in JSON.",
                                                'Return the JSON object {"ok": true}.', TEST_SCHEMA)
            except LLMUnavailable as exc:
                raise HTTPException(status_code=400, detail=f"Connection test failed: {exc}") from exc
            if result.data.get("ok") is not True:
                raise HTTPException(status_code=400, detail="Connection test failed: unexpected reply")
        previous = db.get_llm_settings()
        same = previous is not None and previous.provider == body.provider

        def price(given: float | None, stored: float | None) -> float:
            return given if given is not None else (stored if same and stored is not None else 0.0)

        db.save_llm_settings(provider=body.provider, model=body.model.strip(), base_url=base_url, api_key=api_key,
                             key_hint=mask_key(api_key),
                             input_price=price(body.input_price_per_mtok, previous and previous.input_price_per_mtok),
                             output_price=price(body.output_price_per_mtok, previous and previous.output_price_per_mtok))
        log.info("LLM provider set to %s / %s from the admin dashboard", body.provider, body.model)
        sync_llm()
        return {"current": llm_status(), "tested": body.test}

    @app.delete("/api/admin/llm", dependencies=[Depends(require_admin)])
    def delete_llm_config() -> dict[str, Any]:
        """Remove the dashboard setting and revert to the environment configuration."""
        db.clear_llm_settings()
        sync_llm()
        return {"current": llm_status()}

    @app.post("/api/admin/llm/models", dependencies=[Depends(require_admin)])
    def list_llm_models(body: ModelListRequest) -> dict[str, Any]:
        """List the models the given key can use (queried from the provider)."""
        if body.provider not in PROVIDERS:
            raise HTTPException(status_code=422, detail=f"unknown provider {body.provider!r}")
        base_url = (body.base_url or "").strip() or None
        try:
            provider = build_provider(cfg, body.provider, resolve_key(body.provider, body.api_key, base_url),
                                      "list-models", base_url)
            return {"models": provider.list_models()}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LLMUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -- Dashboard analysis ------------------------------------------------------

    @app.get("/api/admin/assessments", dependencies=[Depends(require_admin)])
    def list_assessments(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        return {"assessments": db.list_assessments(limit=limit, offset=offset)}

    @app.post("/api/admin/cohort-analysis", dependencies=[Depends(require_admin)])
    def cohort_analysis() -> dict[str, Any]:
        """LLM analysis of aggregated (anonymised) results across all candidates."""
        stats = db.analytics()
        if not stats["assessments"]["total"]:
            raise HTTPException(status_code=409, detail="no assessments to analyse yet")
        sync_llm()
        return generator.cohort_report(stats)

    # -- Authentication ---------------------------------------------------------

    def identity_view(identity: AdminIdentity) -> dict[str, Any]:
        return {"admin": {"id": identity.id, "name": identity.name, "email": identity.email},
                "csrf_token": identity.csrf_token}

    @app.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        return {"setup_required": auth.admin_count() == 0,
                "setup_token_required": bool(cfg.admin_setup_token) or cfg.is_production,
                "organization": cfg.organization_name}

    @app.post("/api/auth/setup")
    def setup(body: SetupRequest, request: Request, response: Response) -> dict[str, Any]:
        """Create the first admin account (only while none exists)."""
        if auth.admin_count() > 0:
            raise HTTPException(status_code=409, detail="Setup is already complete. Please sign in.")
        if cfg.is_production and not cfg.admin_setup_token:
            raise HTTPException(status_code=403, detail="Set ADMIN_SETUP_TOKEN or run `python manage.py create-admin`.")
        if cfg.admin_setup_token and not (body.setup_token and
                                          secrets.compare_digest(body.setup_token, cfg.admin_setup_token)):
            raise HTTPException(status_code=403, detail="Invalid setup token.")
        try:
            user = auth.create_admin(body.email, body.name, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        token, csrf = auth.create_session(user.id)
        set_session_cookie(response, request, token)
        log.info("first admin account created (%s)", user.email)
        return identity_view(AdminIdentity(user.id, user.email, user.name, csrf))

    @app.post("/api/auth/login")
    def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        email, client = body.email.strip().lower(), client_id(request)
        if auth.limiter.blocked(email, client):
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
        user = auth.authenticate(email, body.password)
        if user is None:
            auth.limiter.fail(email, client)
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        auth.limiter.reset(email, client)
        token, csrf = auth.create_session(user.id)
        set_session_cookie(response, request, token)
        return identity_view(AdminIdentity(user.id, user.email, user.name, csrf))

    @app.post("/api/auth/logout")
    def logout(response: Response, admin_session: str | None = Cookie(default=None)) -> dict[str, Any]:
        if admin_session:
            auth.end_session(admin_session)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(admin: AdminIdentity = Depends(require_admin)) -> dict[str, Any]:
        return identity_view(admin)

    @app.post("/api/auth/change-password")
    def change_password(body: ChangePasswordRequest, admin: AdminIdentity = Depends(require_admin),
                        admin_session: str | None = Cookie(default=None)) -> dict[str, Any]:
        if admin.id is None:
            raise HTTPException(status_code=400, detail="Sign in with an admin account to change a password.")
        try:
            auth.change_password(admin.id, body.current_password, body.new_password)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        auth.end_other_sessions(admin.id, keep_token=admin_session)
        return {"ok": True}

    # -- Admin users ----------------------------------------------------------------

    @app.get("/api/admin/users", dependencies=[Depends(require_admin)])
    def list_admins() -> dict[str, Any]:
        return {"users": [{"id": u.id, "name": u.name, "email": u.email,
                           "created_at": as_utc(u.created_at).isoformat(),
                           "last_login_at": u.last_login_at and as_utc(u.last_login_at).isoformat()}
                          for u in auth.list_admins()]}

    @app.post("/api/admin/users", dependencies=[Depends(require_admin)])
    def add_admin(body: NewAdminRequest) -> dict[str, Any]:
        try:
            user = auth.create_admin(body.email, body.name, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": user.id, "name": user.name, "email": user.email}

    @app.delete("/api/admin/users/{admin_id}")
    def remove_admin(admin_id: int, admin: AdminIdentity = Depends(require_admin)) -> dict[str, Any]:
        if admin.id == admin_id:
            raise HTTPException(status_code=400, detail="You can't remove your own account.")
        try:
            auth.delete_admin(admin_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True}

    # -- Employee links (invitations) ----------------------------------------------

    @app.post("/api/admin/invitations")
    def invite(body: InvitationRequest, request: Request, admin: AdminIdentity = Depends(require_admin)) -> dict[str, Any]:
        return invitation_view(create_invitation(body, admin, None), request)

    @app.post("/api/admin/invitations/bulk")
    def invite_bulk(body: BulkInvitationRequest, request: Request,
                    admin: AdminIdentity = Depends(require_admin)) -> dict[str, Any]:
        return {"invitations": [invitation_view(create_invitation(e, admin, body.valid_days), request)
                                for e in body.employees]}

    @app.get("/api/admin/invitations", dependencies=[Depends(require_admin)])
    def list_invitations(request: Request, status: str | None = Query(None), search: str | None = Query(None)
                         ) -> dict[str, Any]:
        return {"invitations": [invitation_view(i, request) for i in db.list_invitations(status, search)],
                "counts": db.invitation_counts()}

    def editable_invitation(invitation_id: str) -> Invitation:
        inv = db.get_invitation(invitation_id)
        if inv is None:
            raise HTTPException(status_code=404, detail="Invitation not found.")
        if inv.submitted_at:
            raise HTTPException(status_code=409, detail="This employee has already completed the assessment.")
        return inv

    @app.post("/api/admin/invitations/{invitation_id}/revoke", dependencies=[Depends(require_admin)])
    def revoke_invitation(invitation_id: str, request: Request) -> dict[str, Any]:
        editable_invitation(invitation_id)
        return invitation_view(db.update_invitation(invitation_id, revoked_at=utcnow()), request)

    @app.post("/api/admin/invitations/{invitation_id}/extend", dependencies=[Depends(require_admin)])
    def extend_invitation(invitation_id: str, body: ExtendRequest, request: Request) -> dict[str, Any]:
        inv = editable_invitation(invitation_id)
        base = max(as_utc(inv.expires_at), utcnow())
        return invitation_view(db.update_invitation(invitation_id, expires_at=base + timedelta(days=body.days),
                                                    revoked_at=None), request)

    # -- Employee-facing endpoints (authorised by the link token only) --------------

    def invitation_for_token(token: str) -> Invitation:
        inv = db.invitation_by_token(token) if 16 <= len(token) <= 128 else None
        if inv is None:
            raise HTTPException(status_code=404, detail={"status": "invalid",
                                                         "message": "This assessment link is not valid."})
        return inv

    def deadline(inv: Invitation):
        return as_utc(inv.started_at) + timedelta(minutes=cfg.test_duration_minutes + cfg.submission_grace_minutes)

    @app.get("/api/invite/{token}")
    def open_invitation(token: str) -> dict[str, Any]:
        """What the employee's browser needs to run the test. No scores, ever."""
        inv = invitation_for_token(token)
        status = inv.status()
        info = {"status": status, "organization": cfg.organization_name,
                "support": {"email": cfg.support_email, "phone": cfg.support_phone}}
        if status in ("revoked", "expired", "completed"):
            return info
        if inv.opened_at is None:
            inv = db.update_invitation(inv.id, opened_at=utcnow())
        return {**info,
                "candidate": {"name": inv.employee_name, "email": inv.email, "employee_code": inv.employee_code,
                              "department": inv.department},
                "window": {"opens": as_utc(inv.created_at).isoformat(), "closes": as_utc(inv.expires_at).isoformat()},
                "started_at": inv.started_at and as_utc(inv.started_at).isoformat(),
                "duration_minutes": cfg.test_duration_minutes}

    @app.post("/api/invite/{token}/start")
    def start_invitation(token: str) -> dict[str, Any]:
        inv = invitation_for_token(token)
        status = inv.status()
        if status in ("revoked", "expired", "completed"):
            raise HTTPException(status_code=410, detail={"status": status})
        if inv.started_at is None:
            inv = db.update_invitation(inv.id, started_at=utcnow())
        return {"started_at": as_utc(inv.started_at).isoformat(), "duration_minutes": cfg.test_duration_minutes}

    @app.post("/api/invite/{token}/submit")
    def submit_invitation(token: str, body: CandidateSubmission) -> dict[str, Any]:
        inv = invitation_for_token(token)
        if inv.submitted_at:
            raise HTTPException(status_code=409, detail={"status": "completed"})
        if inv.revoked_at:
            raise HTTPException(status_code=410, detail={"status": "revoked"})
        # An expired link is still accepted from someone who started before it expired.
        if inv.status() == "expired" and not (inv.started_at and utcnow() <= deadline(inv)):
            raise HTTPException(status_code=410, detail={"status": "expired"})
        data = AssessmentInput(inv.employee_code, inv.employee_name, inv.email,
                               {k: v for k, v in body.responses.items() if v is not None})
        generator.validator.normalise(data.responses)  # reject malformed input before claiming the link
        if not db.claim_invitation_submission(inv.id):
            raise HTTPException(status_code=409, detail={"status": "completed"})
        late = bool(inv.started_at and utcnow() > deadline(inv))
        report = generator.standard_report(data)
        if late:
            report["quality_flags"] = [*report["quality_flags"], "Submitted after the time limit."]
        assessment_id = db.save_assessment(
            test_taker_id=inv.employee_code, name=inv.employee_name, email=inv.email,
            instrument=generator.bank.instrument, scale_points=cfg.scale_points,
            responses=generator.validator.normalise(data.responses), report=public_report(report),
            proportions=report.get("_proportions", {}),
        )
        db.update_invitation(inv.id, assessment_id=assessment_id, submitted_late=late)
        return {"status": "received"}

    # -- Web app (candidate links + admin console) -----------------------------------

    dist = cfg.frontend_dist
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    def spa() -> Response:
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<p>The web app hasn't been built yet. Run <code>npm run build</code> in the "
                            "project root, then restart the server.</p>", status_code=503)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> Response:
        path = dist / "favicon.svg"
        return FileResponse(path) if path.is_file() else Response(status_code=404)

    for route in ("/", "/admin", "/admin/{rest:path}", "/t/{token}"):
        app.add_api_route(route, spa, methods=["GET"], include_in_schema=False)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000)
