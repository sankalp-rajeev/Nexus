"""Synthetic post-hoc feature/observer tests; no TRAIL or real NLI inference."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from scripts.external.diagnose_trail import (argument_difference, distribution, observe_claims,
    sequence_features, safe_error_type)


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
