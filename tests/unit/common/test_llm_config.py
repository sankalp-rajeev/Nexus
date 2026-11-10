"""The mock LLM must be opt-in only (Improvement Plan, Phase 0)."""

from __future__ import annotations

import pytest

from services.common import llm_config
from services.common.llm_config import LLMConfigError


def test_default_mode_is_gemini_not_mock(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM", raising=False)
    assert llm_config.llm_mode() == "gemini"
    assert not llm_config.is_mock()


def test_missing_key_raises_instead_of_falling_back(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        llm_config.gemini_api_key()


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    with pytest.raises(LLMConfigError):
        llm_config.gemini_api_key()


def test_critic_factory_raises_without_key(monkeypatch):
    from services.critic.llm import make_provider

    monkeypatch.delenv("NEXUS_LLM", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        make_provider("HALLUCINATION")


def test_critic_factory_uses_mock_only_when_explicit(monkeypatch):
    from services.critic.llm import MockProvider, make_provider

    monkeypatch.setenv("NEXUS_LLM", "mock")
    assert isinstance(make_provider("HALLUCINATION"), MockProvider)


def test_healer_scorer_raises_without_key(monkeypatch):
    from services.healer.eval_runner import _run_gemini_fallback

    monkeypatch.delenv("NEXUS_LLM", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        _run_gemini_fallback("task", "output")


def test_healer_mock_score_is_labelled(monkeypatch):
    from services.healer.eval_runner import _run_gemini_fallback

    monkeypatch.setenv("NEXUS_LLM", "mock")
    assert _run_gemini_fallback("task", "output").per_metric == {"mock": 0.5}


def test_invalid_mode_rejected(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM", "gpt")
    with pytest.raises(LLMConfigError):
        llm_config.llm_mode()


def test_describe_reports_mock_flag(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM", "mock")
    assert llm_config.describe()["mock"] == "true"
    monkeypatch.setenv("NEXUS_LLM", "gemini")
    d = llm_config.describe()
    assert d["mock"] == "false" and d["model"]
