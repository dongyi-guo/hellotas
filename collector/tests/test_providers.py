"""The optional AI step with each provider: request shapes, answers, refusals and falling back to the rules.

No network: a fake stands in for each service and records what would have been sent.
"""

import json

import pytest
from conftest import NOW, FakeFetcher
from test_pipeline import _future_meetup

from hellotas_collector.config import load
from hellotas_collector.pipeline import Collector
from hellotas_collector.providers import make_provider
from hellotas_collector.report import markdown

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "AI_API_KEY",
        "COLLECTOR_MODEL", "COLLECTOR_AI_PROVIDER")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def answer_for(system: str) -> dict:
    if "score its relevance" in system:
        return {"relevant": True, "score": 85, "reason": "Local cyber security meetup open to students."}
    return {
        "title": {"en": "SecTalks Hobart: Just Spoof the Government?", "zh": "SecTalks Hobart：冒充政府？",
                  "ne": "SecTalks Hobart: सरकारको नक्कल?"},
        "summary": {"en": "A talk on email spoofing from a real engagement.", "zh": "一次关于邮件伪造的分享。",
                    "ne": "इमेल स्पुफिङबारे कुराकानी।"},
        "location": {"en": "Mathers House, Hobart", "zh": "", "ne": ""},
        "cost": {"en": "Free", "zh": "免费", "ne": "निःशुल्क"},
        "host": "SecTalks Hobart", "slug": "sectalks-hobart-spoofing", "type": "meetup", "format": "in_person",
        "topics": ["cyber", "community"],
    }


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeHTTP:
    """Stands in for requests.Session: answers like OpenAI's or Gemini's API and records each request."""

    def __init__(self, style, status=200, refuse=False, fence=False):
        self.style, self.status, self.refuse, self.fence = style, status, refuse, fence
        self.requests = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        if self.status != 200:
            return Response(self.status, {"error": {"message": "Incorrect API key provided"}})
        if self.style == "gemini":
            system = json["systemInstruction"]["parts"][0]["text"]
            if self.refuse:
                return Response(200, {"candidates": [{"finishReason": "SAFETY"}]})
            text = _dumps(answer_for(system), self.fence)
            return Response(200, {
                "candidates": [{"finishReason": "STOP", "content": {"parts": [
                    {"text": "thinking about it", "thought": True}, {"text": text}]}}],
                "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 200, "thoughtsTokenCount": 50}})
        system = json["messages"][0]["content"]
        if self.refuse:
            return Response(200, {"choices": [{"finish_reason": "stop",
                                               "message": {"content": None, "refusal": "I can't help with that."}}]})
        return Response(200, {"choices": [{"finish_reason": "stop",
                                           "message": {"content": _dumps(answer_for(system), self.fence)}}],
                              "usage": {"prompt_tokens": 1000, "completion_tokens": 250}})


def _dumps(data, fence):
    text = json.dumps(data, ensure_ascii=False)
    return f"```json\n{text}\n```" if fence else text


def run_with(site, provider, client, use_ai=None, **ai):
    config = load(site / "collector" / "sources.yaml")
    config.ai.update(enabled=True, provider=provider, **ai)
    c = Collector(site, config, now=NOW, fetcher=FakeFetcher(_future_meetup(site)), images=False,
                  log=lambda *a: None, use_ai=use_ai, client=client, dry_run=True)
    return c, c.run(["sectalks-hobart"])


def test_openai(site, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    http = FakeHTTP("openai")
    c, result = run_with(site, "openai", http)
    p = result.added[0]
    assert p.written_by == "ai" and p.judgement.by == "ai" and p.slug == "sectalks-hobart-spoofing"
    first, second = http.requests
    assert first["url"] == "https://api.openai.com/v1/chat/completions"
    assert first["headers"]["Authorization"] == "Bearer sk-test"
    body = first["json"]
    assert body["model"] == "gpt-5-mini"
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"]
    assert body["reasoning_effort"] == "low" and second["json"]["reasoning_effort"] == "medium"
    assert "max_completion_tokens" in body and "max_tokens" not in body
    assert result.ai["provider"] == "openai" and result.ai["input_tokens"] == 2000
    assert "AI: openai, gpt-5-mini, 2 call(s)" in markdown(result)


def test_openai_without_reasoning_setting(site, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    http = FakeHTTP("openai")
    run_with(site, "openai", http, send_effort=False, models={"openai": "gpt-4.1"})
    assert http.requests[0]["json"]["model"] == "gpt-4.1" and "reasoning_effort" not in http.requests[0]["json"]


def test_gemini(site, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    http = FakeHTTP("gemini")
    c, result = run_with(site, "gemini", http)
    assert result.added[0].written_by == "ai"
    req = http.requests[0]
    assert req["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert req["headers"] == {"x-goog-api-key": "g-test"}
    assert req["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "JSON Schema" in req["json"]["systemInstruction"]["parts"][0]["text"]
    assert result.ai["output_tokens"] == 500  # thinking tokens are billed, so they are counted


def test_openai_compatible_service(site, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "or-test")
    http = FakeHTTP("openai", fence=True)  # some models wrap their JSON in a code fence
    c, result = run_with(site, "openai-compatible", http, base_url="https://openrouter.ai/api/v1/",
                         models={"openai-compatible": "deepseek/deepseek-chat"})
    assert result.added[0].written_by == "ai"
    body = http.requests[0]["json"]
    assert http.requests[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert body["response_format"] == {"type": "json_object"} and "reasoning_effort" not in body
    assert "JSON Schema" in body["messages"][0]["content"] and "max_tokens" in body


def test_openai_compatible_needs_an_address_and_a_model():
    with pytest.raises(ValueError, match="base_url"):
        make_provider({"provider": "openai-compatible", "models": {"openai-compatible": "x"}}, client=object())
    with pytest.raises(ValueError, match="models.openai-compatible"):
        make_provider({"provider": "openai-compatible", "base_url": "https://api.example.com/v1"}, client=object())
    with pytest.raises(ValueError, match="must be one of"):
        make_provider({"provider": "chatgpt"})


@pytest.mark.parametrize("style,provider,key", [("openai", "openai", "OPENAI_API_KEY"),
                                                ("gemini", "gemini", "GEMINI_API_KEY")])
def test_refusal_and_bad_key_fall_back_to_rules(site, monkeypatch, style, provider, key):
    monkeypatch.setenv(key, "test")
    c, result = run_with(site, provider, FakeHTTP(style, refuse=True))
    assert result.added[0].written_by == "rules" and result.added[0].judgement.by == "rules"
    c, result = run_with(site, provider, FakeHTTP(style, status=401))
    assert result.added[0].written_by == "rules"
    assert "credential rejected" in result.added[0].judgement.reason


def test_only_the_chosen_providers_key_switches_it_on(site, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    c, result = run_with(site, "gemini", FakeHTTP("gemini"))
    assert c.editor is None and result.added[0].written_by == "rules"
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    c, result = run_with(site, "gemini", FakeHTTP("gemini"))
    assert c.editor is not None and result.added[0].written_by == "ai"


def test_variables_override_the_file(site, monkeypatch):
    monkeypatch.setenv("COLLECTOR_AI_PROVIDER", "gemini")
    monkeypatch.setenv("COLLECTOR_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    http = FakeHTTP("gemini")
    run_with(site, "openai", http)
    assert http.requests[0]["url"].endswith("/models/gemini-2.5-pro:generateContent")


def test_switched_off_by_default_whatever_keys_exist(site, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "AI_API_KEY"):
        monkeypatch.setenv(key, "test")
    config = load(site / "collector" / "sources.yaml")
    assert config.ai_enabled is False
    c = Collector(site, config, now=NOW, fetcher=FakeFetcher(_future_meetup(site)), images=False,
                  log=lambda *a: None, dry_run=True)
    assert c.editor is None
