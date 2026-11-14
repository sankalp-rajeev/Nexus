"""Synthetic C1/C2/C4/C5 contracts; no benchmark or TRAIL fixtures."""
from datetime import datetime, timezone
import pytest

from nexus_agent.models import CompleteTrace, Span, SpanType
from services.detectors_v2 import hallucination as h, openinference as oi, repetition
from services.detectors_v2.normalization import argument_tokens, grounding_text, jaccard


def span(kind, inp='', out=None, *, error=None, tool='synthetic', index=1):
    return Span(trace_id='synthetic',span_id=str(index),agent_name='synthetic',span_type=kind,
        input=inp,output=out,error_type=error,duration_ms=1,client_timestamp=datetime(2025,1,1,tzinfo=timezone.utc),
        sdk_version='synthetic',metadata={'tool_name':tool})


def trace(spans, final='The synthetic measurement is forty units.'):
    return CompleteTrace(trace_id='synthetic',agent_name='synthetic',started_at=datetime(2025,1,1,tzinfo=timezone.utc),
        root_input='What is the synthetic measurement?',final_output=final,spans=spans,span_count=len(spans))


def wire(attrs, status='Ok'):
    return {'trace_id':'ab'*16,'spans':[{'trace_id':'ab'*16,'span_id':'cd'*8,
        'timestamp':'2025-01-01T00:00:00Z','duration':'PT1S','status_code':status,
        'span_attributes':{'openinference.span.kind':'TOOL','tool.name':'web_search',**attrs}}]}


@pytest.mark.parametrize('status,output,error', [('Error','synthetic failure',True),
    ('Ok','{"error":"synthetic"}',True),('Ok','{"is_error":true}',True),('Ok','Error: synthetic',True),
    ('Ok','SyntheticError: synthetic',True),('Ok','{"status":"failed"}',True),
    ('Ok','{"error":null}',False),('Ok','Synthetic external source text.',False),
    ('Ok','Error handling documentation is retrieved here.',False)])
def test_c1_only_successful_retrieval_is_retrieval(status,output,error):
    source=wire({'input.value':'{"query":"synthetic"}','output.value':output},status)
    mapped=oi.complete_trace(source).spans[0]
    assert mapped.span_type==(SpanType.TOOL_CALL if error else SpanType.RETRIEVAL)
    assert (mapped.error_type is not None)==error
    assert mapped.input=='{"query":"synthetic"}' and mapped.output==output


def test_c1_does_not_retag_unmatched_tool_or_mutate_source_view():
    s=span(SpanType.RETRIEVAL,out='Error: synthetic')
    s.metadata['otel.attributes']={'openinference.span.kind':'TOOL','tool.name':'web_search'}
    original=trace([s]); result=oi.adapt(original)
    assert original.spans[0].span_type==SpanType.RETRIEVAL
    assert result.spans[0].span_type==SpanType.TOOL_CALL
    s.metadata['otel.attributes']['tool.name']='unmatched'
    assert oi.adapt(original).spans[0].span_type==SpanType.RETRIEVAL


def tool(args='{"x":"SYNTHETIC, value!"}', name='synthetic', error=None):
    return span(SpanType.TOOL_CALL,args,tool=name,error=error)


def test_c2_fixed_three_in_six_regardless_of_success():
    repeated=[tool(error='SyntheticError') for _ in range(3)]
    assert repetition.loop(trace([repeated[0],tool(name='other1'),repeated[1],tool(name='other2'),tool(name='other3'),repeated[2]]))
    assert not repetition.loop(trace([repeated[0],tool(name='a'),tool(name='b'),repeated[1],tool(name='c'),tool(name='d'),repeated[2]]))
    assert not repetition.loop(trace(repeated[:2]))


def test_c2_normalization_and_jaccard_boundary_are_fixed():
    assert argument_tokens('HELLO,   world!')==argument_tokens('hello world')
    assert jaccard(frozenset('abcd'),frozenset('abcde'))==.8
    assert repetition.loop(trace([tool('"a b c d"'),tool('"a b c d e"'),tool('"a b c d"')] ))
    assert not repetition.loop(trace([tool('"a b c"'),tool('"a b c d e"'),tool('"a b c"')] ))
    assert (repetition.MIN_CALLS,repetition.WINDOW,repetition.MIN_JACCARD)==(3,6,.8)


def test_c2_counts_named_retrieval_as_executed_tool_operation():
    calls=[span(SpanType.RETRIEVAL,'{"query":"synthetic"}',tool='web_search') for _ in range(3)]
    assert repetition.loop(trace(calls))


def test_c4_case_accents_punctuation_numbers_and_global_source():
    assert grounding_text('CAFÉ, Inc. has 1,000 units')=='cafe inc has 1000 units'
    t=trace([span(SpanType.RETRIEVAL,out='Alice has a synthetic fact here.'),
             span(SpanType.RETRIEVAL,out='Bob has another synthetic fact here.')])
    assert h.entity_present_globally('Alice joined Bob in the synthetic project.',t)
    assert not h.entity_present_globally('MissingCompany has a synthetic fact.',t)


def test_c4_keeps_claim_splitting_model_values_and_threshold_external():
    t=trace([span(SpanType.RETRIEVAL,out='The synthetic measurement is forty units.')])
    seen=[]
    def values(pairs):
        seen.extend(pairs); return [.8]*len(pairs)
    score=h.score(t,'final',values)
    assert score.score==pytest.approx(.2) and seen
    assert all(c=='The synthetic measurement is forty units' for _,c in seen)


def test_c4_exact_gate_shortcut_does_not_need_model_predictions():
    t=trace([span(SpanType.RETRIEVAL,out='A synthetic source has factual measurement text.')],final='MissingCompany has a factual measurement.')
    def never(_): pytest.fail('Gate-forced min=0 cannot depend on model output')
    assert h.score(t,'final',never).score==1


def test_c5_final_vs_every_llm_and_no_future_source_leakage():
    source=span(SpanType.RETRIEVAL,out='Alice has a synthetic measurement of forty units.')
    early=span(SpanType.LLM_CALL,out='MissingCompany has a factual measurement.')
    late=span(SpanType.LLM_CALL,out='Alice has a synthetic measurement of forty units.')
    t=trace([early,source,late],final='Alice has a synthetic measurement of forty units.')
    assert h.score(t,'final',lambda pairs:[.9]*len(pairs)).score==pytest.approx(.1)
    assert h.score(t,'all_llm',lambda pairs:[.9]*len(pairs)).score==pytest.approx(.1)
    t2=trace([source,early,late],final=t.final_output)
    assert h.score(t2,'all_llm',lambda pairs:[.9]*len(pairs)).score==1


def test_c5_no_llm_after_retrieval_is_explicit_abstention():
    t=trace([span(SpanType.RETRIEVAL,out='A synthetic source has factual text for grounding.')])
    assert h.score(t,'all_llm',lambda pairs:[]).reason=='no_llm_output_after_retrieval'
