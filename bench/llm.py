"""Provider-agnostic LLM client for NexusBench.

* Providers: Gemini (REST), DeepSeek (OpenAI-compatible), Ollama (local).
* Every response is cached (append-only JSONL) keyed by provider, model,
  sampling params and messages, so re-generation is free and reproducible.
* Every paid call is written to a cost ledger and checked against a hard
  per-provider cap *before* the call, using the worst case (max_tokens).

Prices are USD per 1M tokens, checked 2026-11-10 (ai.google.dev pricing,
api-docs.deepseek.com pricing). DeepSeek uses the peak rate (conservative).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(REPO, "data", "nexusbench")

PRICES: dict[tuple[str, str], tuple[float, float]] = {
    ("gemini", "gemini-2.5-flash-lite"): (0.10, 0.40),
    ("gemini", "gemini-3.5-flash-lite"): (0.30, 2.50),
    ("deepseek", "deepseek-flash"): (0.30, 1.20),
}
# Hard caps for Phase 1 (agreed with the user 2026-11-10): $5 total.
CAPS_USD: dict[str, float] = {"gemini": 2.0, "deepseek": 2.0, "ollama": 0.0}


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def load_env(path: str = os.path.join(REPO, ".env")) -> None:
    """Minimal .env loader (does not override variables already set)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.split(" #")[0].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def gemini_thinking_config(model: str) -> dict[str, Any]:
    """Minimal-thinking config for a Gemini model.

    Gemini 2.x takes ``thinkingBudget`` (0 disables thinking). Gemini 3.x rejects
    ``thinkingBudget`` with HTTP 400 and takes ``thinkingLevel`` instead
    (found 2026-11-10; DECISIONS D34).
    """
    m = re.match(r"gemini-(\d+)", model)
    major = int(m.group(1)) if m else 0
    return {"thinkingLevel": "low"} if major >= 3 else {"thinkingBudget": 0}


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    latency_ms: float


class _JsonlStore:
    """Thread-safe append-only JSONL file loaded into memory."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.rows: list[dict[str, Any]] = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.rows = [json.loads(line) for line in fh if line.strip()]

    def append(self, row: dict[str, Any]) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            self.rows.append(row)


class CostLedger(_JsonlStore):
    def __init__(self, path: str = os.path.join(DATA_DIR, "cost_ledger.jsonl")) -> None:
        super().__init__(path)

    def spent(self, provider: str) -> float:
        return sum(r["cost_usd"] for r in self.rows if r["provider"] == provider)

    def check(self, provider: str, model: str, worst_case_usd: float) -> None:
        cap = CAPS_USD.get(provider, 0.0)
        if provider == "ollama":
            return
        if self.spent(provider) + worst_case_usd > cap:
            raise BudgetExceeded(
                f"{provider}: spent ${self.spent(provider):.4f}, next call could cost "
                f"${worst_case_usd:.4f}, cap ${cap:.2f}"
            )


class ResponseCache(_JsonlStore):
    def __init__(self, path: str = os.path.join(DATA_DIR, "llm_cache.jsonl")) -> None:
        super().__init__(path)
        self._index = {r["key"]: r for r in self.rows}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._index.get(key)

    def put(self, row: dict[str, Any]) -> None:
        self.append(row)
        self._index[row["key"]] = row


def _cost(provider: str, model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES.get((provider, model), (0.0, 0.0))
    return (tin * pin + tout * pout) / 1e6


class LLMClient:
    """One client per (provider, model). ``complete`` returns JSON text."""

    def __init__(self, provider: str, model: str, *, ledger: CostLedger | None = None,
                 cache: ResponseCache | None = None, timeout_s: float = 90.0) -> None:
        load_env()
        if provider not in {"gemini", "deepseek", "ollama"}:
            raise ValueError(f"unknown provider {provider}")
        if provider != "ollama" and (provider, model) not in PRICES:
            raise ValueError(f"no price on file for {provider}/{model}; add it to PRICES")
        self.provider = provider
        self.model = model
        self.ledger = ledger or CostLedger()
        self.cache = cache or ResponseCache()
        self._http = httpx.Client(timeout=timeout_s)

    # -- public -----------------------------------------------------------
    def complete(self, system: str, messages: list[dict[str, str]], *, max_tokens: int = 500,
                 temperature: float = 0.0, seed: int = 0, cache_tag: str = "") -> LLMResponse:
        """``messages``: [{"role": "user"|"assistant", "content": str}, ...].

        ``cache_tag`` lets callers deliberately request a fresh sample (e.g.
        repeated runs) while keeping each sample cached.
        """
        key = hashlib.sha256(json.dumps(
            [self.provider, self.model, system, messages, max_tokens, temperature, seed, cache_tag],
            sort_keys=True).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            return LLMResponse(hit["text"], self.provider, self.model, hit["input_tokens"],
                               hit["output_tokens"], 0.0, True, 0.0)

        approx_in = (len(system) + sum(len(m["content"]) for m in messages)) // 3 + 50
        self.ledger.check(self.provider, self.model,
                          _cost(self.provider, self.model, approx_in, max_tokens))

        t0 = time.perf_counter()
        text, tin, tout = self._call_with_retries(system, messages, max_tokens, temperature, seed)
        latency = (time.perf_counter() - t0) * 1000
        cost = _cost(self.provider, self.model, tin, tout)
        self.ledger.append({"ts": time.time(), "provider": self.provider, "model": self.model,
                            "input_tokens": tin, "output_tokens": tout, "cost_usd": cost})
        self.cache.put({"key": key, "provider": self.provider, "model": self.model, "text": text,
                        "input_tokens": tin, "output_tokens": tout})
        return LLMResponse(text, self.provider, self.model, tin, tout, cost, False, latency)

    # -- transport --------------------------------------------------------
    def _call_with_retries(self, system, messages, max_tokens, temperature, seed):
        delay = 2.0
        last: Exception | None = None
        for _ in range(5):
            try:
                return self._call(system, messages, max_tokens, temperature, seed)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                body = exc.response.text
                if code == 429 and "PerDay" in body:  # daily quota: retrying cannot help
                    raise LLMError(f"{self.provider}: daily quota exhausted: {body[:300]}") from exc
                if code not in (408, 429, 500, 502, 503, 504):
                    raise LLMError(f"{self.provider} HTTP {code}: {exc.response.text[:300]}") from exc
                last = exc
            except (httpx.TransportError, json.JSONDecodeError, KeyError) as exc:
                last = exc
            time.sleep(delay)
            delay *= 2
        raise LLMError(f"{self.provider}: gave up after retries ({last})")

    def _call(self, system, messages, max_tokens, temperature, seed):
        if self.provider == "gemini":
            return self._gemini(system, messages, max_tokens, temperature, seed)
        if self.provider == "deepseek":
            return self._deepseek(system, messages, max_tokens, temperature)
        return self._ollama(system, messages, max_tokens, temperature, seed)

    def _gemini(self, system, messages, max_tokens, temperature, seed):
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise LLMError("GEMINI_API_KEY not set")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]}
                for m in messages
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "seed": seed,
                "thinkingConfig": gemini_thinking_config(self.model),
            },
        }
        r = self._http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": key}, json=body)
        r.raise_for_status()
        d = r.json()
        cand = (d.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        u = d.get("usageMetadata", {})
        tout = u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
        return text, u.get("promptTokenCount", 0), tout

    def _deepseek(self, system, messages, max_tokens, temperature):
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise LLMError("DEEPSEEK_API_KEY not set")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        r = self._http.post("https://api.deepseek.com/chat/completions",
                            headers={"Authorization": f"Bearer {key}"}, json=body)
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return (d["choices"][0]["message"].get("content") or "",
                u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

    def _ollama(self, system, messages, max_tokens, temperature, seed):
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "seed": seed, "num_predict": max_tokens},
        }
        r = self._http.post(f"{host}/api/chat", json=body)
        r.raise_for_status()
        d = r.json()
        return d["message"]["content"], d.get("prompt_eval_count", 0), d.get("eval_count", 0)
