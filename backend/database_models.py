"""SQLAlchemy models and persistence helpers.

Tables
------
test_takers      one row per candidate (external id, name, email)
assessments      one row per submission (status, quality, timings)
responses        the candidate's raw answers, Fernet-encrypted at rest,
                 plus a SHA-256 digest for integrity / duplicate checks
results          one row per scored dimension (for analytics queries)
llm_cache        persistent LLM generations shared across candidates

Raw answers are only ever stored encrypted and are never logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, create_engine,
                        func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from config import Settings, settings as default_settings

log = logging.getLogger("assessment.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TestTaker(Base):
    __tablename__ = "test_takers"
    __test__ = False  # not a pytest test class

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assessments: Mapped[list["Assessment"]] = relationship(back_populates="test_taker")


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    test_taker_id: Mapped[int] = mapped_column(ForeignKey("test_takers.id"), index=True)
    instrument: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # Completed | Incomplete
    response_quality: Mapped[str] = mapped_column(String(20))  # Genuine | Questionable
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    questions_answered: Mapped[int] = mapped_column(Integer)
    scale_points: Mapped[int] = mapped_column(Integer)
    norms: Mapped[str] = mapped_column(String(20))
    report: Mapped[dict[str, Any]] = mapped_column(JSON)  # standard report as returned to clients
    premium_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scoring_time_ms: Mapped[float] = mapped_column(Float)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    test_taker: Mapped[TestTaker] = relationship(back_populates="assessments")
    response: Mapped["Response"] = relationship(back_populates="assessment", uselist=False,
                                                cascade="all, delete-orphan")
    results: Mapped[list["Result"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class Response(Base):
    """Encrypted raw answers for one assessment."""

    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), unique=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    assessment: Mapped[Assessment] = relationship(back_populates="response")


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(30))
    raw_score: Mapped[float] = mapped_column(Float)
    proportion: Mapped[float] = mapped_column(Float)
    sten_score: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(10))
    percentile: Mapped[float] = mapped_column(Float)

    assessment: Mapped[Assessment] = relationship(back_populates="results")


class LLMCacheEntry(Base):
    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


class ResponseCipher:
    def __init__(self, key: str | bytes):
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls, cfg: Settings) -> "ResponseCipher":
        if cfg.response_encryption_key:
            return cls(cfg.response_encryption_key)
        if cfg.is_production:
            raise RuntimeError("RESPONSE_ENCRYPTION_KEY must be set in production")
        # Development convenience: a key persisted next to the database so
        # data stays readable across restarts. Never used in production.
        path = cfg.dev_key_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
            log.warning("generated development encryption key at %s; set RESPONSE_ENCRYPTION_KEY for real use", path)
        return cls(path.read_bytes())

    @staticmethod
    def digest(responses: Mapping[int, int]) -> str:
        canonical = json.dumps({str(k): v for k, v in sorted(responses.items())}, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def encrypt(self, responses: Mapping[int, int]) -> bytes:
        return self._fernet.encrypt(json.dumps({str(k): v for k, v in responses.items()}).encode())

    def decrypt(self, token: bytes) -> dict[int, int]:
        try:
            return {int(k): v for k, v in json.loads(self._fernet.decrypt(token)).items()}
        except InvalidToken as exc:
            raise RuntimeError("stored responses could not be decrypted with the configured key") from exc


# ---------------------------------------------------------------------------
# Database facade
# ---------------------------------------------------------------------------


class Database:
    def __init__(self, cfg: Settings = default_settings, url: str | None = None):
        url = url or cfg.database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, future=True)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False)
        self.cipher = ResponseCipher.from_settings(cfg)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # -- assessments --------------------------------------------------------

    def save_assessment(self, *, test_taker_id: str, name: str, email: str | None, instrument: str,
                        scale_points: int, responses: Mapping[int, int], report: Mapping[str, Any],
                        proportions: Mapping[str, float]) -> str:
        with self.session() as s:
            taker = s.scalar(select(TestTaker).where(TestTaker.external_id == test_taker_id))
            if taker is None:
                taker = TestTaker(external_id=test_taker_id, name=name, email=email)
                s.add(taker)
            else:
                taker.name, taker.email = name, email
            assessment = Assessment(
                test_taker=taker, instrument=instrument, status=report["status"],
                response_quality=report["response_quality"], quality_flags=report["quality_flags"],
                questions_answered=report["questions_answered"], scale_points=scale_points,
                norms=report["norms"], report=dict(report), scoring_time_ms=report["completion_time_ms"],
            )
            assessment.response = Response(ciphertext=self.cipher.encrypt(responses),
                                           sha256=self.cipher.digest(responses))
            for dim, sc in report.get("scores", {}).items():
                assessment.results.append(Result(
                    dimension=dim, category=sc["category"], raw_score=sc["raw_score"],
                    proportion=proportions[dim], sten_score=sc["sten_score"], level=sc["level"],
                    percentile=sc["percentile"],
                ))
            s.add(assessment)
            s.flush()
            return assessment.id

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        with self.session() as s:
            a = s.get(Assessment, assessment_id)
            if a is not None:
                _ = a.test_taker, a.response  # load before the session closes
            return a

    def latest_for_test_taker(self, external_id: str) -> Assessment | None:
        with self.session() as s:
            a = s.scalar(select(Assessment).join(TestTaker).where(TestTaker.external_id == external_id)
                         .order_by(Assessment.submitted_at.desc()).limit(1))
            if a is not None:
                _ = a.test_taker, a.response
            return a

    def get_responses(self, assessment_id: str) -> dict[int, int] | None:
        with self.session() as s:
            r = s.scalar(select(Response).where(Response.assessment_id == assessment_id))
            return self.cipher.decrypt(r.ciphertext) if r else None

    def save_premium_report(self, assessment_id: str, premium: Mapping[str, Any]) -> None:
        with self.session() as s:
            a = s.get(Assessment, assessment_id)
            if a is not None:
                a.premium_report = dict(premium)

    def proportion_rows(self) -> list[dict[str, float]]:
        """Per-assessment dimension proportions for norm calibration
        (genuine, completed assessments only)."""
        with self.session() as s:
            rows = s.execute(
                select(Result.assessment_id, Result.dimension, Result.proportion)
                .join(Assessment).where(Assessment.status == "Completed", Assessment.response_quality == "Genuine")
            ).all()
        by_assessment: dict[str, dict[str, float]] = {}
        for aid, dim, p in rows:
            by_assessment.setdefault(aid, {})[dim] = p
        return list(by_assessment.values())

    def analytics(self) -> dict[str, Any]:
        with self.session() as s:
            total = s.scalar(select(func.count()).select_from(Assessment)) or 0
            by_status = dict(s.execute(select(Assessment.status, func.count()).group_by(Assessment.status)).all())
            by_quality = dict(s.execute(
                select(Assessment.response_quality, func.count()).group_by(Assessment.response_quality)).all())
            premium = s.scalar(select(func.count()).select_from(Assessment)
                               .where(Assessment.premium_report.is_not(None))) or 0
            avg_ms = s.scalar(select(func.avg(Assessment.scoring_time_ms)))
            dims = s.execute(
                select(Result.dimension, func.count(), func.avg(Result.sten_score), func.min(Result.sten_score),
                       func.max(Result.sten_score))
                .group_by(Result.dimension)
            ).all()
            levels = s.execute(select(Result.dimension, Result.level, func.count())
                               .group_by(Result.dimension, Result.level)).all()
            sten_dist = s.execute(select(Result.sten_score, func.count()).group_by(Result.sten_score)).all()
            cache_entries = s.scalar(select(func.count()).select_from(LLMCacheEntry)) or 0
            cache_hits = s.scalar(select(func.sum(LLMCacheEntry.hits))) or 0

        level_map: dict[str, dict[str, int]] = {}
        for dim, level, n in levels:
            level_map.setdefault(dim, {"Low": 0, "Moderate": 0, "High": 0})[level] = n
        return {
            "assessments": {"total": total, "by_status": by_status, "by_quality": by_quality,
                            "premium_reports": premium,
                            "avg_scoring_time_ms": round(avg_ms, 2) if avg_ms is not None else None},
            "dimensions": {
                dim: {"n": n, "mean_sten": round(mean, 2), "min_sten": lo, "max_sten": hi,
                      "levels": level_map.get(dim, {})}
                for dim, n, mean, lo, hi in dims
            },
            "sten_distribution": {int(k): v for k, v in sorted(sten_dist)},
            "llm_cache": {"persistent_entries": cache_entries, "persistent_hits": int(cache_hits)},
        }


class DatabaseCacheStore:
    """Persistent LLM cache backend (implements engine.CacheStore)."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> dict[str, Any] | None:
        with self.db.session() as s:
            entry = s.get(LLMCacheEntry, key)
            if entry is None:
                return None
            entry.hits += 1
            return entry.value

    def set(self, key: str, kind: str, value: dict[str, Any], model: str) -> None:
        with self.db.session() as s:
            if s.get(LLMCacheEntry, key) is None:
                s.add(LLMCacheEntry(key=key, kind=kind, model=model, value=value))
