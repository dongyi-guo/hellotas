"""The AI services the collector can use, behind one small interface.

Each provider takes a system prompt, the event text and a JSON Schema, and returns the parsed JSON answer with the
tokens it used. Which one is used is set in collector/sources.yaml (ai.provider); the key comes from a repository
secret. Adding another service means adding one class here and one entry in PROVIDERS.

  anthropic          Claude, through the Anthropic SDK                       key: ANTHROPIC_API_KEY
  openai             ChatGPT models, through the OpenAI API                  key: OPENAI_API_KEY
  gemini             Google Gemini, through the Gemini API                   key: GEMINI_API_KEY
  openai-compatible  any service with an OpenAI-style chat API (OpenRouter,   key: AI_API_KEY
                     DeepSeek, Groq, Mistral, ...); needs ai.base_url
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests

# Defaults when sources.yaml doesn't name a model. Providers rename and retire models; check the provider's own
# model list before switching the AI on, and set ai.models.<provider> (or the COLLECTOR_MODEL variable).
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "openai-compatible": "",
}
KEY_VARIABLES = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "openai-compatible": ("AI_API_KEY",),
}
PROVIDERS = tuple(DEFAULT_MODELS)

# Claude models that support server-side refusal fallbacks (fallbacks: "default"); Haiku has none
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(Exception):
    """The AI couldn't answer (no credential, API error, refusal or unusable output); use the rules instead."""


@dataclass
class Answer:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0


def provider_name(ai: dict) -> str:
    name = (os.environ.get("COLLECTOR_AI_PROVIDER") or ai.get("provider") or "anthropic").strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"ai.provider must be one of {', '.join(PROVIDERS)}, not {name!r}")
    return name


def model_for(ai: dict, name: str) -> str:
    return (os.environ.get("COLLECTOR_MODEL") or (ai.get("models") or {}).get(name) or ai.get("model")
            or DEFAULT_MODELS[name])


def api_key(name: str) -> str:
    return next((os.environ[v] for v in KEY_VARIABLES[name] if os.environ.get(v)), "")


def credentials_present(name: str = "anthropic") -> bool:
    return bool(api_key(name))


def make_provider(ai: dict, client=None) -> "Provider":
    """The provider sources.yaml asks for. `client` replaces the network in tests: an Anthropic client for
    anthropic, and an object with requests' post() for the others."""
    name = provider_name(ai)
    model = model_for(ai, name)
    if not model:
        raise ValueError(f"set ai.models.{name} in sources.yaml (or the COLLECTOR_MODEL variable)")
    if name == "anthropic":
        return AnthropicProvider(model, client=client)
    if name == "gemini":
        return GeminiProvider(model, api_key(name), session=client)
    if name == "openai":
        return OpenAIProvider(model, api_key(name), base_url=ai.get("base_url") or "https://api.openai.com/v1",
                              strict=True, send_effort=bool(ai.get("send_effort", True)), session=client)
    base_url = ai.get("base_url") or ""
    if not base_url:
        raise ValueError("ai.provider openai-compatible needs ai.base_url, e.g. https://openrouter.ai/api/v1")
    # Services differ in what they accept, so only the widely supported parts: JSON mode, no reasoning setting
    return OpenAIProvider(model, api_key(name), base_url=base_url, strict=False, send_effort=False, session=client,
                          name=name)


def _schema_in_prompt(system: str, schema: dict) -> str:
    """For services that can return JSON but can't enforce a schema: describe it in the prompt instead."""
    return (system + "\n\nAnswer with one JSON object and nothing else. It must match this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False))


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)  # some models wrap JSON in a code fence
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIUnavailable("the answer wasn't valid JSON") from exc
    if not isinstance(data, dict):
        raise AIUnavailable("the answer wasn't a JSON object")
    return data


def _http_error(service: str, response) -> AIUnavailable:
    status = response.status_code
    try:
        body = response.json()
        detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except ValueError:
        detail = ""
    detail = f": {str(detail)[:200]}" if detail else ""
    if status in (401, 403) or "api key" in detail.lower():  # Gemini answers a bad key with 400
        return AIUnavailable(f"{service} credential rejected{detail}")
    if status == 429:
        return AIUnavailable(f"rate limited or out of credit at {service}{detail}")
    if status in (400, 404, 422):
        return AIUnavailable(f"request rejected by {service}{detail}")
    return AIUnavailable(f"{service} API error {status}{detail}")


class Provider:
    name = ""
    model = ""

    def ask(self, task: str, system: str, user: str, schema: dict, effort: str, max_tokens: int) -> Answer:
        raise NotImplementedError


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str, client=None):
        self.model = model
        if client is None:
            import anthropic  # only needed when this provider is used
            client = anthropic.Anthropic(max_retries=3, timeout=120.0)
        self.client = client

    def ask(self, task, system, user, schema, effort, max_tokens):
        params = dict(
            model=self.model,
            max_tokens=max_tokens,
            # The stable part of the prompt first, so repeated calls in a run reuse the prompt cache
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if self.model in _FALLBACK_MODELS:
            # If a safety classifier declines, the API retries on Anthropic's recommended fallback model
            params.update(betas=[_FALLBACK_BETA], fallbacks="default")
        try:
            response = self.client.beta.messages.create(**params)
        except Exception as exc:  # the SDK's errors, mapped without importing it when a fake client is used
            raise _anthropic_error(exc) from exc
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
        if response.stop_reason == "refusal":
            raise AIUnavailable("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise AIUnavailable("the answer was cut off (max_tokens)")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        return Answer(_parse_json(text), tokens_in, tokens_out)


def _anthropic_error(exc: Exception) -> AIUnavailable:
    kind = type(exc).__name__
    message = getattr(exc, "message", "") or str(exc)
    if kind == "AuthenticationError" or kind == "PermissionDeniedError":
        return AIUnavailable(f"Anthropic credential rejected: {message}")
    if kind == "RateLimitError":
        return AIUnavailable("rate limited by the Anthropic API")
    if kind == "BadRequestError" or kind == "NotFoundError":
        return AIUnavailable(f"request rejected: {message}")
    if kind == "APIConnectionError" or kind == "APITimeoutError":
        return AIUnavailable("couldn't reach the Anthropic API")
    if hasattr(exc, "status_code"):
        return AIUnavailable(f"Anthropic API error {exc.status_code}")
    return AIUnavailable(f"Anthropic API error: {message}")


class OpenAIProvider(Provider):
    """OpenAI's Chat Completions API, which many other services copy.

    strict: enforce the JSON Schema (OpenAI's structured outputs). Services that don't support it get JSON mode
    with the schema described in the prompt. send_effort: pass reasoning_effort (reasoning models only).
    """

    def __init__(self, model: str, key: str, base_url: str, strict: bool = True, send_effort: bool = True,
                 session=None, name: str = "openai"):
        self.name = name
        self.model = model
        self.key = key
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.strict = strict
        self.send_effort = send_effort
        self.session = session or requests.Session()

    def ask(self, task, system, user, schema, effort, max_tokens):
        body = {"model": self.model, "messages": [
            {"role": "system", "content": system if self.strict else _schema_in_prompt(system, schema)},
            {"role": "user", "content": user}]}
        if self.strict:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": task, "schema": schema, "strict": True}}
            # Reasoning models count their thinking against this limit, so allow room for it
            body["max_completion_tokens"] = max_tokens * 2
        else:
            body["response_format"] = {"type": "json_object"}
            body["max_tokens"] = max_tokens
        if self.send_effort:
            body["reasoning_effort"] = effort
        service = "OpenAI" if self.name == "openai" else self.url.split("/")[2]
        try:
            response = self.session.post(self.url, json=body, timeout=180,
                                         headers={"Authorization": f"Bearer {self.key}"})
        except requests.RequestException as exc:
            raise AIUnavailable(f"couldn't reach {service}") from exc
        if response.status_code != 200:
            raise _http_error(service, response)
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable(f"{service} sent an answer the collector couldn't read") from exc
        usage = data.get("usage") or {}
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise AIUnavailable("the model declined this request")
        if choice.get("finish_reason") == "length":
            raise AIUnavailable("the answer was cut off (token limit)")
        return Answer(_parse_json(message.get("content") or ""), int(usage.get("prompt_tokens") or 0),
                      int(usage.get("completion_tokens") or 0))


class GeminiProvider(Provider):
    """Google's Gemini API (generateContent) in JSON mode, with the schema described in the prompt."""

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
    DECLINED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "OTHER"}

    def __init__(self, model: str, key: str, session=None):
        self.model = model
        self.key = key
        self.session = session or requests.Session()

    def ask(self, task, system, user, schema, effort, max_tokens):
        body = {
            "systemInstruction": {"parts": [{"text": _schema_in_prompt(system, schema)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            # Thinking models count their thinking against this limit, so allow room for it
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens * 2},
        }
        try:
            response = self.session.post(f"{self.BASE}{self.model}:generateContent", json=body, timeout=180,
                                         headers={"x-goog-api-key": self.key})
        except requests.RequestException as exc:
            raise AIUnavailable("couldn't reach Gemini") from exc
        if response.status_code != 200:
            raise _http_error("Gemini", response)
        try:
            data = response.json()
        except ValueError as exc:
            raise AIUnavailable("Gemini sent an answer the collector couldn't read") from exc
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount") or 0)
        tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
        if (data.get("promptFeedback") or {}).get("blockReason") or not data.get("candidates"):
            raise AIUnavailable("the model declined this request")
        candidate = data["candidates"][0]
        reason = candidate.get("finishReason", "STOP")
        if reason == "MAX_TOKENS":
            raise AIUnavailable("the answer was cut off (token limit)")
        if reason in self.DECLINED:
            raise AIUnavailable("the model declined this request")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return Answer(_parse_json(text), tokens_in, tokens_out)
