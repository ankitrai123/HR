"""Hybrid psychometric scoring and reporting engine.

Two layers:

1. Deterministic core (always available, no network):
   QuestionBank -> ResponseValidator -> HybridScoringEngine (raw -> Sten)
   -> HybridReportGenerator.standard_report() using the INTERPRETATIONS library.

2. Optional LLM layer (premium reports):
   ClaudeInterpreter generates personalised text via the Anthropic API.
   LLMInterpretationCache stores every generation keyed only on
   non-identifying inputs (dimension + level, or the profile's level vector),
   so the same text is reused across candidates and most premium reports
   need zero API calls. Any LLM failure falls back to pre-written text.

Psychometric notes
------------------
* Items are Likert-scored 1..K. Reverse-keyed items are flipped (K + 1 - x)
  so a higher keyed score always means "more of the trait".
* A dimension's raw score is the mean keyed score of its answered items.
  It is rescaled to a 0..1 proportion so norms are independent of K.
* Sten ("standard ten") scores place a candidate relative to a norm group:
  z = (proportion - norm_mean) / norm_sd, then sten bands are half a
  standard deviation wide, centred on 5.5 (sten = 2z + 5.5, clipped 1..10).
* The shipped norms are PROVISIONAL placeholders. Calibrate them from real
  candidate data with HybridScoringEngine.compute_norms() before relying on
  Sten scores; see docs/ARCHITECTURE.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from config import Settings, settings as default_settings
from llm_providers import AnthropicProvider, LLMProvider, LLMUnavailable, provider_from_env

log = logging.getLogger("assessment.engine")

# ---------------------------------------------------------------------------
# Static psychometric tables
# ---------------------------------------------------------------------------

# Upper z-score bound for stens 1..9; anything above the last bound is sten 10.
# Equivalent to sten = round-down(2z + 5.5) clipped to 1..10.
STEN_TABLE: tuple[tuple[float, int], ...] = (
    (-2.0, 1), (-1.5, 2), (-1.0, 3), (-0.5, 4), (0.0, 5),
    (0.5, 6), (1.0, 7), (1.5, 8), (2.0, 9),
)

LOW, MODERATE, HIGH = "Low", "Moderate", "High"

# Provisional norms (on the 0..1 proportion scale) used until real candidate
# data is available. Self-report personality items typically skew positive,
# hence a mean above the scale midpoint.
DEFAULT_NORM = {"mean": 0.62, "sd": 0.13}

INTERPRETATIONS: dict[str, dict[str, str]] = {
    "Ethical Propensity": {
        LOW: "Tends to take a flexible view of rules and procedures and may bend them when they seem to get in the way. Clear guidelines and accountability help keep conduct consistent.",
        MODERATE: "Somewhat likely to act in a trustworthy manner and follow established norms, though may occasionally prioritise expedience over procedure under pressure.",
        HIGH: "Consistently holds high standards of honesty and integrity, follows rules and procedures, and is likely to challenge unethical behaviour when it arises.",
    },
    "Initiative Taking": {
        LOW: "Prefers direction and structure from others before acting, and may wait for problems to be assigned rather than taking them on proactively.",
        MODERATE: "Takes initiative on familiar tasks and within their own area, but may look to others for a lead on ambiguous or unassigned work.",
        HIGH: "Acts proactively, identifies problems without prompting, seeks out learning and works comfortably with minimal supervision.",
    },
    "Adaptability": {
        LOW: "May find frequent change, uncertainty or setbacks unsettling and prefers stable, predictable routines and working methods.",
        MODERATE: "Generally copes with change and pressure, though sudden shifts or repeated setbacks may take some time to absorb.",
        HIGH: "Adjusts readily to changing priorities, stays composed under uncertainty and pressure, and recovers quickly from setbacks.",
    },
    "Team Work": {
        LOW: "Tends to prefer working independently and may place individual goals ahead of collective ones; may need encouragement to seek or offer help.",
        MODERATE: "Cooperates well with colleagues on shared goals while retaining a preference for owning their individual contribution.",
        HIGH: "Puts team success ahead of personal recognition, supports colleagues willingly, shares credit and moves past conflicts quickly.",
    },
    "Networking": {
        LOW: "More comfortable in small, familiar groups; building new relationships and large social settings may feel draining.",
        MODERATE: "Builds relationships when needed and is comfortable with most people, though may not actively seek out new contacts.",
        HIGH: "Builds rapport quickly, enjoys meeting people from different backgrounds and actively maintains a broad professional network.",
    },
    "Negotiation & Influence": {
        LOW: "May hesitate to assert views or challenge others and can find it harder to read interpersonal cues in tense discussions.",
        MODERATE: "Can express views and persuade others in familiar situations, but may hold back when facing senior or strongly opinionated people.",
        HIGH: "Expresses views confidently, reads others' emotions well, stays calm in disagreements and brings people round to their position.",
    },
    "Service Orientation": {
        LOW: "May trade quality or attention to detail for speed and may not always look beyond the immediate task to the needs of others.",
        MODERATE: "Delivers dependable quality and attends to others' needs, with occasional lapses in detail under time pressure.",
        HIGH: "Holds high standards of quality and precision, listens attentively and finds meaning in serving others through their work.",
    },
    "Result Orientation": {
        LOW: "May be less driven by targets and deadlines and can lose focus on long or repetitive tasks.",
        MODERATE: "Works towards goals and deadlines reliably, with motivation that may vary depending on the task.",
        HIGH: "Strongly goal-driven, tracks progress, stays focused on monotonous work and consistently delivers on time.",
    },
    "Leading by Example": {
        LOW: "May doubt their own abilities or look to others to set the standard, and may be reluctant to take visible ownership.",
        MODERATE: "Generally dependable and accountable, and is starting to model the standards they expect from others.",
        HIGH: "Self-assured and accountable, keeps commitments, owns outcomes and inspires others through their own conduct.",
    },
    "Innovation": {
        LOW: "Prefers proven methods and predictable outcomes and may be cautious about novel ideas or risk-taking.",
        MODERATE: "Open to new ideas when their value is clear, balancing creativity with a preference for tested approaches.",
        HIGH: "Curious and original, welcomes new ideas, challenges conventions and treats calculated risk as an opportunity.",
    },
    "Strategic Orientation": {
        LOW: "Tends to decide on instinct or in the moment and may give less weight to evidence, planning and long-term consequences.",
        MODERATE: "Uses evidence and planning for important decisions, while sometimes relying on intuition or deliberating longer than needed.",
        HIGH: "Plans ahead, weighs evidence and alternative viewpoints, anticipates consequences and decides with confidence.",
    },
}


def level_for_sten(sten: int) -> str:
    """Map a Sten score to its band: 1-4 Low, 5-6 Moderate, 7-10 High."""
    if sten <= 4:
        return LOW
    if sten <= 6:
        return MODERATE
    return HIGH


def z_to_sten(z: float) -> int:
    for upper, sten in STEN_TABLE:
        if z < upper:
            return sten
    return 10


def z_to_percentile(z: float) -> float:
    """Percentile of a normal distribution, rounded to one decimal."""
    return round(50.0 * (1.0 + math.erf(z / math.sqrt(2.0))), 1)


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    id: int
    text: str
    dimension: str
    reverse_keyed: bool


@dataclass
class QuestionBank:
    items: dict[int, Item]
    dimensions: list[dict[str, str]]
    key_status: str = "provisional"
    instrument: str = "personality_map"

    @classmethod
    def load(cls, path: Path) -> "QuestionBank":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = {
            it["id"]: Item(it["id"], it["text"], it["dimension"], bool(it.get("reverse_keyed")))
            for it in raw["items"]
        }
        bank = cls(items=items, dimensions=raw["dimensions"], key_status=raw.get("key_status", "unknown"),
                   instrument=raw.get("instrument", "personality_map"))
        unknown = {it.dimension for it in items.values()} - set(bank.dimension_names)
        if unknown:
            raise ValueError(f"items reference unknown dimensions: {sorted(unknown)}")
        return bank

    @property
    def dimension_names(self) -> list[str]:
        return [d["name"] for d in self.dimensions]

    def category_of(self, dimension: str) -> str:
        return next(d["category"] for d in self.dimensions if d["name"] == dimension)

    def items_for(self, dimension: str) -> list[Item]:
        return [it for it in self.items.values() if it.dimension == dimension]

    def __len__(self) -> int:
        return len(self.items)


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------


@dataclass
class QualityCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class ValidationResult:
    complete: bool
    checks: list[QualityCheck]

    @property
    def quality(self) -> str:
        return "Genuine" if all(c.passed for c in self.checks) else "Questionable"

    @property
    def flags(self) -> list[str]:
        return [c.detail for c in self.checks if not c.passed]


class ResponseValidator:
    """Four response-quality checks.

    completeness       enough items answered for reliable scores
    variety            candidate used more than a couple of options
    social desirability raw mean isn't implausibly close to "strongly agree"
    central tendency   candidate didn't hide in the middle of the scale
    """

    def __init__(self, bank: QuestionBank, cfg: Settings = default_settings):
        self.bank = bank
        self.cfg = cfg

    def middle_options(self) -> set[int]:
        k = self.cfg.scale_points
        return {(k + 1) // 2} if k % 2 else {k // 2, k // 2 + 1}

    def normalise(self, responses: Mapping[Any, Any]) -> dict[int, int]:
        """Coerce keys to ints and reject unknown items / out-of-range values."""
        clean: dict[int, int] = {}
        for key, value in responses.items():
            try:
                qid = int(key)
            except (TypeError, ValueError):
                raise ValueError(f"question id {key!r} is not an integer") from None
            if qid not in self.bank.items:
                raise ValueError(f"unknown question id {qid}")
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= self.cfg.scale_points:
                raise ValueError(f"response to question {qid} must be an integer 1..{self.cfg.scale_points}")
            clean[qid] = value
        return clean

    def validate(self, responses: Mapping[int, int]) -> ValidationResult:
        cfg = self.cfg
        values = list(responses.values())
        n = len(values)
        k = cfg.scale_points

        answered_ok = n >= min(cfg.min_answered, len(self.bank))
        checks = [
            QualityCheck("completeness", answered_ok,
                         f"Only {n} of {len(self.bank)} questions answered (minimum {cfg.min_answered})."),
        ]
        if n == 0:
            return ValidationResult(False, checks)

        distinct = len(set(values))
        checks.append(QualityCheck("response_variety", distinct >= cfg.min_distinct_options,
                                   f"Only {distinct} distinct response option(s) used (minimum {cfg.min_distinct_options})."))

        mean = sum(values) / n
        ceiling = 1 + cfg.max_mean_fraction * (k - 1)
        checks.append(QualityCheck("social_desirability", mean <= ceiling,
                                   f"Average response {mean:.2f} exceeds {ceiling:.2f}, suggesting socially desirable responding."))

        middle = self.middle_options()
        middle_share = sum(v in middle for v in values) / n
        checks.append(QualityCheck("central_tendency", middle_share <= cfg.max_middle_fraction,
                                   f"{middle_share:.0%} of responses were middle options (maximum {cfg.max_middle_fraction:.0%})."))
        return ValidationResult(answered_ok, checks)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    dimension: str
    category: str
    items_answered: int
    raw_score: float  # mean keyed score on 1..K
    proportion: float  # raw score rescaled to 0..1
    sten_score: int
    level: str
    percentile: float


class HybridScoringEngine:
    """Raw keyed scores -> 0..1 proportion -> z against norms -> Sten."""

    def __init__(self, bank: QuestionBank, cfg: Settings = default_settings,
                 norms: Mapping[str, Mapping[str, float]] | None = None):
        self.bank = bank
        self.cfg = cfg
        self.norms = dict(norms) if norms is not None else self._load_norms(cfg.norms_path)

    def _load_norms(self, path: Path) -> dict[str, dict[str, float]]:
        if Path(path).is_file():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            log.info("loaded calibrated norms from %s", path)
            return data["dimensions"]
        return {}

    @property
    def norms_status(self) -> str:
        return "calibrated" if self.norms else "provisional"

    def norm_for(self, dimension: str) -> Mapping[str, float]:
        return self.norms.get(dimension, DEFAULT_NORM)

    def keyed_value(self, item: Item, value: int) -> int:
        return self.cfg.scale_points + 1 - value if item.reverse_keyed else value

    def score(self, responses: Mapping[int, int]) -> dict[str, DimensionScore]:
        k = self.cfg.scale_points
        results: dict[str, DimensionScore] = {}
        for dim in self.bank.dimension_names:
            keyed = [self.keyed_value(it, responses[it.id]) for it in self.bank.items_for(dim) if it.id in responses]
            if not keyed:
                continue
            raw = sum(keyed) / len(keyed)
            proportion = (raw - 1) / (k - 1)
            norm = self.norm_for(dim)
            z = (proportion - norm["mean"]) / norm["sd"]
            sten = z_to_sten(z)
            results[dim] = DimensionScore(
                dimension=dim, category=self.bank.category_of(dim), items_answered=len(keyed),
                raw_score=round(raw, 3), proportion=round(proportion, 4), sten_score=sten,
                level=level_for_sten(sten), percentile=z_to_percentile(z),
            )
        return results

    @staticmethod
    def compute_norms(proportion_rows: Iterable[Mapping[str, float]], min_sample: int = 30) -> dict[str, Any]:
        """Build a norms table from stored candidates' dimension proportions.

        Save the result as JSON at settings.norms_path to switch the engine
        from provisional to calibrated norms.
        """
        by_dim: dict[str, list[float]] = {}
        for row in proportion_rows:
            for dim, p in row.items():
                by_dim.setdefault(dim, []).append(p)
        if not by_dim or min(len(v) for v in by_dim.values()) < min_sample:
            raise ValueError(f"need at least {min_sample} scored assessments per dimension to compute norms")
        dims = {}
        for dim, vals in by_dim.items():
            mean = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
            dims[dim] = {"mean": round(mean, 4), "sd": round(max(sd, 1e-3), 4), "n": len(vals)}
        return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dimensions": dims}


# ---------------------------------------------------------------------------
# LLM cache
# ---------------------------------------------------------------------------


class CacheStore(Protocol):
    """Optional persistent backend (e.g. the database) behind the LRU."""

    def get(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, kind: str, value: dict[str, Any], model: str) -> None: ...


class LLMInterpretationCache:
    """Thread-safe LRU cache with an optional persistent store and
    single-flight de-duplication, so concurrent requests for the same key
    trigger at most one API call."""

    def __init__(self, max_entries: int = 5000, store: CacheStore | None = None):
        self.max_entries = max_entries
        self.store = store
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Lock] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(kind: str, payload: Mapping[str, Any], model: str, prompt_version: str) -> str:
        blob = json.dumps({"kind": kind, "payload": payload, "model": model, "v": prompt_version}, sort_keys=True)
        return f"{kind}:{hashlib.sha256(blob.encode()).hexdigest()[:32]}"

    def _get_local(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        return None

    def _put_local(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def get_or_create(self, key: str, kind: str, model: str,
                      factory: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        """Return (value, was_cached). `factory` runs only on a true miss."""
        value = self._get_local(key)
        if value is None and self.store is not None:
            value = self.store.get(key)
            if value is not None:
                self._put_local(key, value)
        if value is not None:
            with self._lock:
                self.hits += 1
            return value, True

        with self._lock:
            key_lock = self._inflight.setdefault(key, threading.Lock())
        try:
            with key_lock:
                value = self._get_local(key)  # another thread may have filled it
                if value is not None:
                    with self._lock:
                        self.hits += 1
                    return value, True
                with self._lock:
                    self.misses += 1
                value = factory()
                self._put_local(key, value)
                if self.store is not None:
                    self.store.set(key, kind, value, model)
                return value, False
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries_in_memory": len(self._data),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else None,
            }


# ---------------------------------------------------------------------------
# Claude interpreter
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You are an experienced occupational psychologist writing feedback for a workplace personality assessment.

The assessment measures 11 competency dimensions on Sten scores, grouped into three levels: Low (Sten 1-4), Moderate (5-6), High (7-10). Scores describe self-reported preferences relative to a norm group; they are not measures of ability, and neither end of a scale is "bad".

Write in plain, professional British English, addressed to the candidate in the second person. Be specific, balanced and practical. Do not diagnose, do not mention clinical conditions, and do not make hiring recommendations. Never invent scores or facts beyond what you are given."""

DIMENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string", "description": "2-3 sentences interpreting this level of the dimension."},
        "development_actions": {"type": "array", "items": {"type": "string"},
                                "description": "3 concrete, workplace-focused actions."},
        "coaching_insight": {"type": "string", "description": "One sentence a coach could use to open a conversation."},
    },
    "required": ["interpretation", "development_actions", "coaching_insight"],
    "additionalProperties": False,
}

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string", "description": "A 120-180 word summary of the overall profile."},
        "coaching_insights": {"type": "array", "items": {"type": "string"},
                              "description": "3-4 insights that connect dimensions to each other."},
    },
    "required": ["executive_summary", "coaching_insights"],
    "additionalProperties": False,
}


COHORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "A 100-150 word overview of the group."},
        "observations": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "observations", "recommendations"],
    "additionalProperties": False,
}

COHORT_SYSTEM_PROMPT = """You are an experienced occupational psychologist advising a hiring team on aggregated personality assessment results.

Scores are Sten scores (1-10) on 11 competency dimensions; levels are Low (1-4), Moderate (5-6) and High (7-10). Describe group-level patterns only; never speculate about individuals, protected characteristics or clinical conditions, and do not recommend hiring or rejecting anyone. Write in plain, professional British English."""


@dataclass
class UsageTracker:
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.api_calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1


class LLMInterpreter:
    """Generates personalised text through the configured LLM provider
    (Claude, NVIDIA NIM, OpenAI, Gemini, ... see llm_providers.py).

    Only non-identifying data is sent: dimension names, levels and the
    pre-written interpretation. Candidate names, emails and raw item
    responses never leave the service.
    """

    def __init__(self, cfg: Settings = default_settings, provider: LLMProvider | None = None, client: Any = None,
                 input_price_per_mtok: float | None = None, output_price_per_mtok: float | None = None):
        self.cfg = cfg
        self.usage = UsageTracker()
        if provider is None and client is not None:
            provider = AnthropicProvider(cfg, client=client)  # injected SDK client (tests)
        self.provider = provider if provider is not None else provider_from_env(cfg)
        self.source = "environment" if self.provider is not None else "none"
        self.input_price = cfg.llm_input_price_per_mtok if input_price_per_mtok is None else input_price_per_mtok
        self.output_price = cfg.llm_output_price_per_mtok if output_price_per_mtok is None else output_price_per_mtok
        self._lock = threading.Lock()

    def set_provider(self, provider: LLMProvider | None, source: str,
                     input_price_per_mtok: float | None = None, output_price_per_mtok: float | None = None) -> None:
        """Hot-swap the provider (e.g. after an admin saves a new API key)."""
        with self._lock:
            self.provider = provider
            self.source = source if provider is not None else "none"
            self.input_price = input_price_per_mtok or 0.0
            self.output_price = output_price_per_mtok or 0.0

    @property
    def available(self) -> bool:
        return self.provider is not None

    @property
    def cache_model_id(self) -> str:
        return self.provider.cache_id if self.provider else "none"

    def describe(self) -> dict[str, Any]:
        p = self.provider
        return {"available": p is not None, "provider": p.id if p else None,
                "provider_label": p.spec.label if p else None, "model": p.model if p else None,
                "source": self.source}

    def _call(self, prompt: str, schema: dict[str, Any], system: str = SYSTEM_PROMPT) -> dict[str, Any]:
        provider = self.provider
        if provider is None:
            raise LLMUnavailable("no LLM provider configured")
        try:
            result = provider.generate_json(system, prompt, schema)
        except LLMUnavailable as exc:
            self.usage.record_failure()
            if exc.result is not None:
                self.usage.record(exc.result.input_tokens, exc.result.output_tokens)
            raise
        self.usage.record(result.input_tokens, result.output_tokens)
        return result.data

    def dimension_insight(self, dimension: str, category: str, level: str) -> dict[str, Any]:
        prompt = (
            f"Dimension: {dimension} (category: {category})\n"
            f"Candidate level: {level}\n"
            f"Standard interpretation: {INTERPRETATIONS[dimension][level]}\n\n"
            "Write a richer interpretation of what this level typically looks like at work, "
            "three development actions suited to this level, and one coaching insight."
        )
        return self._call(prompt, DIMENSION_SCHEMA)

    def profile_narrative(self, levels: Mapping[str, str]) -> dict[str, Any]:
        lines = "\n".join(f"- {dim}: {lvl}" for dim, lvl in levels.items())
        prompt = (
            "Here is a candidate's profile across the 11 dimensions (levels only):\n"
            f"{lines}\n\n"
            "Write an executive summary of the profile and 3-4 coaching insights that "
            "explain how the strengths and development areas interact."
        )
        return self._call(prompt, PROFILE_SCHEMA)

    def cohort_analysis(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        prompt = (
            "Below are aggregated, anonymised results for a group of candidates (no individual data).\n"
            f"{json.dumps(summary, indent=1, sort_keys=True)}\n\n"
            "Write a short analysis for the hiring team: an overall summary, 3-5 notable observations "
            "about the group's strengths and gaps, and 3-5 practical recommendations (e.g. onboarding, "
            "training, team composition). If the norms or scoring key are provisional, say that the "
            "patterns are indicative only."
        )
        return self._call(prompt, COHORT_SCHEMA, system=COHORT_SYSTEM_PROMPT)

    def estimated_cost_usd(self) -> float:
        return round(self.usage.input_tokens / 1e6 * self.input_price
                     + self.usage.output_tokens / 1e6 * self.output_price, 6)


# Backwards-compatible name: ClaudeInterpreter(cfg, client=anthropic_client).
ClaudeInterpreter = LLMInterpreter


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass
class AssessmentInput:
    test_taker_id: str
    name: str
    email: str | None
    responses: dict[int, int]


class HybridReportGenerator:
    """Builds standard (deterministic) and premium (LLM-enhanced) reports."""

    def __init__(self, bank: QuestionBank | None = None, cfg: Settings = default_settings,
                 interpreter: ClaudeInterpreter | None = None, cache: LLMInterpretationCache | None = None,
                 norms: Mapping[str, Mapping[str, float]] | None = None):
        self.cfg = cfg
        self.bank = bank or QuestionBank.load(cfg.question_bank_path)
        self.validator = ResponseValidator(self.bank, cfg)
        self.engine = HybridScoringEngine(self.bank, cfg, norms=norms)
        self.interpreter = interpreter or ClaudeInterpreter(cfg)
        self.cache = cache or LLMInterpretationCache(cfg.cache_max_entries)

    # -- standard ---------------------------------------------------------

    def standard_report(self, data: AssessmentInput) -> dict[str, Any]:
        started = time.perf_counter()
        responses = self.validator.normalise(data.responses)
        validation = self.validator.validate(responses)

        report: dict[str, Any] = {
            "test_id": data.test_taker_id,
            "name": data.name,
            "status": "Completed" if validation.complete else "Incomplete",
            "response_quality": validation.quality,
            "quality_flags": validation.flags,
            "questions_answered": len(responses),
            "norms": self.engine.norms_status,
            "scoring_key": self.bank.key_status,
            "api_calls_made": 0,
        }
        if validation.complete:
            scores = self.engine.score(responses)
            report["scores"] = {
                dim: {
                    "category": s.category,
                    "sten_score": s.sten_score,
                    "level": s.level,
                    "percentile": s.percentile,
                    "raw_score": s.raw_score,
                    "interpretation": INTERPRETATIONS[dim][s.level],
                }
                for dim, s in scores.items()
            }
            report["strengths"] = [d for d, s in scores.items() if s.level == HIGH]
            report["areas_of_development"] = [d for d, s in scores.items() if s.level == LOW]
            report["profile_summary"] = self._profile_summary(report["strengths"], report["areas_of_development"], len(scores))
            report["_proportions"] = {d: s.proportion for d, s in scores.items()}
        else:
            report.update(scores={}, strengths=[], areas_of_development=[],
                          profile_summary="Not enough questions were answered to produce a reliable profile.")
        report["completion_time_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return report

    @staticmethod
    def _profile_summary(strengths: list[str], development: list[str], total: int) -> str:
        def join(items: list[str]) -> str:
            return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

        parts = []
        if strengths:
            parts.append(f"Shows clear strengths in {join(strengths)}, which can be drawn on at work.")
        if development:
            verb = "is an area" if len(development) == 1 else "are areas"
            parts.append(f"{join(development)} {verb} where focused development would have the greatest impact.")
        moderate = total - len(strengths) - len(development)
        if moderate == total:
            parts.append("The profile is balanced, with every dimension in the moderate range of the comparison group.")
        elif moderate:
            noun = "dimension sits" if moderate == 1 else "dimensions sit"
            parts.append(f"The remaining {moderate} {noun} in the moderate range of the comparison group.")
        return " ".join(parts)

    # -- premium ----------------------------------------------------------

    def premium_report(self, data: AssessmentInput, standard: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        report = dict(standard) if standard is not None else self.standard_report(data)
        if report["status"] != "Completed":
            report["premium_features"] = {"error": "Premium features need a completed assessment.", "api_calls_made": 0}
            return report

        calls_before = self.interpreter.usage.api_calls
        cost_before = self.interpreter.estimated_cost_usd()
        scores = report["scores"]
        sources: set[str] = set()

        def insight(dim: str) -> tuple[str, dict[str, Any]]:
            level = scores[dim]["level"]
            value, source = self._cached_or_fallback(
                kind="dimension",
                payload={"dimension": dim, "level": level},
                generate=lambda: self.interpreter.dimension_insight(dim, scores[dim]["category"], level),
                fallback=lambda: self._fallback_dimension(dim, level),
            )
            sources.add(source)
            return dim, value

        # Fresh generations run in parallel; cached ones return immediately.
        with ThreadPoolExecutor(max_workers=6) as pool:
            insights = dict(pool.map(insight, scores))

        levels = {dim: scores[dim]["level"] for dim in self.bank.dimension_names if dim in scores}
        narrative, source = self._cached_or_fallback(
            kind="profile",
            payload={"levels": levels},
            generate=lambda: self.interpreter.profile_narrative(levels),
            fallback=lambda: self._fallback_profile(report),
        )
        sources.add(source)

        focus = report["areas_of_development"] or sorted(scores, key=lambda d: scores[d]["sten_score"])[:2]
        api_calls = self.interpreter.usage.api_calls - calls_before
        report["premium_features"] = {
            "executive_summary": narrative["executive_summary"],
            "development_plan": [{"dimension": d, "actions": insights[d]["development_actions"]} for d in focus],
            "coaching_insights": narrative["coaching_insights"] + [insights[d]["coaching_insight"] for d in focus],
            "dimension_insights": {d: v["interpretation"] for d, v in insights.items()},
            "content_source": "llm" if sources == {"llm"} else "fallback" if sources == {"fallback"} else "mixed",
            "generated_by": self.interpreter.describe() if "llm" in sources else None,
            "api_calls_made": api_calls,
            "estimated_cost_usd": round(self.interpreter.estimated_cost_usd() - cost_before, 6),
            "generation_time_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        report["api_calls_made"] = api_calls
        return report

    def _cached_or_fallback(self, kind: str, payload: dict[str, Any], generate: Callable[[], dict[str, Any]],
                            fallback: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], str]:
        """Cache first, then the LLM, then pre-written text. Never raises."""
        if not self.interpreter.available:
            return fallback(), "fallback"
        model_id = self.interpreter.cache_model_id
        key = LLMInterpretationCache.make_key(kind, payload, model_id, self.cfg.prompt_version)
        try:
            value, _ = self.cache.get_or_create(key, kind, model_id, generate)
            return value, "llm"
        except LLMUnavailable as exc:
            log.warning("LLM %s generation failed, using fallback: %s", kind, exc)
        except Exception:  # never let a premium feature break the report
            log.exception("unexpected LLM error; using fallback")
        return fallback(), "fallback"

    @staticmethod
    def _fallback_dimension(dim: str, level: str) -> dict[str, Any]:
        actions = {
            LOW: [f"Pick one situation this month where {dim.lower()} matters and agree a specific goal with your manager.",
                  f"Observe a colleague who is strong in {dim.lower()} and note two behaviours to try.",
                  "Review progress with a mentor every two weeks."],
            MODERATE: [f"Identify where {dim.lower()} already works well for you and apply it to a new context.",
                       "Ask for specific feedback after a relevant task.",
                       "Set one stretch goal for the next quarter."],
            HIGH: [f"Use your strength in {dim.lower()} to support or mentor others.",
                   "Watch for over-use of this strength in situations that call for a different approach.",
                   "Take on a visible project that relies on this strength."],
        }[level]
        return {"interpretation": INTERPRETATIONS[dim][level], "development_actions": actions,
                "coaching_insight": f"What does {dim.lower()} look like for you on a good day at work?"}

    @staticmethod
    def _fallback_profile(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "executive_summary": report["profile_summary"],
            "coaching_insights": [
                "Build development plans around existing strengths rather than only fixing gaps.",
                "Discuss how the profile shows up in your current role with your manager or coach.",
            ],
        }

    # -- cohort -----------------------------------------------------------

    @staticmethod
    def cohort_summary(analytics: Mapping[str, Any], norms: str, scoring_key: str) -> dict[str, Any]:
        """Anonymised aggregate sent to the LLM for cohort analysis."""
        a = analytics["assessments"]
        dims = {}
        for dim, d in analytics["dimensions"].items():
            n = max(1, d["n"])
            dims[dim] = {"mean_sten": d["mean_sten"],
                         "pct_low": round(100 * d["levels"].get("Low", 0) / n),
                         "pct_moderate": round(100 * d["levels"].get("Moderate", 0) / n),
                         "pct_high": round(100 * d["levels"].get("High", 0) / n)}
        return {"candidates": a["total"], "completed": a["by_status"].get("Completed", 0),
                "flagged_responses": a["by_quality"].get("Questionable", 0),
                "norms": norms, "scoring_key": scoring_key, "dimensions": dims}

    def cohort_report(self, analytics: Mapping[str, Any]) -> dict[str, Any]:
        summary = self.cohort_summary(analytics, self.engine.norms_status, self.bank.key_status)
        calls_before = self.interpreter.usage.api_calls
        value, source = self._cached_or_fallback(
            kind="cohort", payload=summary,
            generate=lambda: self.interpreter.cohort_analysis(summary),
            fallback=lambda: self._fallback_cohort(summary),
        )
        return {**value, "content_source": source, "candidates": summary["candidates"],
                "generated_by": self.interpreter.describe() if source == "llm" else None,
                "api_calls_made": self.interpreter.usage.api_calls - calls_before}

    @staticmethod
    def _fallback_cohort(summary: Mapping[str, Any]) -> dict[str, Any]:
        ranked = sorted(summary["dimensions"].items(), key=lambda kv: kv[1]["mean_sten"], reverse=True)
        top = [d for d, _ in ranked[:3]]
        low = [d for d, _ in ranked[-3:]][::-1]
        caveat = (" Norms are provisional, so treat these patterns as indicative only."
                  if summary["norms"] == "provisional" else "")
        return {
            "summary": (f"Across {summary['candidates']} candidates, the highest average scores are in "
                        f"{', '.join(top)} and the lowest in {', '.join(low)}.{caveat}"),
            "observations": [f"{d}: mean Sten {v['mean_sten']}, {v['pct_high']}% high and {v['pct_low']}% low."
                             for d, v in ranked[:2] + ranked[-2:]],
            "recommendations": [f"Consider development support for {low[0]} during onboarding.",
                                "Configure an AI provider in the dashboard for a fuller written analysis."],
        }

    def stats(self) -> dict[str, Any]:
        u = self.interpreter.usage
        return {
            "llm_available": self.interpreter.available,
            "llm": self.interpreter.describe(),
            "llm_model": self.interpreter.provider.model if self.interpreter.provider else None,
            "api_calls": u.api_calls,
            "api_failures": u.failures,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "estimated_cost_usd": self.interpreter.estimated_cost_usd(),
            "cache": self.cache.stats(),
        }

    def warm_cache(self) -> int:
        """Pre-generate all dimension x level insights (33 calls at most).
        Returns the number of API calls made."""
        before = self.interpreter.usage.api_calls
        for dim in self.bank.dimension_names:
            for level in (LOW, MODERATE, HIGH):
                self._cached_or_fallback(
                    "dimension", {"dimension": dim, "level": level},
                    lambda d=dim, lv=level: self.interpreter.dimension_insight(d, self.bank.category_of(d), lv),
                    lambda d=dim, lv=level: self._fallback_dimension(d, lv),
                )
        return self.interpreter.usage.api_calls - before


def public_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Strip internal fields (prefixed with _) before returning to clients."""
    return {k: v for k, v in report.items() if not k.startswith("_")}


__all__ = [
    "AssessmentInput", "ClaudeInterpreter", "LLMInterpreter", "DimensionScore", "HybridReportGenerator", "HybridScoringEngine",
    "INTERPRETATIONS", "LLMInterpretationCache", "LLMUnavailable", "QuestionBank", "ResponseValidator",
    "STEN_TABLE", "level_for_sten", "public_report", "z_to_percentile", "z_to_sten",
]
