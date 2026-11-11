"""HALLUCINATION detector: claim-level NLI grounding against retrieved context.

1. Retrieved context = outputs of retrieval spans and retrieval-tool calls.
   JSON document lists become one premise per document; long prose is chunked.
2. The final answer is split into claims: sentences, then a rule-based split
   on clause-joining conjunctions. Hedges, abstentions and statements about the
   retrieval itself ("the documents don't mention X") are not factual claims.
3. Each claim is scored by the best entailment probability over premises
   (single documents and the whole context) with a local NLI cross-encoder.
4. Trace score = 1 - min over claims of best entailment. Flag if >= threshold.

No gold answers, no knowledge of which document "should" have been retrieved.
"""

from __future__ import annotations

import re
import threading

from nexus_agent.models import CompleteTrace, SpanType

from services.detectors.common import RETRIEVAL_TOOLS, parse_json, tool_calls

NLI_MODEL = "cross-encoder/nli-deberta-v3-base"
_ENTAIL_IDX = 1  # id2label: 0 contradiction, 1 entailment, 2 neutral

_HEDGE = re.compile(
    r"\b(could ?n[o']?t|cannot|can't|unable|not (?:contain|mention|include|provide|specify|"
    r"available|found|listed|say|state)|no (?:information|details|mention|record|data)|"
    r"(?:do|does|did)(?: not|n't) (?:know|have|contain|mention|include|say|specify|state)|"
    r"insufficient|unknown|not sure|i don't|there is no)\b", re.I)
_META = re.compile(r"\b(documents?|search results?|results? (?:returned|found)|the context|"
                   r"information provided|knowledge base|sources?)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_CONJ = re.compile(r";\s+|,?\s+(?:and|but|while|whereas)\s+(?=(?:it|its|the|they|he|she|this|"
                   r"that|[A-Z])\b)")
_NUM_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")

_lock = threading.Lock()
_model = None


def _nli():
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(NLI_MODEL)
    return _model


def _norm(text: str) -> str:
    return _NUM_COMMA.sub("", text or "").strip()


def _resolve_pronouns(title: str, text: str) -> str:
    """Lightweight coreference: sentence-initial It/Its in a titled document
    refer to the title. NLI cross-encoders otherwise accept 'X was founded in
    2018' from another company's 'It was founded in 2018'."""
    text = re.sub(r"(^|(?<=[.!?]\s))It\b", title, text)
    return re.sub(r"(^|(?<=[.!?]\s))Its\b", f"{title}'s", text)


def retrieved_context(trace: CompleteTrace) -> list[str]:
    premises: list[str] = []
    texts = [s.output for s in trace.spans
             if s.span_type == SpanType.RETRIEVAL and s.output and s.error_type is None]
    texts += [c.span.output for c in tool_calls(trace)
              if c.ok and c.tool in RETRIEVAL_TOOLS and c.span.output]
    for t in texts:
        obj = parse_json(t)
        if isinstance(obj, list):  # a document list (possibly empty: no evidence)
            for d in obj:
                if not isinstance(d, dict):
                    premises.append(str(d))
                    continue
                title = str(d.get("title") or "").strip()
                body = " ".join(str(v) for k, v in d.items() if k != "title")
                premises.append(_resolve_pronouns(title, body) if title else body)
        else:
            premises += [t[i:i + 600] for i in range(0, len(t), 600)]
    return [_norm(p) for p in premises if p and p.strip()]


def premise_units(premises: list[str]) -> list[str]:
    """Sentences and 2-sentence windows of every premise, plus the premise itself.

    Sentence-level NLI: the cross-encoder judged 'X was founded in 1964' as
    entailed by 'X was founded in 1964 by Y.' but as neutral once an unrelated
    sentence followed it, so evidence is scored at sentence granularity.
    """
    units: list[str] = []
    for p in premises:
        sents = [s.strip() for s in _SENT.split(p) if s.strip()]
        units += sents
        units += [f"{a} {b}" for a, b in zip(sents, sents[1:])]
        if len(sents) > 2:
            units.append(p[:1500])
    seen: set[str] = set()
    return [u for u in units if not (u in seen or seen.add(u))]


_ENTITY = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b")
_NON_ENTITY = {"The", "It", "Its", "In", "A", "An", "This", "That", "There", "They", "He", "She",
               "Answer", "Question", "Based", "According", "Yes", "No", "What", "Who", "Which",
               "How", "When", "Where", "USD"}
_IMPERATIVE = re.compile(r"^\s*(please|check|try|contact|consider|let|feel|visit|refer|note|see|"
                         r"you (?:may|can|could|should|might))\b", re.I)


def entities(text: str) -> set[str]:
    out = set()
    for m in _ENTITY.findall(text):
        words = [w for w in m.split() if w not in _NON_ENTITY]
        if words:
            out.add(" ".join(words).lower())
    return out


def claims(answer: str, question: str) -> list[str]:
    out = []
    for sent in _SENT.split((answer or "").strip()):
        for part in _CONJ.split(sent):
            part = part.strip(" .,;")
            if (not part or _HEDGE.search(part) or _META.search(part)
                    or _IMPERATIVE.search(part) or part.endswith("?")):
                continue
            if len(part.split()) < 4:  # bare answer ("1964"): attach the question
                part = f"The answer to the question '{question.strip()}' is {part}"
            out.append(_norm(part))
    return out


def score(trace: CompleteTrace) -> float | None:
    """1 - min_claim max_premise P(entail). None when there is nothing to check."""
    premises = retrieved_context(trace)
    cl = claims(trace.final_output or "", trace.root_input or "")
    if not premises or not cl:
        return None
    cands = premise_units(premises)
    pairs = [(p, c) for c in cl for p in cands]
    probs = _nli().predict(pairs, apply_softmax=True, batch_size=16)
    k = len(cands)
    best = []
    for i, c in enumerate(cl):
        ents = entities(c)
        vals = []
        for j, p in enumerate(cands):
            pl = p.lower()
            # Entity gate: a premise can only support a claim if it names the
            # claim's entities (NLI models under-weight entity mismatches).
            gated = all(e in pl for e in ents)
            vals.append(float(probs[i * k + j][_ENTAIL_IDX]) if gated else 0.0)
        best.append(max(vals))
    return 1.0 - min(best)
