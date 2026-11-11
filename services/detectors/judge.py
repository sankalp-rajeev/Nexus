"""Optional HALLUCINATION variant: an LLM grounding judge (Gemini).

Reported separately from the NLI detector, never mixed in. Gemini is a
different model family from both trace models (DeepSeek, Qwen). Calls are
cached and every paid call is logged in data/phase2/cost_ledger.jsonl.
"""

from __future__ import annotations

import json
import os

from nexus_agent.models import CompleteTrace

from services.detectors.hallucination import retrieved_context

JUDGE_MODEL = "gemini-3.5-flash-lite"
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DIR = os.path.join(_REPO, "data", "phase2")
_SYSTEM = ("You check whether an assistant's answer is supported by retrieved documents. "
           "Use only the documents, not your own knowledge. Respond only with JSON.")
_client = None


def _llm():
    global _client
    if _client is None:
        from bench import llm as llm_mod

        class _Gemini3Client(llm_mod.LLMClient):
            """Gemini 3.x rejects thinkingConfig.thinkingBudget (bench/llm.py is frozen
            in this phase), so the request uses thinkingLevel='low' instead."""

            def _gemini(self, system, messages, max_tokens, temperature, seed):
                body = {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": m["content"]}]}
                                 for m in messages],
                    "generationConfig": {"temperature": temperature,
                                         "maxOutputTokens": max_tokens,
                                         "responseMimeType": "application/json", "seed": seed,
                                         "thinkingConfig": {"thinkingLevel": "low"}},
                }
                r = self._http.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{self.model}:generateContent",
                    headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")}, json=body)
                r.raise_for_status()
                d = r.json()
                cand = (d.get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
                u = d.get("usageMetadata", {})
                return (text, u.get("promptTokenCount", 0),
                        u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0))

        llm_mod.CAPS_USD["gemini"] = 1.50  # Phase 2 cap (whole phase, this ledger)
        _client = _Gemini3Client(
            "gemini", JUDGE_MODEL,
            ledger=llm_mod.CostLedger(os.path.join(_DIR, "cost_ledger.jsonl")),
            cache=llm_mod.ResponseCache(os.path.join(_DIR, "llm_cache.jsonl")))
    return _client


def judge(trace: CompleteTrace) -> bool | None:
    """True = some factual claim is unsupported. None = nothing to judge."""
    docs = retrieved_context(trace)
    answer = (trace.final_output or "").strip()
    if not docs or not answer:
        return None
    doc_txt = "\n".join(f"[{i + 1}] {d}" for i, d in enumerate(docs))[:4000]
    prompt = (f"Documents:\n{doc_txt}\n\nQuestion: {trace.root_input}\nAnswer: {answer}\n\n"
              "Does the answer make any factual claim that the documents do not support? "
              "Saying the information is missing is not a factual claim. Respond with JSON: "
              '{"unsupported_claim": true|false, "reason": "<short>"}')
    resp = _llm().complete(_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=150)
    try:
        return bool(json.loads(resp.text).get("unsupported_claim"))
    except (json.JSONDecodeError, AttributeError):
        return None


def spent_usd() -> float:
    return _llm().ledger.spent("gemini")
