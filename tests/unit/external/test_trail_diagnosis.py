"""Synthetic post-hoc feature/observer tests; no TRAIL or real NLI inference."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from scripts.external.diagnose_trail import (argument_difference, distribution, observe_claims,
    sequence_features, safe_error_type)
from scripts.external.report_trail_diagnosis import aggregate, histogram, original_exact_repeat_status


def step(tool='synthetic', args='{}', *, ok=True, position=0):
    return {'tool':tool,'args_text':args,'raw_input':args,'ok':ok,'position':position}


@pytest.mark.parametrize('a,b,expected', [
    ('{"a":1}', '{"a":1}', 'exact'),
    ('{"a":1}', '{ "a" : 1 }', 'whitespace_only'),
    ('{"a":1,"b":2}', '{"b":2,"a":1}', 'json_formatting_or_key_order_only'),
    ('{"id":1}', '{"id":2}', 'ID_pattern_or_ID_field_only'),
    ('{"x":"C-123"}', '{"x":"C-456"}', 'ID_pattern_or_ID_field_only'),
    ('a'*100+'x', 'a'*100+'y', 'small_edit_similarity_at_least_0.90'),
    ('short', 'completely different', 'other_changed_arguments'),
])
def test_argument_difference(a,b,expected):
    assert argument_difference(a,b)==expected


def test_longest_run_and_filtered_span_interleaving_are_distinct():
    result=sequence_features([step(position=0),step(position=3),step(position=6)])
    assert result['longest_successful_identical_consecutive_run']==3
    assert result['equal_consecutive_tool_pairs_with_other_spans_between']==2
    result=sequence_features([step(),step('other',position=1),step(position=2)])
    assert result['longest_successful_identical_consecutive_run']==1
    assert result['exact_repeat_pairs_separated_by_other_tool_steps']==1


def test_errors_break_successful_runs_and_empty_is_zero():
    assert sequence_features([])['longest_successful_identical_consecutive_run']==0
    values=[step(),step(ok=False),step(),step()]
    assert sequence_features(values)['longest_successful_identical_consecutive_run']==2


def test_distribution_and_error_types_never_export_arbitrary_error_text():
    assert distribution([])=={'n':0}
    assert distribution([1,3])['median']==2
    assert safe_error_type('SyntheticError')=='SyntheticError'
    assert safe_error_type('synthetic exception message with detail').startswith('non_class_string_sha256_')


class FakeTokenizer:
    def __call__(self, a, b=None, *, truncation=False, max_length=None, add_special_tokens=True, padding=False):
        if isinstance(a,str):
            return {'input_ids':list(range(len(a.split())))}
        ids=[]; encodings=[]
        for x,y in zip(a,b):
            nx,ny=len(x.split()),len(y.split())
            while truncation and nx+ny+3>max_length:
                if nx>=ny: nx-=1
                else: ny-=1
            seqs=[None]+[0]*nx+[None]+[1]*ny+[None]
            ids.append(list(range(len(seqs))))
            encodings.append(SimpleNamespace(sequence_ids=seqs))
        class Batch(dict): pass
        result=Batch(input_ids=ids); result.encodings=encodings
        return result


def test_probability_observer_preserves_values_and_observes_gate_and_truncation():
    premises=['synthetic source has many words here','another synthetic source has words here']
    claims=['UnseenCompany has a synthetic measurement','the synthetic source has a measurement']
    pairs=[(p,c) for c in claims for p in premises]
    probs=[[.05,.9,.05],[.1,.8,.1],[.3,.3,.4],[.1,.7,.2]]
    original=deepcopy(probs)
    out=observe_claims(pairs,probs,claims,premises,FakeTokenizer(),8)
    assert probs==original
    assert out['claims'][0]['raw_best_entailment']==.9
    assert out['claims'][0]['best_entailment_after_entity_gate']==0
    assert out['claims'][0]['allowed_premise_units']==0
    assert out['claims'][1]['best_entailment_after_entity_gate']==.7
    assert all(p['removed_tokens']>0 and p['kept_tokens']==8 for p in out['pairs'])
    assert all(p['removed_tokens']==p['removed_premise_tokens']+p['removed_claim_tokens'] for p in out['pairs'])


def test_histogram_sorts_numerically():
    assert list(histogram([10,2,2,1]))==['1','2','10']


def test_any_status_exact_runs_do_not_imply_successful_loop_runs():
    steps=[{'tool':'synthetic','args_sha256':'same','ok':ok} for ok in (True,False,True)]
    result=original_exact_repeat_status([{'original_tool_steps':steps}])
    assert result['longest_run_ignoring_success_histogram']=={'3':1}
    assert result['pair_counts']=={'adjacent_exact_pairs_all_statuses':2,
        'adjacent_exact_pairs_both_successful':0,'adjacent_exact_pairs_with_error':2}


def test_posthoc_aggregate_keeps_saved_scope_and_diagnostic_values_separate():
    records=[]
    for i in range(63):
        eligible=i<19
        empty_sequence=sequence_features([])
        records.append({'trace_id':f'{i+1:032x}',
            'gold_classes':{'LOOP_DETECTED':i<22,'TOOL_MISFIRE':i<2,'HALLUCINATION':i<5},
            'hallucination_applicability':{'reached':eligible,'reason':None if eligible else 'no_successful_retrieval_text'},
            'raw_pipeline_label':'HALLUCINATION' if eligible else 'NORMAL',
            'raw_outputs':{'loop':False,'misfire':False,'hallucination':1.0 if eligible else None},
            'flags':{'LOOP_DETECTED':False,'TOOL_MISFIRE':False,'HALLUCINATION':eligible,'PLAN_DRIFT':False,'CONTEXT_BLEED':False},
            'decision_differences':[], 'loop_visible':empty_sequence,'loop_original_tool':empty_sequence,
            'original_tool_steps':[],
            'nesting_original_tools':{'tool_steps':0,'with_agent_ancestor':0},'nesting_visible_tools':{'tool_steps':0,'with_agent_ancestor':0},
            'errors':{'all_span_error_types':{},'original_tool_error_types':{},'visible_tool_error_types':{},
                'all_span_errors':0,'original_tool_errors':0,'visible_tool_errors':0,'retagged_retrieval_errors':0,'retry_patterns':{}},
            'claim_count':1 if eligible else 0,'retrieved_characters':100 if eligible else 0,'hallucination_labels_on_eligible':{},
            'nli_observations':{'claims':[{'best_entailment_after_entity_gate':0,'raw_best_entailment':.9,'allowed_premise_units':0}] if eligible else [],
                'pairs':[{'full_tokens':5,'removed_tokens':0,'removed_premise_tokens':0,'removed_claim_tokens':0}] if eligible else []}})
    state={'runtime_seconds':1,'diagnostic_code_commit':'synthetic','model_max_pair_tokens':512}
    result={'provenance':{'detector_thresholds':{'HALLUCINATION':{'threshold':.5034}}}}
    out=aggregate(records,state,result,{})
    assert out['decision_difference_trace_ids']==[]
    assert out['fresh_pipeline_label_counts']['HALLUCINATION']==19
    assert out['fresh_pipeline_label_counts']['NORMAL']==44
    assert out['loop_positive']['frozen_visible']['longest_run_histogram']=={'0':22}
    assert out['hallucination']['gate_forced_zero_claims']==19
    assert out['hallucination']['pairs_truncated']==0
    assert out['raw_NLI_null_traces']==44
    with pytest.raises(RuntimeError): aggregate(records[:-1],state,result,{})
