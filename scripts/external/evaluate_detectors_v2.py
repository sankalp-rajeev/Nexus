"""Development-only v1/v2 evaluation. No TRAIL-B or NexusBench TEST execution.

Only C5 scope is selected, once from pooled TRAIL dev+A F1. All raw records and
the exact local NLI memo live below the excluded private directory.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"),str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from bench.detector_view import detector_view
from scripts.external import score_trail as original
from scripts.external.trail_dev_check import check_frozen
from scripts.external.trail_dev_check_a1 import applicability
from scripts.external.v2_data import PRIVATE, trail_catalog, trail_records, nexus_dev_rows, nexus_dev_traces
from scripts.external.v2_metrics import trail_table, choose_scope, nexus_table
from scripts.external.v2_nli_cache import EntailmentCache
from scripts.external.check_frozen import check as check_v1_freeze
from services.collector.openinference import complete_trace
from services.detectors import hallucination as frozen_h, pipeline as v1
from services.detectors_v2 import pipeline as v2, openinference as c1

RUN = PRIVATE / "v2_development"


def save(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    os.replace(temp,path)


def open_cache():
    # The authorized main merge changed SDK release metadata. Compare the live
    # path to that merge, and frozen detector bytes to their original tags.
    from huggingface_hub.constants import HF_HUB_CACHE
    check_v1_freeze()
    pin=json.loads((ROOT/'.github/model-revisions.json').read_text())[frozen_h.NLI_MODEL]
    diagnostic=json.loads((PRIVATE/'diagnostics/run_state.json').read_text())
    if diagnostic['status']!='complete' or diagnostic['preflight']['nli_revision']!=pin:
        raise RuntimeError('Prior A diagnostic cache provenance differs')
    for name,digest in diagnostic['immutable_sha256'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Original scored artifact changed')
    snapshot=Path(HF_HUB_CACHE)/('models--'+frozen_h.NLI_MODEL.replace('/','--'))/'snapshots'/pin
    target=ROOT/frozen_h.NLI_MODEL
    if not all((snapshot/n).is_file() for n in ('config.json','model.safetensors','tokenizer.json')):
        raise RuntimeError('Pinned local model cache missing; no download allowed')
    if (target/'.nexus-model-revision').read_text().strip()!=pin:
        raise RuntimeError('Local model revision differs')
    for path in snapshot.rglob('*'):
        if path.is_file() and path.suffix in {'.json','.safetensors','.txt','.model'}:
            with path.open('rb') as stream: expected=hashlib.file_digest(stream,'sha256').digest()
            with (target/path.relative_to(snapshot)).open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').digest()
            if expected!=actual: raise RuntimeError('Local model bytes differ from pinned cache')
    return EntailmentCache(RUN/'entailment.sqlite',pin)


def pack(scores, reason=None):
    flags=v1.fired(scores,v1.load_thresholds())
    return {'flags':flags,'label':next((c for c in v1.ORDER if flags[c]),'NORMAL'),
        'hallucination_reason':reason,'raw':{'loop':bool(scores.loop),'misfire':bool(scores.misfire),
            'bleed':scores.bleed,'drift':scores.drift,'hallucination':scores.halluc}}


def seed_A(cache,tid,view):
    path=PRIVATE/'diagnostics'/f'{tid}.json'
    record=json.loads(path.read_text())
    obs=record['nli_observations']
    if obs.get('claims'):
        premises=frozen_h.premise_units(frozen_h.retrieved_context(view))
        claims=frozen_h.claims(view.final_output or '',view.root_input or '')
        if len(claims)!=len(obs['claims']): raise RuntimeError('Diagnostic claim cache mismatch')
        for text,claim in zip(claims,obs['claims']):
            if len(text)!=claim['characters'] or len(premises)!=len(claim['per_premise_entailment']):
                raise RuntimeError('Diagnostic pair cache mismatch')
            for premise,value in zip(premises,claim['per_premise_entailment']):
                cache.seed((premise,text),value)
    raw=record['raw_outputs']
    return v1.Scores(raw['loop'],raw['misfire'],raw['bleed'],raw['drift'],raw['hallucination'])


def trail_phase():
    catalog=trail_catalog()
    excluded=set(json.loads(original.OUTPUT.read_text())['conversion_failure_ids'])
    ids=set(catalog['entries'])-excluded
    state_path=RUN/'trail_state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'running','completed_ids':[],
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'code_commit':original.git('rev-parse','HEAD').decode().strip(),
        'conversion_exclusions':sorted(excluded)}
    if state['status']=='complete': raise RuntimeError('TRAIL development phase already complete')
    save(state_path,state)
    records_dir=RUN/'trail'; records_dir.mkdir(exist_ok=True)
    started=time.perf_counter()
    with (RUN/'runtime.log').open('a',encoding='utf-8') as log:
        with redirect_stdout(log),redirect_stderr(log): cache=open_cache()
        try:
            for tid,row,source,label in trail_records(ids-set(state['completed_ids'])):
                with redirect_stdout(log),redirect_stderr(log):
                    base=detector_view(complete_trace(source).model_dump(mode='json'))
                    updated=c1.adapt(base)
                    gold,_,_=original.map_labels(label,base)
                    if row['cohort']=='A':
                        old=seed_A(cache,tid,base)
                    else:
                        model=frozen_h._nli(); original_predict=model.predict; model.predict=cache.predict
                        try: old=v1.compute_scores(base)
                        finally: model.predict=original_predict
                    _,reason=applicability(base)
                    new_final=v2.compute_scores(updated,scope='final',entailments=cache.entailments)
                    new_all=v2.compute_scores(updated,scope='all_llm',entailments=cache.entailments)
                    record={'trace_id':tid,'cohort':row['cohort'],'split':row['split'],'gold':gold,
                        'v1':pack(old,reason),'v2_final':pack(new_final,new_final.hallucination_reason),
                        'v2_all_llm':pack(new_all,new_all.hallucination_reason),
                        'c1_error_spans_restored':sum(bool(s.metadata.get('v2.retrieval_error_kept_as_tool')) for s in updated.spans)}
                    save(records_dir/f'{tid}.json',record)
                state['completed_ids'].append(tid); save(state_path,state)
                print(json.dumps({'TRAIL_development_completed':len(state['completed_ids']),'of':78}),flush=True)
        finally: cache.close()
    records=[json.loads((records_dir/f'{tid}.json').read_text()) for tid in sorted(ids)]
    records += [{'trace_id':tid,'cohort':catalog['entries'][tid]['cohort'],'split':catalog['entries'][tid]['split'],'conversion_failure':True} for tid in sorted(excluded)]
    final=trail_table(records,'v2_final')['HALLUCINATION']
    all_llm=trail_table(records,'v2_all_llm')['HALLUCINATION']
    selected=choose_scope(final,all_llm)
    selection={'selection_data':'TRAIL dev + TRAIL-A only; development, not a result','scope':selected,
        'final':final,'all_llm':all_llm,'tie_rule':'final wins exact ties','parameters_tuned':False}
    if (RUN/'selection.json').exists() and json.loads((RUN/'selection.json').read_text())!=selection:
        raise RuntimeError('Existing C5 choice differs')
    save(RUN/'selection.json',selection)
    aggregate={'scope':'development, not a result','cohorts':{'dev':15,'A':64,'conversion_exclusions':len(excluded)},
        'selection':selection,'tables':{mapping:{variant:trail_table(records,variant,mapping) for variant in ('v1','v2_final','v2_all_llm')} for mapping in ('v1','C3')},
        'by_cohort':{cohort:{mapping:{variant:trail_table([r for r in records if r['cohort']==cohort],variant,mapping) for variant in ('v1','v2_final','v2_all_llm')} for mapping in ('v1','C3')} for cohort in ('dev','A')},
        'c1_restored_error_spans':sum(r.get('c1_error_spans_restored',0) for r in records),
        'nli_cache':{'seeded_A_pairs':cache.seeded,'hits':cache.hits,'misses':cache.misses}}
    save(RUN/'trail_aggregate.json',aggregate)
    state['status']='complete'; state['runtime_seconds']=time.perf_counter()-started; save(state_path,state)
    print(json.dumps({'TRAIL_development_status':'complete','C5_choice':selected,'final_F1':final['f1'],'all_llm_F1':all_llm['f1'],'runtime_seconds':state['runtime_seconds']}),flush=True)


def nexus_phase():
    selection=json.loads((RUN/'selection.json').read_text())
    scope=selection['scope']
    if v2.load_config()['c5_scope']!=scope: raise RuntimeError('Freeze selected C5 config before regression evaluation')
    rows=nexus_dev_rows()
    if len(rows)!=359: raise RuntimeError('NexusBench DEV count differs from 359')
    ids={r['trace_id'] for r in rows}; traces=nexus_dev_traces(ids)
    state_path=RUN/'nexus_state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'running','completed_ids':[],
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'frozen_v2_commit':original.git('rev-parse','HEAD').decode().strip(),'scope':scope}
    if state['status']=='complete': raise RuntimeError('NexusBench development phase already complete')
    save(state_path,state)
    records_dir=RUN/'nexus'; records_dir.mkdir(exist_ok=True)
    started=time.perf_counter()
    with (RUN/'runtime.log').open('a',encoding='utf-8') as log:
        with redirect_stdout(log),redirect_stderr(log): cache=open_cache()
        try:
            for row in rows:
                tid=row['trace_id']
                if tid in state['completed_ids']: continue
                with redirect_stdout(log),redirect_stderr(log):
                    view=detector_view(traces[tid])  # Existing DEV detector adapter, no OI retagging.
                    model=frozen_h._nli(); original_predict=model.predict; model.predict=cache.predict
                    try: old=v1.compute_scores(view)
                    finally: model.predict=original_predict
                    new=v2.compute_scores(view,scope=scope,entailments=cache.entailments)
                    save(records_dir/f'{tid}.json',{'trace_id':tid,'gold':row['label'],'v1':pack(old),'v2':pack(new,new.hallucination_reason)})
                state['completed_ids'].append(tid); save(state_path,state)
                if len(state['completed_ids'])%10==0:
                    print(json.dumps({'NexusBench_DEV_completed':len(state['completed_ids']),'of':359}),flush=True)
        finally: cache.close()
    records=[json.loads((records_dir/f'{tid}.json').read_text()) for tid in sorted(ids)]
    a,b=nexus_table(records,'v1'),nexus_table(records,'v2')
    macro_keys=('macro_recall_five_flags','macro_recall_headline_flags','macro_recall_five_priority','macro_recall_headline_priority')
    drops={key:b[key]-a[key] for key in macro_keys}
    aggregate={'scope':'development, not a result','v1':a,'v2':b,'macro_recall_deltas':drops,
        'macro_recall_drop_gt_0.02':any(v<-.02 for v in drops.values()),
        'false_alert_increase':b['false_alerts_per_1000_NORMAL']>a['false_alerts_per_1000_NORMAL'],
        'selected_C5_scope':scope,'frozen_v2_commit':state['frozen_v2_commit']}
    save(RUN/'nexus_aggregate.json',aggregate)
    state['status']='complete'; state['runtime_seconds']=time.perf_counter()-started; save(state_path,state)
    print(json.dumps({'NexusBench_DEV_status':'complete','macro_recall_deltas':drops,'macro_recall_drop_gt_0.02':aggregate['macro_recall_drop_gt_0.02'],'false_alert_increase':aggregate['false_alert_increase'],'runtime_seconds':state['runtime_seconds']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['trail','nexus'],required=True)
    args=parser.parse_args()
    RUN.mkdir(parents=True,exist_ok=True)
    logging.getLogger('transformers').setLevel(logging.ERROR)
    try:
        check_frozen()
        (trail_phase if args.phase=='trail' else nexus_phase)()
    except BaseException as exc:
        print(json.dumps({'STOP':'development evaluation failed','type':type(exc).__name__}),flush=True)
        raise SystemExit(1) from None
