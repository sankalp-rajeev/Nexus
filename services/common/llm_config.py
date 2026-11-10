"""Single source of truth for which LLM the services use.

Rules (Improvement Plan, Phase 0):
  * The mock is selected ONLY by an explicit flag: ``NEXUS_LLM=mock``.
  * A missing API key is an error, never a silent switch to the mock.
  * The model name is pinned here (overridable by env) and is recorded in
    every report/result file via :func:`describe`.
"""

from __future__ import annotations

import os

# gemini-2.0-flash is no longer served (checked 2026-11-10 via models.list).
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

_PLACEHOLDER_KEYS = {"", "your_gemini_api_key_here"}


class LLMConfigError(RuntimeError):
    """Raised when a real LLM is requested but cannot be configured."""


def llm_mode() -> str:
    """Return the configured provider: ``gemini`` (default) or ``mock``."""
    mode = os.getenv("NEXUS_LLM", "gemini").strip().lower()
    if mode not in {"gemini", "mock"}:
        raise LLMConfigError(f"NEXUS_LLM must be 'gemini' or 'mock', got {mode!r}")
    return mode


def is_mock() -> bool:
    return llm_mode() == "mock"


def gemini_model() -> str:
    return os.getenv("CRITIC_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


def gemini_api_key() -> str:
    """Return the Gemini key or raise. Never returns a placeholder."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key in _PLACEHOLDER_KEYS:
        raise LLMConfigError(
            "GEMINI_API_KEY is not set. Set it, or set NEXUS_LLM=mock explicitly "
            "for offline/CI runs."
        )
    return key


def describe() -> dict[str, str]:
    """Provider/model header for reports and result files."""
    if is_mock():
        return {"provider": "mock", "model": "MockProvider", "mock": "true"}
    return {"provider": "gemini", "model": gemini_model(), "mock": "false"}
