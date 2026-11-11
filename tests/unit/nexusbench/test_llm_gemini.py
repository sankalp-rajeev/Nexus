"""bench/llm.py must not send thinkingBudget to Gemini 3.x (HTTP 400)."""

from __future__ import annotations

import pytest

from bench import llm as llm_mod
from bench.llm import gemini_thinking_config


@pytest.mark.parametrize("model,expected", [
    ("gemini-2.5-flash-lite", {"thinkingBudget": 0}),
    ("gemini-3.5-flash-lite", {"thinkingLevel": "low"}),
    ("gemini-3.8-flash", {"thinkingLevel": "low"}),
    ("gemini-10-pro", {"thinkingLevel": "low"}),
])
def test_thinking_config_by_major_version(model, expected):
    assert gemini_thinking_config(model) == expected


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1}}


class _FakeHttp:
    def __init__(self):
        self.bodies = []

    def post(self, url, headers=None, json=None):
        self.bodies.append(json)
        return _FakeResp()


@pytest.mark.parametrize("model", ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite"])
def test_request_body_uses_the_right_thinking_field(tmp_path, monkeypatch, model):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    c = llm_mod.LLMClient("gemini", model, ledger=llm_mod.CostLedger(str(tmp_path / "l.jsonl")),
                          cache=llm_mod.ResponseCache(str(tmp_path / "c.jsonl")))
    c._http = _FakeHttp()
    c.complete("sys", [{"role": "user", "content": "hi"}], max_tokens=5)
    tc = c._http.bodies[0]["generationConfig"]["thinkingConfig"]
    if model.startswith("gemini-3"):
        assert "thinkingBudget" not in tc and tc == {"thinkingLevel": "low"}
    else:
        assert tc == {"thinkingBudget": 0}
