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
    # Fernet key used to encrypt stored responses at rest.
    response_encryption_key: str | None = None
    dev_key_path: Path = DATA_DIR / ".dev_encryption_key"
    # When set, every endpoint except POST /api/assess requires X-API-Key.
    admin_api_key: str | None = None
    cors_origins: tuple[str, ...] = field(default_factory=lambda: ("http://localhost:5173",))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)

    def validate(self) -> list[str]:
        """Return a list of configuration problems (empty when valid)."""
        problems: list[str] = []
        if self.scale_points < 2:
            problems.append("ASSESSMENT_SCALE_POINTS must be >= 2")
        if self.llm_effort not in ("low", "medium", "high", "xhigh", "max"):
            problems.append("LLM_EFFORT must be one of low|medium|high|xhigh|max")
        if self.anthropic_api_key is not None and not validate_api_key_format(self.anthropic_api_key):
            problems.append("ANTHROPIC_API_KEY does not look like an Anthropic API key (sk-ant-...)")
        if self.is_production:
            if not self.response_encryption_key:
                problems.append("RESPONSE_ENCRYPTION_KEY is required in production")
            if not self.admin_api_key:
                problems.append("ADMIN_API_KEY is required in production")
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
        database_url=_env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'assessments.db'}") or "",
        response_encryption_key=_env("RESPONSE_ENCRYPTION_KEY"),
        admin_api_key=_env("ADMIN_API_KEY"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )


settings = load_settings()
