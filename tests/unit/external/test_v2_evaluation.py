"""Synthetic loader, exact memoization, C3 and sole-selection contracts."""
import json
from types import SimpleNamespace
import numpy as np
import pytest

from scripts.external.v2_data import nexus_dev_rows, nexus_dev_traces
from scripts.external.v2_metrics import choose_scope, f1, trail_table
from scripts.external.v2_nli_cache import EntailmentCache


def test_nexus_dev_filter_precedes_trace_json_decode(tmp_path):
    labels=tmp_path/'labels.csv'
    labels.write_text('trace_id,split,label\nwanted,dev,NORMAL\nsealed,test,NEVER_USE\n')
    assert nexus_dev_rows(labels)==[{'trace_id':'wanted','split':'dev','label':'NORMAL'}]
    traces=tmp_path/'traces'
    traces.write_text('{"trace_id": "sealed", INVALID SEALED CONTENT\n'+json.dumps({'trace_id':'wanted','spans':[]})+'\n')
    decoded=[]
    def decode(blob):
        value=json.loads(blob); decoded.append(value['trace_id']); return value
    assert set(nexus_dev_traces({'wanted'},traces,decode=decode))=={'wanted'}
    assert decoded==['wanted']


def test_C5_F1_only_selection_and_final_tie_break():
    a={'tp':1,'fp':1,'fn':0}; b={'tp':1,'fp':0,'fn':0}
    assert choose_scope(a,b)=='all_llm' and choose_scope(b,a)=='final'
    assert choose_scope(a,a)=='final'
    assert f1({'tp':0,'fp':0,'fn':0}) is None


def test_C3_changes_only_v2_LOOP_prediction_and_preserves_abstention():
    flags={'LOOP_DETECTED':False,'TOOL_MISFIRE':True,'HALLUCINATION':False}
    row={'gold':{'LOOP_DETECTED':True,'TOOL_MISFIRE':False,'HALLUCINATION':True},
         'v1':{'flags':flags,'hallucination_reason':'no_successful_retrieval_text'},
         'v2_final':{'flags':flags,'hallucination_reason':'no_successful_retrieval_text'}}
    assert trail_table([row],'v2_final','v1')['LOOP_DETECTED']['fn']==1
    assert trail_table([row],'v2_final','C3')['LOOP_DETECTED']['tp']==1
    assert trail_table([row],'v1','C3')['LOOP_DETECTED']['fn']==1
    assert trail_table([row],'v2_final','C3')['HALLUCINATION']['evaluated']==0


def test_entailment_cache_never_fabricates_missing_softmax_components(tmp_path,monkeypatch):
    calls=[]
    def predict(pairs,**kwargs):
        calls.append(list(pairs)); return np.asarray([[.1,.7,.2] for _ in pairs],dtype=np.float32)
    monkeypatch.setattr('scripts.external.v2_nli_cache.frozen._nli',lambda:SimpleNamespace(predict=predict))
    cache=EntailmentCache(tmp_path/'cache.sqlite','synthetic-revision')
    pair=('synthetic premise','synthetic claim')
    cache.seed(pair,.7)
    assert cache.entailments([pair])==[.7] and calls==[]
    result=cache.predict([pair],apply_softmax=True,batch_size=16)
    assert len(calls)==1 and result[0].tolist()==pytest.approx([.1,.7,.2])
    assert cache.predict([pair],apply_softmax=True,batch_size=16).tolist()==result.tolist() and len(calls)==1
    assert cache.entailments([pair])==[float(np.float32(.7))]
    cache.close()
