"""Configuration for the hybrid assessment backend.

All settings come from environment variables (optionally a `.env` file in this
directory) so the same code runs in dev, CI and production. See
docs/CONFIGURATION.md for the full reference.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

log = logging.getLogger("assessment.config")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so python-dotenv isn't required.
    Real environment variables always win over the file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return (_env(name, str(default)) or "").lower() in ("1", "true", "yes", "on")


def normalize_database_url(url: str) -> str:
    """Accept the postgres:// and postgresql:// URLs that Vercel/Neon, Heroku and
    others inject, and use the psycopg (v3) driver for them."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    environment: str = "development"

    # --- Instrument -------------------------------------------------------
    question_bank_path: Path = DATA_DIR / "question_bank.json"
    # Optional calibrated norms (see HybridScoringEngine.compute_norms); the
    # built-in provisional norms are used when this file doesn't exist.
    norms_path: Path = DATA_DIR / "norms.json"
    # Number of Likert points. The candidate frontend uses 6
    # (Strongly Disagree .. Strongly Agree); set to 5 for a 1-5 instrument.
    scale_points: int = 6

    # --- Response quality checks -----------------------------------------
    min_answered: int = 170
    min_distinct_options: int = 3
    # Social-desirability / acquiescence ceiling expressed as a fraction of
    # the scale range: 0.75 == mean <= 4.0 on a 1-5 scale, <= 4.75 on 1-6.
    max_mean_fraction: float = 0.75
    max_middle_fraction: float = 0.50

    # --- LLM layer ----------------------------------------------------------
    anthropic_api_key: str | None = None
    # Default provider when none is set from the admin dashboard: "anthropic"
    # uses ANTHROPIC_API_KEY; any other id from llm_providers.PROVIDERS uses
    # LLM_API_KEY (+ LLM_BASE_URL for ollama/custom).
    llm_provider: str = "anthropic"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_compat_max_tokens: int = 4096
    llm_enabled: bool = True
    llm_model: str = "claude-opus-5"
    llm_effort: str = "medium"
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 60.0
    # Opt in to Anthropic's server-side refusal fallback (see README).
    llm_use_fallbacks: bool = True
    prompt_version: str = "v1"
    # Rough USD prices per million tokens, used only for cost reporting.
    llm_input_price_per_mtok: float = 5.0
    llm_output_price_per_mtok: float = 25.0

    # --- Cache -------------------------------------------------------------
    cache_max_entries: int = 5000  # in-memory LRU in front of the DB cache

    # --- Persistence & security --------------------------------------------
    database_url: str = f"sqlite:///{DATA_DIR / 'assessments.db'}"
    # True on Vercel (VERCEL=1): a read-only, ephemeral filesystem, so SQLite
    # and the generated development key can't be used.
    on_vercel: bool = False
    # Fernet key used to encrypt stored responses at rest.
    response_encryption_key: str | None = None
    dev_key_path: Path = DATA_DIR / ".dev_encryption_key"
    # Optional machine access (scripts / integrations) via the X-API-Key
    # header. People sign in with admin accounts instead.
    admin_api_key: str | None = None
    # Required to create the first admin account from the browser in
    # production (or use `python manage.py create-admin`).
    admin_setup_token: str | None = None

    # --- Platform ------------------------------------------------------------
    # Base URL used in employee links, e.g. https://assess.example.com.
    # Defaults to the address the admin is using.
    public_base_url: str | None = None
    organization_name: str = "Acme Corporation"
    support_email: str = "support@example.com"
    support_phone: str = "+91 80 0000 0000"
    invitation_default_days: int = 14
    # Minutes allowed after the timer ends before a submission is marked late.
    submission_grace_minutes: int = 5
    test_duration_minutes: int = 45
    frontend_dist: Path = BASE_DIR.parent / "dist"
    cors_origins: tuple[str, ...] = field(default_factory=lambda: ("http://localhost:5173",))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_available(self) -> bool:
        """True when environment variables configure an LLM provider."""
        if not self.llm_enabled:
            return False
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return bool(self.llm_api_key) or self.llm_provider in ("ollama", "custom")

    def validate(self) -> list[str]:
        """Return a list of configuration problems (empty when valid)."""
        problems: list[str] = []
        if self.scale_points < 2:
            problems.append("ASSESSMENT_SCALE_POINTS must be >= 2")
        if self.llm_effort not in ("low", "medium", "high", "xhigh", "max"):
            problems.append("LLM_EFFORT must be one of low|medium|high|xhigh|max")
        if self.anthropic_api_key is not None and not validate_api_key_format(self.anthropic_api_key):
            problems.append("ANTHROPIC_API_KEY does not look like an Anthropic API key (sk-ant-...)")
        if self.on_vercel:
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL is not set. On Vercel the filesystem is read-only, so add a Postgres "
                                "database (Vercel Storage -> Neon) and set DATABASE_URL")
            if not self.response_encryption_key:
                problems.append("RESPONSE_ENCRYPTION_KEY is not set. Generate one with: python -c \"from "
                                "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        elif self.is_production:
            if not self.response_encryption_key:
                problems.append("RESPONSE_ENCRYPTION_KEY is required in production")
            if self.public_base_url and not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL should use https:// in production")
        return problems


def validate_api_key_format(key: str) -> bool:
    """Cheap offline sanity check; the API itself is the source of truth."""
    return key.startswith("sk-ant-") and len(key) > 20 and key.strip() == key


def load_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    origins = _env("CORS_ORIGINS", "http://localhost:5173") or ""
    return Settings(
        environment=_env("APP_ENV", "development") or "development",
        question_bank_path=Path(_env("QUESTION_BANK_PATH", str(DATA_DIR / "question_bank.json"))),
        norms_path=Path(_env("NORMS_PATH", str(DATA_DIR / "norms.json"))),
        scale_points=_env_int("ASSESSMENT_SCALE_POINTS", 6),
        min_answered=_env_int("MIN_ANSWERED", 170),
        min_distinct_options=_env_int("MIN_DISTINCT_OPTIONS", 3),
        max_mean_fraction=_env_float("MAX_MEAN_FRACTION", 0.75),
        max_middle_fraction=_env_float("MAX_MIDDLE_FRACTION", 0.50),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        llm_provider=_env("LLM_PROVIDER", "anthropic") or "anthropic",
        llm_api_key=_env("LLM_API_KEY"),
        llm_base_url=_env("LLM_BASE_URL"),
        llm_compat_max_tokens=_env_int("LLM_COMPAT_MAX_TOKENS", 4096),
        llm_enabled=_env_bool("LLM_ENABLED", True),
        llm_model=_env("LLM_MODEL", "claude-opus-5") or "claude-opus-5",
        llm_effort=_env("LLM_EFFORT", "medium") or "medium",
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 16000),
        llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 60.0),
        llm_use_fallbacks=_env_bool("LLM_USE_FALLBACKS", True),
        prompt_version=_env("LLM_PROMPT_VERSION", "v1") or "v1",
        llm_input_price_per_mtok=_env_float("LLM_INPUT_PRICE_PER_MTOK", 5.0),
        llm_output_price_per_mtok=_env_float("LLM_OUTPUT_PRICE_PER_MTOK", 25.0),
        cache_max_entries=_env_int("LLM_CACHE_MAX_ENTRIES", 5000),
        database_url=normalize_database_url(_env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'assessments.db'}") or ""),
        on_vercel=bool(_env("VERCEL")),
        response_encryption_key=_env("RESPONSE_ENCRYPTION_KEY"),
        admin_api_key=_env("ADMIN_API_KEY"),
        admin_setup_token=_env("ADMIN_SETUP_TOKEN"),
        public_base_url=(_env("PUBLIC_BASE_URL") or "").rstrip("/") or None,
        organization_name=_env("ORGANIZATION_NAME", "Acme Corporation") or "Acme Corporation",
        support_email=_env("SUPPORT_EMAIL", "support@example.com") or "support@example.com",
        support_phone=_env("SUPPORT_PHONE", "+91 80 0000 0000") or "+91 80 0000 0000",
        invitation_default_days=_env_int("INVITATION_DEFAULT_DAYS", 14),
        submission_grace_minutes=_env_int("SUBMISSION_GRACE_MINUTES", 5),
        test_duration_minutes=_env_int("TEST_DURATION_MINUTES", 45),
        frontend_dist=Path(_env("FRONTEND_DIST", str(BASE_DIR.parent / "dist"))),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )


settings = load_settings()
