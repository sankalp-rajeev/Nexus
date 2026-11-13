"""Render aggregate development tables and an uncommitted A3 review draft."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sdk'),str(ROOT)]
from scripts.external.evaluate_detectors_v2 import RUN
from scripts.external.score_trail import git


def metric(m):
    if m['estimate'] is None: return 'undefined'
    lo,hi=m['wilson95']
    return f"{m['estimate']:.4f} [{lo:.4f}, {hi:.4f}]"


def value(v):
    return 'undefined' if v is None else f'{v:.6f}'


def trail_rows(t,scope):
    lines=['| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] | F1 | Abstentions | Exclusions |',
           '| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |']
    for key,title in (('v1','v1'),('v2_'+scope,'v2 selected')):
        for cls in ('LOOP_DETECTED','TOOL_MISFIRE','HALLUCINATION'):
            v=t[key][cls]
            lines.append(f"| {title} | {cls} | {v['evaluated']} | {v['tp']} / {v['fp']} / {v['fn']} / {v['tn']} | {metric(v['precision'])} | {metric(v['recall'])} | {value(v['f1'])} | {sum(v['abstentions'].values())} | {sum(v['exclusions'].values())} |")
    return lines


def main():
    trail=json.loads((RUN/'trail_aggregate.json').read_text())
    nexus=json.loads((RUN/'nexus_aggregate.json').read_text())
    ts=json.loads((RUN/'trail_state.json').read_text()); ns=json.loads((RUN/'nexus_state.json').read_text())
    if ts['status']!='complete' or ns['status']!='complete': raise RuntimeError('Development evaluation incomplete')
    scope=trail['selection']['scope']; freeze=nexus['frozen_v2_commit']
    config=json.loads((ROOT/'services/detectors_v2/config.json').read_text())
    if scope!=config['c5_scope'] or scope!=nexus['selected_C5_scope']: raise RuntimeError('Scope changed after selection')
    lines=['# TRAIL v2 development evaluation','', '**development, not a result**','',
        'TRAIL dev and TRAIL-A are development data for this iteration. TRAIL-B remains sealed: no B trace or label was loaded, and no B detector evaluation occurred. NexusBench uses DEV only (359 rows); TEST trace JSON was never decoded or evaluated. No provider calls were made.','',
        '## Main merge, tests and isolation','',
        '- Fetched origin and merged origin/main with merge commit `d9fef595ae95d5c2d051aaf673611e500aa9ad77`; no conflicts or manual conflict resolutions. 328 merge tests passed, the freeze check passed, and the merge was pushed before v2 work.',
        '- Upstream README/dashboard/SDK release changes arrived through that requested merge. V2 work makes no further edits to those paths.',
        '- `detectors-v2` lives in new `services/detectors_v2/` modules. The original live classifier/default remains v1. Shared frozen files and thresholds are unchanged; `scripts/external/check_frozen.py` passes.',
        '- Original TRAIL v1 result, result report, scoring checkpoints and diagnostic observations are not rewritten. All raw new records and NLI memoization remain under excluded `data/external/trail/v2_development/`.',
        '- Final verification: 350 tests pass, including synthetic C1/C2/C4/both-C5 tests, structural DEV isolation, metric/selection contracts and exact-cache behavior. The 75-file shared freeze and unchanged live-path checks pass. Secret and verbatim-content scans cover explicit publication paths against the allowed 79 development traces/labels, never B.',
        '', '## Fixed design','',
        'The implementation and choices were fixed in [DESIGN.md](../../services/detectors_v2/DESIGN.md) before development evaluation:',
        '', '- C1: call the existing A1 adapter, retaining matched retrieval errors as TOOL_CALL. Recorded error status or explicit structured/prefixed error output qualifies; successful source operations stay retrieval. Output-only errors receive ToolOutputError. Names, arguments, outputs and existing errors are preserved.',
        '- C2: at least three same-tool calls in a window of six consecutive tool operations; lowercase, punctuation/symbol boundaries and whitespace normalization; pairwise token Jaccard >=0.8 for all pairs in the triple, regardless of success. Executed named/original-TOOL retrieval operations count as tool operations for repetition. Parameters were not tuned.',
        '- C4: the frozen entity extractor is retained; entity/source presence uses casefold, accent removal, punctuation/whitespace normalization and thousands-number canonicalization, searching all retrieved text. Claim splitting, NLI premise construction/model/revision and threshold 0.5034 are unchanged.',
        '- C5 final: final answer only. C5 all_llm: LLM outputs after a source operation, with only sources available in that output\'s prefix. Both preserve the registered readable-source gate and explicit abstentions. Trace hallucination is the worst eligible output.',
        '- Exact algebraic short-circuits skip inference when an entity gate forces a score of 1 or a worst-output score is already 1. Exact pinned-model pair memoization reuses identical entailments; no approximate pruning or fabricated softmax components.',
        '', '## Sole selection: C5 HALLUCINATION F1','',
        'Selection uses pooled eligible trace-level HALLUCINATION F1 on TRAIL dev + A, computed as 2TP/(2TP+FP+FN). A defined score beats undefined; final wins exact ties. This is the only selection step. Each scope\'s eligibility and abstentions are shown; NexusBench did not influence selection.','',
        '| Scope | Pooled F1 | TP / FP / FN | Evaluated | Abstentions | Exclusions | Dev F1 | A F1 |',
        '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for key in ('final','all_llm'):
        v=trail['selection'][key]
        d=trail['by_cohort']['dev']['v1']['v2_'+key]['HALLUCINATION']
        a=trail['by_cohort']['A']['v1']['v2_'+key]['HALLUCINATION']
        lines.append(f"| {key} | {value(v['f1'])} | {v['tp']} / {v['fp']} / {v['fn']} | {v['evaluated']} | {sum(v['abstentions'].values())} | {sum(v['exclusions'].values())} | {value(d['f1'])} | {value(a['f1'])} |")
    lines += ['',f'**Selected and frozen scope: `{scope}`**, config/code commit `{freeze}`. No C1/C2/C4 parameter or threshold selection was performed.','',
        '## TRAIL dev + A development tables','',
        'Membership is 15 dev + 64 A = 79; the previously known duplicate-span A trace remains the single conversion exclusion for both versions, leaving 78 converted traces. Gold labels and tool-origin qualification follow v1/A1. Null NLI/applicability cases are abstentions, never negatives. Wilson intervals are unrounded in private aggregate records; undefined denominators remain undefined.','',
        '### Original v1 mapping','']
    lines += trail_rows(trail['tables']['v1'],scope)
    lines += ['', '### C3 development mapping','',
        'Only the v2 Resource Abuse/Timeout (LOOP_DETECTED) prediction changes to **v2 LOOP OR v2 TOOL_MISFIRE**. The v1 baseline remains its original registered mapping in both tables. Other classes and all gold labels stay unchanged.','']
    lines += trail_rows(trail['tables']['C3'],scope)
    lines += ['', '### Development observations','',
        'On these development inputs, v2 LOOP gains 12 true positives and 3 false positives; v1 flags none. '
        'C1 restores 96 failed source operations to tool calls. V2 MISFIRE finds 2 of 3 gold positives with 7 false positives; '
        'the three-positive denominator is too small for a reliable general claim. All v2 MISFIRE-positive traces already '
        'fire v2 LOOP, so C3 has the same confusion counts as the original mapping here. '
        'Selected-scope HALLUCINATION confusion counts equal v1: normalization does not improve the trace decisions on this sample. '
        'Every-output C5 has more false positives and one more eligible trace than final-answer C5. '
        'These observations did not trigger any additional selection or implementation change.']
    for cohort in ('dev','A'):
        lines += ['',f'### Cohort {cohort}: original mapping','']
        lines += trail_rows(trail['by_cohort'][cohort]['v1'],scope)
    lines += ['', '### Abstention/exclusion reasons, pooled','',
        '| Version | Class | Type | Reason | Count |','| --- | --- | --- | --- | ---: |']
    for key,title in (('v1','v1'),('v2_'+scope,'v2 selected')):
        for cls,v in trail['tables']['v1'][key].items():
            for kind in ('abstentions','exclusions'):
                for reason,count in v[kind].items(): lines.append(f'| {title} | {cls} | {kind} | `{reason}` | {count} |')
    lines += ['',f"C1 restored {trail['c1_restored_error_spans']} errored retrieval spans to TOOL_CALL. Private NLI memo statistics: {trail['nli_cache']}. These are computational counts, not accuracy claims.",'',
        '## NexusBench DEV regression check','',
        'The existing detector_view is used on 359 DEV traces. Non-DEV rows are discarded on their split field before constructing a label record; trace IDs are filtered before trace JSON decoding. OTHER_FAILURE/RUN_ERROR are excluded from per-class metrics as in the original DEV contract. NLI non-applicability retains native NexusBench negative-flag semantics, unlike the TRAIL-specific abstention rule.','',
        'Both independent flags and priority-label views are shown to avoid conflating a detector change with label masking. The original three headline classes are HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT. Five-class macro also includes LOOP_DETECTED and TOOL_MISFIRE.','',
        '| Macro recall view | v1 | v2 | Delta | Drop >0.02 |','| --- | ---: | ---: | ---: | --- |']
    for key,delta in nexus['macro_recall_deltas'].items():
        lines.append(f"| {key} | {value(nexus['v1'][key])} | {value(nexus['v2'][key])} | {delta:+.6f} | {delta < -.02} |")
    lines += ['', '| Version | NORMAL traces | False alerts | False alerts / 1,000 NORMAL |','| --- | ---: | ---: | ---: |']
    for key in ('v1','v2'):
        r=nexus[key]
        lines.append(f"| {key} | {r['normal_traces']} | {r['false_alerts']} | {value(r['false_alerts_per_1000_NORMAL'])} |")
    lines += ['',f"**Regression flags:** macro-recall drop >0.02 = **{nexus['macro_recall_drop_gt_0.02']}**; any false-alert increase = **{nexus['false_alert_increase']}**. These flags are reported as observed and did not trigger tuning or reselection."]
    lines += ['', 'The priority-view regression comes from four gold MISFIRE traces that additionally fire v2 LOOP. '
        'The unchanged priority order emits LOOP for them, reducing MISFIRE priority recall from 34/34 to 30/34, '
        'while all 34 MISFIRE flags still fire internally. The added LOOP false positives lower its precision from '
        '1.0000 to 0.8947. No additional NORMAL trace is alerted. The five-class priority macro drops by 0.023529, '
        'crossing the requested 0.02 warning threshold. V1 remains live.']
    for key,title in (('classes','Independent detector flags'),('priority_classes','Priority-winning labels')):
        lines += ['',f'### {title}','',
            '| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |',
            '| --- | --- | ---: | --- | --- | --- |']
        for variant in ('v1','v2'):
            for cls,v in nexus[variant][key].items():
                lines.append(f"| {variant} | {cls} | {v['evaluated']} | {v['tp']} / {v['fp']} / {v['fn']} / {v['tn']} | {metric(v['precision'])} | {metric(v['recall'])} |")
    lines += ['', '## Freeze and review boundary','',
        f"- V2 frozen config/code commit: `{freeze}`; name `detectors-v2`; selected C5 scope `{scope}`.",
        '- NLI revision: `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`; unchanged frozen threshold file and model.',
        f"- Candidate evaluation code commit: `{ts['code_commit']}`. TRAIL runtime {ts['runtime_seconds']:.2f}s; NexusBench DEV runtime {ns['runtime_seconds']:.2f}s.",
        '- Draft [trail_prereg_a3.md](trail_prereg_a3.md) is a local review artifact and is intentionally not committed. No TRAIL-B scoring is authorized or performed by this development run.',
        '- All new commits contain code, synthetic tests, aggregate development numbers and protocol text only; no gated trace content or annotation descriptions.','']
    (ROOT/'reports/external/trail_v2_dev.md').write_text('\n'.join(lines),encoding='utf-8')
    draft=['# DRAFT - TRAIL pre-registration amendment A3','', '**FOR USER REVIEW - NOT COMMITTED - DO NOT SCORE TRAIL-B**','',
        '## Proposed frozen v2 configuration','',
        f"The proposed detector config is **detectors-v2**, frozen by commit **{freeze}**, selected scope **{scope}**. "
        'It uses new non-frozen modules only. V1 remains the live default and all v1 frozen files/thresholds are unchanged.','',
        'C1 retains recorded/error-output retrieval failures as TOOL_CALL; only successful source spans are retrieval. '
        'C2 is fixed at >=3 same-tool calls in any six-tool-call window, with pairwise normalized token Jaccard >=0.8 regardless of success. '
        'C4 checks normalized entities against all retrieved source text while preserving the pinned NLI model, claim splitting and threshold. '
        'C5 uses the development-selected scope and its registered causal/readability/abstention rules. Exact definitions are frozen in services/detectors_v2/DESIGN.md and config.json.','',
        '## Selection completed on development data only','',
        f"Final-answer F1: {value(trail['selection']['final']['f1'])}; every-post-retrieval-LLM-output F1: {value(trail['selection']['all_llm']['f1'])}. "
        f"The sole selection chose `{scope}` on pooled TRAIL dev + A. No threshold or repetition parameter was tuned. "
        'NexusBench DEV regression numbers are development checks, not held-out results; they did not change selection.','',
        f"Regression warnings to review: macro-recall drop >0.02 = {nexus['macro_recall_drop_gt_0.02']}; false-alert increase = {nexus['false_alert_increase']}.",'',
        '## Proposed C3 trace-level mapping','',
        '- LOOP_DETECTED gold: Resource Abuse + Timeout Issues; detected if **v2 LOOP_DETECTED OR v2 TOOL_MISFIRE** fires.',
        '- TOOL_MISFIRE gold: API errors + Formatting Errors on original TOOL-origin spans, including C1/A1 conversions.',
        '- HALLUCINATION gold: Language-only + Tool-related hallucination under the unchanged category normalization. Evaluate only applicable selected-scope traces; count/report abstentions by reason, never as positives or negatives.',
        '- PLAN_DRIFT and CONTEXT_BLEED are not scored on TRAIL.','',
        '## Sealed cohort and unchanged metrics','',
        'TRAIL-B remains the 63 committed A2 IDs (49 GAIA, 14 SWE Bench), fixed by seed 20261114. '
        'Its trace/label files have not been loaded for detector development/evaluation. Original six unjoinable GAIA labels remain outside A and B. '
        'Dataset revision remains b424ce63d5973d5dcd7169b1bc3c07ccdee276d1. '
        'B ID-list SHA-256: 7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f.','',
        'Unit: trace-level per class; independent detector flags with the explicit C3 OR for LOOP. '
        'Report TP/FP/FN/TN, per-class precision and recall with Wilson 95% intervals, per-source breakdown, '
        'full cohort/eligibility denominators, and all abstention/exclusion counts with registered reasons. '
        'Undefined denominators remain undefined. No post-result exclusions, tuning, taxonomy expansion, scope changes or retrieval-rule changes.','',
        '**scored once on TRAIL-B**','',
        'This is a prospective commitment, not an executed run. Before any B access, the user must review this draft, '
        'the reviewed A3 must be committed, and the frozen configuration/manifests/model must pass pre-flight checks. '
        'A crash-only continuation must be disclosed, preserve completed checkpoints, and never become a rerun for better metrics. '
        'No provider calls or gated-content publication; only code, protocol and aggregate numbers may be committed.','']
    draft_path=ROOT/'reports/external/trail_prereg_a3.md'
    if git('ls-files','--',draft_path.relative_to(ROOT).as_posix()): raise RuntimeError('A3 must remain uncommitted for review')
    draft_path.write_text('\n'.join(draft),encoding='utf-8')
    print(json.dumps({'dev_report_written':True,'A3_draft_written_uncommitted':True,'selected_scope':scope,'frozen_commit':freeze}))


if __name__=='__main__':
    main()
