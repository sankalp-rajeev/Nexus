"""Synthetic metrics, taxonomy, location, and structural loader tests only."""
import json
from types import SimpleNamespace
import pytest

from scripts.external.score_trail import (CLASSES, add_observation, fresh_counts,
    load_requested, map_labels, normalize_category, ratio, resolve_location, summarize, wilson)


def view():
    return SimpleNamespace(spans=[SimpleNamespace(span_id=f"{i:016x}", metadata={
        "otel.attributes": {"openinference.span.kind": kind}}) for i, kind in ((1,"LLM"),(2,"TOOL"),(3,"TOOL"))])


def error(category, position=2):
    return {"category": category, "location": f"span {position:016x}"}


def test_wilson_known_values_and_zero_denominators():
    assert wilson(50,100) == pytest.approx([0.4038315304,0.5961684696])
    assert wilson(0,10) == pytest.approx([0.0,0.2775327999])
    assert wilson(10,10) == pytest.approx([0.7224672001,1.0])
    assert wilson(0,0) is None
    assert ratio(0,0) == {"estimate":None,"denominator":0,"numerator":0,"wilson95":None}


@pytest.mark.parametrize("x,n", [(-1,10),(11,10),(0,-1)])
def test_invalid_binomial_counts(x,n):
    with pytest.raises(ValueError): wilson(x,n)


def test_confusion_counts_precision_and_recall_denominators():
    counts=fresh_counts()
    for gold,pred in ((True,True),(False,True),(True,False),(False,False),(True,True)):
        add_observation(counts,gold,pred)
    result=summarize(counts)
    assert [result[k] for k in ('tp','fp','fn','tn','evaluated','gold_positive')]==[2,1,1,1,5,3]
    assert result['precision']==ratio(2,3) and result['recall']==ratio(2,3)


@pytest.mark.parametrize("gold,pred", [(True,True),(True,False),(False,True),(False,False)])
def test_abstentions_are_never_positives_or_negatives(gold,pred):
    counts=fresh_counts()
    add_observation(counts,gold,pred,abstention='no_successful_retrieval_text')
    assert summarize(counts)['evaluated']==0
    assert counts['abstentions']=={'no_successful_retrieval_text':1}


def test_exclusion_precedes_abstention_and_unexplained_missing_is_error():
    counts=fresh_counts()
    add_observation(counts,None,None,exclusion='malformed_category_or_location',abstention='no_checkable_claims')
    assert counts['abstentions']=={} and counts['exclusions']=={'malformed_category_or_location':1}
    with pytest.raises(ValueError): add_observation(counts,None,False)


@pytest.mark.parametrize("category,cls", [('Resource Abuse','LOOP_DETECTED'),(' Timeout__Issues! ','LOOP_DETECTED'),
    ('API errors','TOOL_MISFIRE'),('Formatting Errors','TOOL_MISFIRE'),('Language-only','HALLUCINATION'),
    ('Language-only hallucination','HALLUCINATION'),('Tool-related hallucination','HALLUCINATION')])
def test_exact_registered_label_mapping(category,cls):
    gold,_,_=map_labels({'errors':[error(category)]},view())
    assert gold=={c:c==cls for c in CLASSES}


def test_no_substring_fuzzy_plural_or_unscored_category_expansion():
    labels={'errors':[error(c) for c in ('Resource Abuse extended','API error','Tool-related hallucinations','Goal Deviation','Context Errors')]}
    gold,_,audit=map_labels(labels,view())
    assert gold==dict.fromkeys(CLASSES,False) and sum(audit.values())==5
    assert all(len(key)==64 for key in audit)


def test_multilabel_or_and_tool_origin_survives_retrieval_tag():
    v=view()
    v.spans[1].span_type='retrieval'
    gold,loc,_=map_labels({'errors':[error(c) for c in ('Resource Abuse','API errors','Language-only')]},v)
    assert all(gold.values()) and loc==dict.fromkeys(CLASSES,[1])


def test_misfire_non_tool_is_negative_unresolved_is_unknown_positive_overrides():
    gold,_,_=map_labels({'errors':[error('API errors',1)]},view())
    assert gold['TOOL_MISFIRE'] is False
    missing={'category':'Formatting Errors','location':'unresolved synthetic location'}
    gold,_,_=map_labels({'errors':[missing]},view())
    assert gold['TOOL_MISFIRE'] is None and gold['LOOP_DETECTED'] is False
    gold,loc,_=map_labels({'errors':[missing,error('API errors')]},view())
    assert gold['TOOL_MISFIRE'] is True and loc['TOOL_MISFIRE'] is None


def test_location_ambiguity_and_malformed_category():
    positions={f'{1:016x}':0,f'{2:016x}':1}
    assert resolve_location(f'{1:016x} and {2:016x}',positions) is None
    assert resolve_location(f'span {2:016x}',positions)==1
    gold,_,_=map_labels({'errors':[{'category':None}]},view())
    assert all(v is None for v in gold.values())


def test_mapping_never_reads_descriptions_evidence_impact_or_scores():
    class Guard(dict):
        def get(self,key,*args):
            assert key not in {'evidence','description','impact','scores'}
            return super().get(key,*args)
    label=Guard(errors=[Guard(error('Resource Abuse'))],scores=object())
    assert map_labels(label,view())[0]['LOOP_DETECTED'] is True


def test_loader_filters_ids_before_any_outside_file_open_or_label_decode(tmp_path):
    wanted,outside=f'{1:032x}',f'{2:032x}'
    (tmp_path/'a_trace.json').write_text(json.dumps({'trace_id':wanted,'spans':[]}))
    (tmp_path/'a_label.json').write_text(json.dumps({'trace_id':wanted,'errors':[]}))
    entries={outside:{'split':'gaia','paths':{'trace':'NEVER_OPEN_TRACE','labels':'NEVER_OPEN_LABEL'}},
             wanted:{'split':'gaia','paths':{'trace':'a_trace.json','labels':'a_label.json'}}}
    decoded=[]
    def decoder(blob):
        value=json.loads(blob); decoded.append(value['trace_id']); return value
    records=list(load_requested(entries,{wanted},tmp_path,decode=decoder))
    assert len(records)==1 and decoded==[wanted,wanted] and outside not in decoded


def test_loader_join_is_by_id_and_missing_request_fails(tmp_path):
    tid=f'{1:032x}'
    (tmp_path/'trace').write_text(json.dumps({'trace_id':tid}))
    (tmp_path/'label').write_text(json.dumps({'trace_id':f'{2:032x}'}))
    rows={tid:{'split':'gaia','paths':{'trace':'trace','labels':'label'}}}
    with pytest.raises(RuntimeError,match='join mismatch'): list(load_requested(rows,{tid},tmp_path))
    with pytest.raises(RuntimeError,match='absent'): list(load_requested({}, {tid},tmp_path))
