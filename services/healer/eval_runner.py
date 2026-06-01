"""DeepEval + Gemini evaluation runner.

Evaluates agent output before and after a patch is applied, returning
composite and per-metric scores for MLflow logging.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.healer.eval_runner")


@dataclass
class EvalResult:
    composite_score: float
    per_metric: dict[str, float] = field(default_factory=dict)
    eval_duration_ms: float = 0.0


def run_eval(
    input_text: str,
    actual_output: str,
    retrieval_context: list[str] | None = None,
    gemini_api_key: str | None = None,
) -> EvalResult:
    """Run DeepEval metrics on a single (input, output) pair.

    Falls back to a lightweight Gemini-direct scorer if DeepEval fails
    (e.g., version incompatibility or network issues) to keep the healer
    running in all environments.
    """
    t0 = time.perf_counter()
    try:
        result = _run_deepeval(input_text, actual_output, retrieval_context, gemini_api_key)
    except Exception as exc:
        logger.warning("healer: DeepEval failed (%s); using Gemini fallback scorer", exc)
        result = _run_gemini_fallback(input_text, actual_output, gemini_api_key)
    result.eval_duration_ms = (time.perf_counter() - t0) * 1000
    return result


# ── DeepEval path ─────────────────────────────────────────────────────────────

def _run_deepeval(input_text, actual_output, retrieval_context, gemini_api_key) -> EvalResult:
    import os as _os
    if gemini_api_key:
        _os.environ.setdefault("GEMINI_API_KEY", gemini_api_key)

    from deepeval.test_case import LLMTestCase

    # Build test case
    kwargs: dict[str, Any] = dict(input=input_text, actual_output=actual_output)
    if retrieval_context:
        kwargs["retrieval_context"] = retrieval_context
    test_case = LLMTestCase(**kwargs)

    metrics = _build_metrics(bool(retrieval_context))
    scores: dict[str, float] = {}

    # Evaluate each metric independently (graceful partial failure)
    for m in metrics:
        try:
            m.measure(test_case)
            scores[m.name if hasattr(m, "name") else type(m).__name__] = float(m.score)
        except Exception as exc:
            logger.warning("healer: metric %s failed: %s", type(m).__name__, exc)

    composite = sum(scores.values()) / len(scores) if scores else 0.5
    return EvalResult(composite_score=composite, per_metric=scores)


def _build_metrics(has_context: bool):
    from deepeval.metrics import AnswerRelevancyMetric, GEval
    from deepeval.metrics.g_eval import GEval as _GEval  # noqa: F401

    model = _get_deepeval_model()
    metrics = [AnswerRelevancyMetric(threshold=0.5, model=model)]

    try:
        task_metric = GEval(
            name="TaskCompletion",
            criteria=(
                "Did the AI agent successfully complete the task described in the input? "
                "Score 1.0 if task fully completed with correct output. "
                "Score 0.5 if partially completed. "
                "Score 0.0 if not completed or output is wrong."
            ),
            evaluation_params=["input", "actual_output"],
            model=model,
        )
        metrics.append(task_metric)
    except Exception as exc:
        logger.warning("healer: GEval metric build failed: %s", exc)

    if has_context:
        try:
            from deepeval.metrics import FaithfulnessMetric
            metrics.append(FaithfulnessMetric(threshold=0.5, model=model))
        except Exception:
            pass

    return metrics


def _get_deepeval_model():
    """Return a Gemini model for DeepEval, or None to use default."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        from deepeval.models import GeminiModel
        return GeminiModel(model="gemini-2.0-flash")
    except Exception:
        try:
            # Older deepeval API
            from deepeval.models.gemini_model import GeminiModel
            return GeminiModel(model="gemini-2.0-flash")
        except Exception:
            return None


# ── Gemini direct fallback ────────────────────────────────────────────────────

def _run_gemini_fallback(input_text: str, actual_output: str,
                         gemini_api_key: str | None = None) -> EvalResult:
    """Score output quality 0-1 via a direct Gemini API call."""
    key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    if not key:
        logger.warning("healer: no GEMINI_API_KEY; returning default eval score 0.5")
        return EvalResult(composite_score=0.5, per_metric={"fallback": 0.5})

    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = (
            f"Rate the quality of this AI agent response on a scale from 0.0 to 1.0.\n\n"
            f"Task: {input_text[:500]}\n\n"
            f"Response: {actual_output[:500]}\n\n"
            "Reply with only a number between 0.0 and 1.0."
        )
        resp = model.generate_content(prompt)
        score = float(resp.text.strip().split()[0])
        score = max(0.0, min(1.0, score))
        return EvalResult(composite_score=score, per_metric={"gemini_quality": score})
    except Exception as exc:
        logger.warning("healer: Gemini fallback scorer failed: %s", exc)
        return EvalResult(composite_score=0.5, per_metric={"default": 0.5})
