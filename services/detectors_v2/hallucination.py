"""C4 global normalized entity presence; fixed C5 scopes and frozen NLI/splits."""
from dataclasses import dataclass

from nexus_agent.models import SpanType
from services.detectors import hallucination as v1
from services.detectors.common import RETRIEVAL_TOOLS, tool_calls
from services.detectors_v2.normalization import grounding_text


@dataclass
class Hallucination:
    score: float | None
    reason: str | None
    targets: int = 0
    claims: int = 0
    pairs: int = 0


def readable(p):
    import re
    return len(p.strip()) >= 20 and len(re.findall(r"[^\W\d_]{2,}", p)) >= 3


def raw_sources(trace):
    texts = [s.output for s in trace.spans if s.span_type == SpanType.RETRIEVAL and not s.error_type and s.output]
    texts += [c.span.output for c in tool_calls(trace) if c.ok and c.tool in RETRIEVAL_TOOLS and c.span.output]
    return texts


def entity_present_globally(claim, trace, premises=None):
    premises = v1.retrieved_context(trace) if premises is None else premises
    source = grounding_text(" ".join(raw_sources(trace) + premises))
    entities = [grounding_text(e) for e in v1.entities(claim)]
    return all(not e or e in source for e in entities)


def local_entailments(pairs):
    probs = v1._nli().predict(pairs, apply_softmax=True, batch_size=16)
    return [float(p[v1._ENTAIL_IDX]) for p in probs]


def target(trace, answer, entailments=None):
    premises = v1.retrieved_context(trace)
    claims = v1.claims(answer or "", trace.root_input or "")
    if not premises:
        return Hallucination(None, "no_successful_retrieval_text")
    if not claims:
        return Hallucination(None, "no_checkable_claims")
    if not any(readable(p) for p in premises):
        return Hallucination(None, "source_below_registered_readability_gate")
    units = v1.premise_units(premises)
    gates = [entity_present_globally(c, trace, premises) for c in claims]
    # Exact algebraic shortcut, not approximate pruning: a gate-forced zero
    # makes min(best entailment) zero and hence the trace score exactly one.
    if not all(gates):
        return Hallucination(1.0, None, 1, len(claims), 0)
    pairs = [(p, c) for c in claims for p in units]
    values = (entailments or local_entailments)(pairs)
    if len(values) != len(pairs):
        raise ValueError("NLI entailment count mismatch")
    k = len(units)
    best = [max(values[i*k:(i+1)*k]) for i, c in enumerate(claims)]
    return Hallucination(1 - min(best), None, 1, len(claims), len(pairs))


def score(trace, scope="final", entailments=None):
    if scope == "final":
        return target(trace, trace.final_output, entailments)
    if scope != "all_llm":
        raise ValueError("C5 scope must be final or all_llm")
    outputs = []
    had_source = False
    for i, span in enumerate(trace.spans):
        prefix = trace.model_copy(update={"spans": trace.spans[:i+1]})
        if raw_sources(prefix):
            had_source = True
        if span.span_type != SpanType.LLM_CALL or not span.output or not had_source:
            continue
        # Only sources completed before this output are available to this target.
        outputs.append(target(prefix, span.output, entailments))
        if outputs[-1].score == 1.0:
            # No later target can increase a max score beyond one.
            return Hallucination(1.0, None, sum(o.score is not None for o in outputs),
                                 sum(o.claims for o in outputs), sum(o.pairs for o in outputs))
    eligible = [o for o in outputs if o.score is not None]
    if eligible:
        return Hallucination(max(o.score for o in eligible), None, len(eligible), sum(o.claims for o in eligible), sum(o.pairs for o in eligible))
    reason = "no_successful_retrieval_text" if not had_source else "no_llm_output_after_retrieval" if not outputs else outputs[0].reason
    return Hallucination(None, reason)
