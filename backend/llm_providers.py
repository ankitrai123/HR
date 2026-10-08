"""LLM provider adapters.

Every provider exposes the same small interface used by the report engine:

    provider.generate_json(system, prompt, schema) -> ProviderResult
    provider.list_models() -> list[str]

* Anthropic (Claude) uses the official `anthropic` SDK with schema-constrained
  output.
* Everything else (NVIDIA NIM, OpenAI, Google Gemini, Groq, Mistral, DeepSeek,
  Together, OpenRouter, Fireworks, xAI, Perplexity, Ollama, or any custom
  endpoint) speaks the OpenAI-compatible Chat Completions protocol, so a single
  adapter covers them. JSON mode is requested where supported and the reply is
  validated against the schema either way.

Adapters raise LLMUnavailable for every failure so callers can fall back.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from config import Settings


class LLMUnavailable(RuntimeError):
    """Raised when the LLM can't produce usable output; callers fall back.
    `result` carries token usage when the provider billed for a failed call."""

    def __init__(self, message: str, result: "ProviderResult | None" = None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str  # "anthropic" | "openai_compatible"
    base_url: str | None
    model_hint: str
    key_hint: str
    requires_key: bool = True
    base_url_editable: bool = False
    token_param: str = "max_tokens"
    docs_url: str = ""


PROVIDERS: dict[str, ProviderSpec] = {p.id: p for p in [
    ProviderSpec("anthropic", "Anthropic (Claude)", "anthropic", None, "claude-opus-5", "sk-ant-…",
                 docs_url="https://console.anthropic.com/settings/keys"),
    ProviderSpec("nvidia", "NVIDIA NIM", "openai_compatible", "https://integrate.api.nvidia.com/v1",
                 "e.g. meta/llama-3.3-70b-instruct", "nvapi-…", docs_url="https://build.nvidia.com"),
    ProviderSpec("openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1",
                 "use “Fetch models”", "sk-…", token_param="max_completion_tokens",
                 docs_url="https://platform.openai.com/api-keys"),
    ProviderSpec("google", "Google Gemini", "openai_compatible",
                 "https://generativelanguage.googleapis.com/v1beta/openai", "e.g. gemini-2.5-flash", "AIza…",
                 docs_url="https://aistudio.google.com/apikey"),
    ProviderSpec("groq", "Groq", "openai_compatible", "https://api.groq.com/openai/v1",
                 "e.g. llama-3.3-70b-versatile", "gsk_…", docs_url="https://console.groq.com/keys"),
    ProviderSpec("mistral", "Mistral AI", "openai_compatible", "https://api.mistral.ai/v1",
                 "e.g. mistral-large-latest", "…", docs_url="https://console.mistral.ai/api-keys"),
    ProviderSpec("deepseek", "DeepSeek", "openai_compatible", "https://api.deepseek.com/v1",
                 "e.g. deepseek-chat", "sk-…", docs_url="https://platform.deepseek.com/api_keys"),
    ProviderSpec("together", "Together AI", "openai_compatible", "https://api.together.xyz/v1",
                 "use “Fetch models”", "…", docs_url="https://api.together.ai/settings/api-keys"),
    ProviderSpec("openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1",
                 "e.g. provider/model-name", "sk-or-…", docs_url="https://openrouter.ai/keys"),
    ProviderSpec("fireworks", "Fireworks AI", "openai_compatible", "https://api.fireworks.ai/inference/v1",
                 "use “Fetch models”", "fw_…", docs_url="https://fireworks.ai/account/api-keys"),
    ProviderSpec("xai", "xAI (Grok)", "openai_compatible", "https://api.x.ai/v1",
                 "use “Fetch models”", "xai-…", docs_url="https://console.x.ai"),
    ProviderSpec("perplexity", "Perplexity", "openai_compatible", "https://api.perplexity.ai",
                 "e.g. sonar", "pplx-…", docs_url="https://www.perplexity.ai/settings/api"),
    ProviderSpec("ollama", "Ollama (self-hosted)", "openai_compatible", "http://localhost:11434/v1",
                 "e.g. llama3.1", "not required", requires_key=False, base_url_editable=True,
                 docs_url="https://ollama.com"),
    ProviderSpec("custom", "Custom (OpenAI-compatible)", "openai_compatible", None,
                 "model id", "if required", requires_key=False, base_url_editable=True),
]}


@dataclass
class ProviderResult:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# JSON helpers (for providers without schema-constrained output)
# ---------------------------------------------------------------------------

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text, tolerating code fences,
    reasoning traces (<think>…</think>) and surrounding prose."""
    cleaned = _FENCE.sub("", _THINK.sub("", text).strip()).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable("response did not contain a JSON object") from None
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            raise LLMUnavailable("response was not valid JSON") from None
    if not isinstance(value, dict):
        raise LLMUnavailable("response JSON was not an object")
    return value


_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list}


def validate_schema(data: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    """Check the subset of JSON Schema our prompts use (required keys, simple
    types, arrays of strings) and drop unexpected keys."""
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in data:
            raise LLMUnavailable(f"response missing required field {key!r}")
    out: dict[str, Any] = {}
    for key, rule in props.items():
        if key not in data:
            continue
        value, expected = data[key], _TYPES.get(rule.get("type", ""), object)
        if not isinstance(value, expected):
            raise LLMUnavailable(f"field {key!r} should be {rule.get('type')}")
        if expected is list and rule.get("items", {}).get("type") == "string":
            if not all(isinstance(v, str) for v in value):
                raise LLMUnavailable(f"field {key!r} should be a list of strings")
        out[key] = value
    return out


def mask_key(key: str | None) -> str | None:
    if not key:
        return None
    return f"…{key[-4:]}" if len(key) > 8 else "…"


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class LLMProvider:
    spec: ProviderSpec
    model: str

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def cache_id(self) -> str:
        """Identifies provider+model in cache keys so outputs never mix."""
        return f"{self.spec.id}:{self.model}"

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, cfg: Settings, api_key: str | None = None, model: str | None = None, client: Any = None):
        self.spec = PROVIDERS["anthropic"]
        self.cfg = cfg
        self.model = model or cfg.llm_model
        self._api_key = api_key
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self.cfg.llm_timeout_seconds,
                                               max_retries=2)
        return self._client

    @staticmethod
    def supports_effort(model: str) -> bool:
        # Haiku 4.5 rejects the effort parameter; Haiku 5.5 accepts it.
        return not model.startswith("claude-haiku-4")

    @staticmethod
    def supports_server_fallback(model: str) -> bool:
        # Server-side refusal fallback is offered on the Opus 5 / Fable tier.
        return model.startswith(("claude-opus-5", "claude-fable", "claude-mythos"))

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        import anthropic

        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.supports_effort(self.model):
            output_config["effort"] = self.cfg.llm_effort
        kwargs: dict[str, Any] = dict(model=self.model, max_tokens=self.cfg.llm_max_tokens, system=system,
                                      messages=[{"role": "user", "content": prompt}], output_config=output_config)
        if self.cfg.llm_use_fallbacks and self.supports_server_fallback(self.model):
            kwargs.update(betas=[self.FALLBACK_BETA], fallbacks="default")
        try:
            response = self.client.beta.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("Anthropic rejected the API key") from exc
        except anthropic.NotFoundError as exc:
            raise LLMUnavailable(f"Anthropic model {self.model!r} not found") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("Anthropic rate limit reached") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("could not reach the Anthropic API") from exc

        usage = getattr(response, "usage", None)
        result = ProviderResult({}, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request", result)
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("response truncated at max_tokens", result)
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise LLMUnavailable("empty response", result)
        try:
            result.data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("response was not valid JSON", result) from exc
        return result

    def list_models(self) -> list[str]:
        import anthropic

        try:
            return sorted(m.id for m in self.client.models.list())
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("Anthropic rejected the API key") from exc
        except anthropic.APIError as exc:
            raise LLMUnavailable(f"could not list Anthropic models: {exc.__class__.__name__}") from exc


class OpenAICompatibleProvider(LLMProvider):
    """Chat Completions adapter for NVIDIA NIM, OpenAI, Gemini, Groq, etc."""

    def __init__(self, spec: ProviderSpec, cfg: Settings, api_key: str | None, model: str,
                 base_url: str | None = None, http_client: httpx.Client | None = None):
        url = (base_url or spec.base_url or "").rstrip("/")
        if not url:
            raise ValueError(f"{spec.label} needs a base URL")
        if not url.startswith(("https://", "http://")):
            raise ValueError("base URL must start with http:// or https://")
        if spec.requires_key and not api_key:
            raise ValueError(f"{spec.label} needs an API key")
        if not model:
            raise ValueError("model is required")
        self.spec, self.cfg, self.model, self.base_url = spec, cfg, model, url
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=cfg.llm_timeout_seconds)
        self._json_mode = True  # switched off if the endpoint rejects response_format

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self.spec.id == "openrouter":
            headers["X-Title"] = "Psychometric Assessment"
        return headers

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._http.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"{self.spec.label} timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"could not reach {self.spec.label}") from exc

    def _raise_for_status(self, res: httpx.Response) -> None:
        if res.status_code in (401, 403):
            raise LLMUnavailable(f"{self.spec.label} rejected the API key")
        if res.status_code == 404:
            raise LLMUnavailable(f"{self.spec.label}: model {self.model!r} or endpoint not found")
        if res.status_code == 429:
            raise LLMUnavailable(f"{self.spec.label} rate limit or quota reached")
        if res.status_code >= 400:
            raise LLMUnavailable(f"{self.spec.label} API error {res.status_code}: {_error_message(res)}")

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        instructions = (f"{system}\n\nRespond with a single JSON object only (no prose, no code fences) "
                        f"that matches this JSON Schema:\n{json.dumps(schema)}")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": prompt}],
            self.spec.token_param: self.cfg.llm_compat_max_tokens,
        }
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}
        res = self._post(body)
        if res.status_code in (400, 422) and "response_format" in body:
            # Some models/endpoints don't support JSON mode; retry with prompt-only JSON.
            self._json_mode = False
            body.pop("response_format")
            res = self._post(body)
        self._raise_for_status(res)

        try:
            payload = res.json()
            choice = payload["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"{self.spec.label} returned an unexpected response") from exc
        usage = payload.get("usage") or {}
        result = ProviderResult({}, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        if choice.get("finish_reason") == "length":
            raise LLMUnavailable("response truncated at max_tokens", result)
        if choice.get("finish_reason") == "content_filter":
            raise LLMUnavailable("provider content filter blocked the response", result)
        try:
            result.data = validate_schema(extract_json(text), schema)
        except LLMUnavailable as exc:
            raise LLMUnavailable(str(exc), result) from exc  # keep the billed usage
        return result

    def list_models(self) -> list[str]:
        try:
            res = self._http.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"could not reach {self.spec.label}") from exc
        self._raise_for_status(res)
        try:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            return sorted({str(m["id"]) for m in items if isinstance(m, dict) and "id" in m})
        except (ValueError, TypeError) as exc:
            raise LLMUnavailable(f"{self.spec.label} returned an unexpected model list") from exc


def _error_message(res: httpx.Response) -> str:
    try:
        err = res.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        return str(msg or res.text)[:200]
    except ValueError:
        return res.text[:200]


def build_provider(cfg: Settings, provider_id: str, api_key: str | None, model: str | None,
                   base_url: str | None = None, **clients: Any) -> LLMProvider:
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise ValueError(f"unknown provider {provider_id!r}")
    if spec.kind == "anthropic":
        if not api_key and clients.get("client") is None:
            raise ValueError("Anthropic needs an API key")
        return AnthropicProvider(cfg, api_key=api_key, model=model or spec.model_hint, client=clients.get("client"))
    return OpenAICompatibleProvider(spec, cfg, api_key, model or "", base_url=base_url or None,
                                    http_client=clients.get("http_client"))


def provider_from_env(cfg: Settings) -> LLMProvider | None:
    """The provider configured by environment variables, if any."""
    if not cfg.llm_enabled:
        return None
    if cfg.llm_provider == "anthropic":
        return AnthropicProvider(cfg, api_key=cfg.anthropic_api_key) if cfg.anthropic_api_key else None
    if cfg.llm_provider in PROVIDERS and (cfg.llm_api_key or not PROVIDERS[cfg.llm_provider].requires_key):
        try:
            return build_provider(cfg, cfg.llm_provider, cfg.llm_api_key, cfg.llm_model, cfg.llm_base_url)
        except ValueError:
            return None
    return None


def catalog() -> list[dict[str, Any]]:
    return [{"id": p.id, "label": p.label, "base_url": p.base_url, "model_hint": p.model_hint,
             "key_hint": p.key_hint, "requires_key": p.requires_key, "base_url_editable": p.base_url_editable,
             "docs_url": p.docs_url} for p in PROVIDERS.values()]
