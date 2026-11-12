"""Render Phase 5 write-up from aggregate JSON; no experiment launches."""
from datetime import datetime
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.phase5.measurement import atomic_json
from scripts.phase5.followup import stats

RESULTS = ROOT / "results/phase5"


def read(name):
    return json.loads((RESULTS / (name+".json")).read_text(encoding="utf-8"))


def number(value, digits=3):
    return f"{value:.{digits}f}" if value is not None else "n/a"


def finish_ingestion():
    runs = [("initial", "ingestion_load", "l3_ingestion")]
    if (RESULTS/"ingestion_load_addon.json").exists():
        runs.append(("add-on", "ingestion_load_addon", "l3_ingestion/addon_30_40_60"))
    documents, steps = [], []
    for label, filename, folder in runs:
        data = read(filename)
        changed = False
        for step in data["steps"]:
            if "resources" not in step:
                path = ROOT / f"data/phase5/runs/{folder}/resources_{step['offered_rate_events_s']}.json"
                rows = [json.loads(line) for chunk in json.loads(path.read_text(encoding="utf-8")) for line in chunk.splitlines() if line.strip()]
                names = {r["Name"] for r in rows}
                step["resources"] = {name:dict(sampled_max_cpu_percent=max(float(r["CPUPerc"].strip("%")) for r in rows if r["Name"]==name),
                                              last_memory_usage=[r["MemUsage"] for r in rows if r["Name"]==name][-1]) for name in sorted(names)}
                changed = True
            steps.append(dict(step,run=label,source=f"results/phase5/{filename}.json"))
        if changed:
            atomic_json(RESULTS/(filename+".json"),data)
        documents.append(data)
    data = dict(steps=sorted(steps,key=lambda s:s["offered_rate_events_s"]), machine=documents[-1]["machine"],
                sources=[f"results/phase5/{r[1]}.json" for r in runs], API_calls=0,
                run_windows=[dict(run=r[0],started_at=d["started_at"],ended_at=d.get("ended_at"),machine=d["machine"]) for r,d in zip(runs,documents)],
                max_sustained_events_s=max((s["accepted_events_s"] for s in steps if s["sustainable"]),default=None),
                max_stable_lag_events_s=max((s["accepted_events_s"] for s in steps if not any(v["growing"] for v in s["lag_growth"].values())),default=None),
                criteria="unchanged reports/phase5/amendment_2.md; distinct run windows, no interpolation")
    failed = next((s for s in data["steps"] if any(v["growing"] for v in s["lag_growth"].values())),None)
    if failed:
        rising = [n for n,v in failed["lag_growth"].items() if v["growing"]]
        data["bottleneck"] = dict(service=" and ".join(rising) if rising else "generator/collector or incomplete persistence",
                                  evidence="consumer committed-lag growth and per-service CPU samples; not a causal isolated-service benchmark")
    data["persistence_checkpoint_exceptions"] = [dict(run=s["run"],offered_rate_events_s=s["offered_rate_events_s"],
        assembled_at_detection_drain=s["assembled_traces_at_detection_drain"],offered_traces=s["offered_traces"],
        assembled_post_run=s.get("assembled_traces_post_run"),
        note="Original strict sustainability verdict retained; detection and assembly have independent drains")
        for s in steps if not s["sustainable"] and not any(v["growing"] for v in s["lag_growth"].values())
        and s.get("assembled_traces_at_detection_drain") != s.get("offered_traces")]
    atomic_json(RESULTS/"ingestion_summary.json",data)
    return data


def spend_today():
    totals = {}
    for name, root in (("overnight", ""),("part_c","l3_heals"),("part_d_deepseek","gemini_side")):
        path = ROOT/"data/phase5/runs"/root/"budget.sqlite3"
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True) as conn:
            rows = [json.loads(r[0]) for r in conn.execute("SELECT record FROM calls")]
        today = [r for r in rows if datetime.fromisoformat(r["started_at"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()=="2026-11-12"]
        totals[name] = dict(all_calls=len(rows), all_provider_usd=sum(r.get("provider_actual_usd") or 0 for r in rows),
                           calendar_today_calls=len(today), calendar_today_provider_usd=sum(r.get("provider_actual_usd") or 0 for r in today),
                           unknown_calls=sum(r["status"]!="settled" for r in rows),
                           unknown_provider_reserved_usd=sum(r["provider_accounted_usd"] for r in rows if r["status"]!="settled"),
                           calendar_today_unknown_provider_reserved_usd=sum(r["provider_accounted_usd"] for r in today if r["status"]!="settled"))
    gemini = read("gemini_side")["current"]["gemini_budget"]
    data = dict(local_date="2026-11-12", timezone="America/New_York", deepseek=totals,
                deepseek_followup_provider_usd=totals["part_c"]["all_provider_usd"]+totals["part_d_deepseek"]["all_provider_usd"],
                deepseek_calendar_today_provider_usd=sum(v["calendar_today_provider_usd"] for v in totals.values()),
                deepseek_unknown_provider_reserved_usd=sum(v["unknown_provider_reserved_usd"] for v in totals.values()),
                gemini_actual_usage_priced_usd=gemini["actual_usage_priced_usd"], gemini_unknown_calls=gemini["unknown_calls"],
                cost_basis="Provider-reported token usage priced at verified published rates, not invoice; calendar today includes overnight calls after midnight",
                pricing_sources=["https://api-docs.deepseek.com/quick_start/pricing/","https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite"],
                pricing_verified="2026-11-12")
    atomic_json(RESULTS/"spend_today.json",data)
    return data


def main():
    a, sdk, c, d = read("heal_latency_cost"), read("sdk_overhead"), read("heal_concurrency"), read("gemini_side")
    ingestion = finish_ingestion()
    spend = spend_today()
    for data, folder, filename in ((c,"l3_heals","heal_concurrency"),(d,"gemini_side","gemini_side")):
        records = [json.loads(r.read_text(encoding="utf-8")) for r in (ROOT/"data/phase5/runs"/folder/"records").glob("*.json")]
        data["provenance"] = dict(dev_only=True, frozen_reference="phase4-test-scored",
             execution_commits=sorted({r.get("git_commit","not_recorded") for r in records}),
             source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
                ["scripts/phase5/followup.py","scripts/phase5/pipeline.py","scripts/phase5/measurement.py","scripts/phase5/gemini_critic.py"]},
             source_note="Final source hashes; per-heal execution commit set retained; no frozen code change",
             record_count=len(records))
        with sqlite3.connect(f"file:{(ROOT/'data/phase5/runs'/folder/'budget.sqlite3').as_posix()}?mode=ro",uri=True) as conn:
            calls = [json.loads(r[0]) for r in conn.execute("SELECT record FROM calls")]
        data["deepseek_attempt_audit"] = dict(attempts=len(calls),
            statuses=dict(Counter(r["status"] for r in calls)),
            errors=dict(Counter(r["error"] for r in calls if r.get("error"))),
            http_status_counts=dict(Counter(str(r.get("http_status")) for r in calls)),
            known_provider_usd=sum(r.get("provider_actual_usd") or 0 for r in calls),
            unknown_provider_reserved_usd=sum(r["provider_accounted_usd"] for r in calls if r["status"]!="settled"),
            note="Every attempt retained; unknown usage retains its full preflight reservation. Frozen actor transport policy retries eligible errors, up to five attempts.")
        for group in data.get("levels",[data.get("current",{})]):
            grouped = [r for r in records if folder=="gemini_side" or r["item_id"].startswith(f"c{group['concurrency']}-")]
            full = [r for r in grouped if r["status"]=="ok" and all(r.get("stage_status",{}).get(s)=="complete" for s in ("gate_repair","gate_heldout","gate_regression"))]
            group["gate_execution_s"] = stats([sum(r["stages_s"][s] for s in ("gate_repair","gate_heldout","gate_regression")) for r in full])
        atomic_json(RESULTS/(filename+".json"),data)
    p = ROOT/"reports/phase5/results.md"
    old = p.read_text(encoding="utf-8")
    part_a = old.split("## Part A:",1)[1].split("\n## Part B:",1)[0].split("\n## Part C:",1)[0]
    part_b = old.split("\n## Part B:",1)[1].split("\n## Part C:",1)[0].split("\n## Gemini side row",1)[0]
    # Detailed historical A/B sections remain verbatim; this script never reruns them.
    levels = c["levels"]
    current, baseline = d["current"], d["baseline"]
    total = a["L1"]["all_heals"]["total_s"]
    l2 = a["L2"]
    overhead = sdk["collector_healthy"]["paired_added_per_step"]
    checkpoint_notes = " ".join(
        f"At {s['offered_rate_events_s']} offered events/s, assembly was {s['assembled_at_detection_drain']}/{s['offered_traces']} at the detection-drain checkpoint and {s['assembled_post_run']}/{s['offered_traces']} in the subsequent read-only check. The original strict flag remains unchanged."
        for s in ingestion["persistence_checkpoint_exceptions"])
    lines = ["# Phase 5 results", "",
             f"The overnight DEV run completed all {total['n']} heals; median time was {total['p50']:.3f} seconds and p90 was {total['p90']:.3f} seconds.<br>",
             f"Mean provider usage-priced cost was ${l2['provider_usd']['mean']:.6f} per heal, {l2['provider_to_ledger_ratio_of_totals']:.2%} of the ledger estimate; input cache hits were {l2['cache_hit_rate_token_weighted']:.2%}.<br>",
             f"Ingestion sustained {number(ingestion['max_stable_lag_events_s'])} events/s without growing lag; {number(ingestion['max_sustained_events_s'])} events/s passed every strict checkpoint.<br>",
             f"Recorded-response SDK replay added {overhead['p50_ms']:.6f} ms median and {overhead['p99_ms']:.6f} ms p99 per step with the collector up; failed HTTP batches are lost.<br>",
             f"The separate Gemini side row completed {current['completed_n']}/{current['planned_n']} heals; its results and spend are reported apart from the headline.", "",
             "Headline sources: [L1/L2 JSON](../../results/phase5/heal_latency_cost.json), [L3 ingestion](../../results/phase5/ingestion_summary.json), [L3 heals](../../results/phase5/heal_concurrency.json), [L4 JSON](../../results/phase5/sdk_overhead.json), [Gemini JSON](../../results/phase5/gemini_side.json).", "",
             "## Part A:"+part_a.rstrip(), "", "## Part C: L3 load and heal concurrency", "",
             "### Ingestion, no provider calls", "",
             f"Machine: {ingestion['machine']['host']['cpu']}, {ingestion['machine']['host']['cores']} physical cores / {ingestion['machine']['host']['threads']} logical processors, {ingestion['machine']['host']['ram_bytes']/2**30:.2f} GiB host RAM; {ingestion['machine']['platform']}. Docker has {ingestion['machine']['docker']['cpus']} CPUs and {ingestion['machine']['docker']['ram_bytes']/2**30:.2f} GiB RAM.", "",
             "Recorded first-20 DEV spans receive fresh synthetic IDs. Warm-up is one 20-trace pass; each measured offered-rate step lasts at least 180 seconds. All spans, accepted/rejected counts, late detections and missing detections are retained. Latency runs from a trace's first HTTP submission until its classification is committed to Postgres, not per-span HTTP response latency. Trace batching creates within-trace bursts, particularly at low rates.", "",
             "The initial 1/5/20/80 events/s run and later 30/40/60 add-on are separate measurement windows. The add-on keeps the same warm-up, >=180-second holds, final-120-second lag-growth thresholds, acceptance/error checks and complete persistence requirements. All three requested add-on steps run, even if an earlier one saturates. Source JSON preserves both runs independently.", "",
             "| Run | Offered events/s | Hold s | Accepted events/s | Detected/offered traces | Assembled at detection-drain | Detection p50/p99 ms | Assembler / classifier lag slope events/s | Strict pass |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|" ]
    for s in ingestion["steps"]:
        lines.append(f"| {s['run']} | {s['offered_rate_events_s']} | {s['hold_s']:.1f} | {s['accepted_events_s']:.3f} | {s['detected_traces']}/{s['offered_traces']} | {s['assembled_traces_at_detection_drain']}/{s['offered_traces']} | {number(s['detection_latency_ms']['p50'])}/{number(s['detection_latency_ms']['p99'])} | {s['lag_growth']['assembler']['slope_events_s']:.3f} / {s['lag_growth']['classifier']['slope_events_s']:.3f} | {s['sustainable']} |")
    lines += ["", f"Highest rate passing all unchanged checks: **{number(ingestion['max_sustained_events_s'])} accepted events/s**. The bottleneck was the **{ingestion['bottleneck']['service']}**, based on growing committed consumer lag while assembler lag remained stable, supported by service CPU samples. Sustainability requires no growing final-120-second committed consumer lag, >=98% accepted target rate, no HTTP/sink error, complete detections and assembled traces at the original detection-drain checkpoint. The exact lag thresholds, samples, persistence counts and sampled resource maxima are in the JSON; this is a stepped bound, not an interpolated maximum.", "",
              f"The highest step with no growing consumer lag was **{number(ingestion['max_stable_lag_events_s'])} accepted events/s**. The table retains the original stricter checkpoint verdict as well. If assembly lags the independent classification drain by a final write, that checkpoint can conservatively fail even though all traces persist later; this is not proof of event loss or a lower service-capacity ceiling. Subsequent counts and original flags are both retained in ingestion_summary.json.", "",
              checkpoint_notes, "",
              "The unmodified deployed classifier uses its rule detectors, PatchCore/SVM, MiniLM embeddings and configured NLI model. This is distinct from the frozen Phase 4 offline detector used by heals. The classifier publishes classifications to Kafka; a measurement-only sink persists them to a separate Postgres table. Assembler persistence runs in parallel. The original image lacked its NLI cache and silently used its existing zero-score fallback; that pilot was stopped, retained under ignored run state and excluded. A read-only mount of the already-cached exact NLI model restored full configured inference offline. No detector code or thresholds changed.", "",
              "**Phase 4 detection used offline detector code, not the classifier container.** For DEV evidence, [phase4_handoff.py](../../services/critic/phase4_handoff.py#L177) reads saved predictions produced by [audit_dev.py](../../scripts/phase2_followup/audit_dev.py#L47) using the frozen services.detectors.pipeline. The scored Phase 4 path's [build_evidence()](../../bench/heal/test_phase.py#L79) directly calls detector_view, pipeline.compute_scores and pipeline.label in-process. Neither path depends on the deployed classifier container or its NLI cache. Its missing cache therefore did not affect Phase 4 detection. This confirmation inspected source only; sealed TEST data was neither loaded nor rerun.", "",
              "Paid critic/healer consumers were stopped during synthetic ingestion; no repairs/notifications were initiated. They remain stopped to keep all paid calls inside the capped controllers. Automatic approval review rejected advancing Kafka offsets because a future consumer could skip alerts; no offsets were changed. The synthetic backlog remains in Kafka, so starting a paid consumer needs separate attention. This safe alternative does not affect the measurements.", "",
              "### Paired heal concurrency, DeepSeek", "",
              f"Fixed seed {c['seed']}; 10 manifest occurrences drawn without replacement, exact IDs in followup_manifest.json and the result JSON. Concurrency 1 runs before 4. Fresh local response caches per heal; frozen seeds, prompts, gate and baseline reuse stay identical. No paid warm-up. Shared provider cap $1.50, including in-flight/unknown reservations.", "",
              "| Concurrency | Completed / planned | Full gate n | Wall s | Completed heals/hour | Full-gate heal total p50 s | Gate execution p50 s | All-completed time p50 s |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in levels:
        lines.append(f"| {s['concurrency']} | {s['completed_n']}/{s['planned_n']} | {s['full_gate_n']} | {s['elapsed_s']:.3f} | {s['completed_heals_per_hour']:.3f} | {number(s['full_gate_time_s']['p50'])} | {number(s['gate_execution_s']['p50'])} | {number(s['all_completed_time_s']['p50'])} |")
    lines += ["", "All statuses, not-started IDs, errors, timeouts, per-stage quantiles and decisions are retained in heal_concurrency.json. Throughput uses the full level wall clock, including worker startup and rejected/capped slots; completed throughput excludes unsuccessful slots. Full-gate quantiles require all three gate stages complete. Comparisons confound level order, provider/cache warming and stochastic critic patches, so they are descriptive and do not isolate a causal concurrency effect.", "",
              f"Part C retained **{c['deepseek_attempt_audit']['attempts']} API attempts**, with **1 transport error**, **0 timeouts** and all 20 terminal heal statuses OK. Known provider spend was **${c['deepseek_attempt_audit']['known_provider_usd']:.8f}**; **${c['deepseek_attempt_audit']['unknown_provider_reserved_usd']:.8f}** remains reserved for unknown usage. The RemoteProtocolError occurred at concurrency 4; the actor's unchanged retry policy recovered. Its unreported usage is not charged as zero or silently removed.", "",
              "## Part B:"+part_b.rstrip(), "", "## Gemini side row (Part D; separate from headline)", "",
              f"Exact model **{d['model']}**, confirmed by account models.list; returned model versions are recorded in the JSON. Same first 20 manifest occurrences, in order; concurrency 2, same as baseline. Only critic requests go to Google; all gate agent re-runs remain DeepSeek. Frozen prompts/system text, temperature 0.2, schema and local validation are unchanged. Transport adapts the forced strict DeepSeek propose_patch function to Gemini responseMimeType=application/json and responseJsonSchema with the identical schema. Thinking uses Gemini's minimum supported level, not a promise of zero thought tokens; usage accounting includes any thinking. No additional formatting retries are added.", "",
              "| Metric | DeepSeek baseline, same 20 | Gemini critic side row |", "|---|---:|---:|"]
    for label, key in (("Completed heals", "completed_n"),("Full-gate heals", "full_gate_n")):
        lines.append(f"| {label} | {baseline[key]} | {current[key]} |")
    for label,key,field in (("Critic HTTP call p50 ms","critic_call_latency_ms","p50"),("All completed time-to-heal p50 s","all_completed_time_s","p50"),("Full-gate time-to-heal p50 s","full_gate_time_s","p50")):
        lines.append(f"| {label} | {number(baseline[key][field])} | {number(current[key][field])} |")
    lines.append(f"| Per-heal critic stage p50 s (all calls/validation) | {number(baseline['per_stage_s']['critic_call']['p50'])} | {number(current['per_stage_s']['critic_call']['p50'])} |")
    lines += [f"| Critic usage-priced $/completed heal | {number(baseline['critic_cost_per_completed_heal_usd'],8)} | {number(current['critic_cost_per_completed_heal_usd'],8)} |", "",
              f"Descriptive decisions: baseline **{baseline['decisions_descriptive_only'].get('promoted',0)} promoted / {baseline['decisions_descriptive_only'].get('rejected',0)} rejected**; side row **{current['decisions_descriptive_only'].get('promoted',0)} promoted / {current['decisions_descriptive_only'].get('rejected',0)} rejected**. These are **not a re-estimate of Phase 4 repair or promotion rates**. Per-occurrence comparisons, denominators, errors and any cap-stopped/not-started slots are in gemini_side.json. If a cap prevents completion, matched-completed baseline metrics are also provided; the original 20-item baseline is never silently reduced.", "",
              f"Gemini spend: **${current['gemini_budget']['actual_usage_priced_usd']:.8f} / $2.00 cap**, across {current['gemini_budget']['calls']} calls. Gate DeepSeek spend: **${current['deepseek_budget']['provider_actual_usd']:.8f} / $0.75 cap**, across {d['deepseek_attempt_audit']['attempts']} attempts. All 20 completed; neither cap hit. There were {current['api_errors']} API errors and {current['timeouts']} timeouts; unknown Gemini calls: {current['gemini_budget']['unknown_calls']}. All API retries/uncertain calls retain cost reservations. Provider actual here means API-reported usage times verified paid rates, including cache/thinking; neither API response is an invoice. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) were verified 2026-11-12.", "",
              "## Part E: spend, limitations and validation", "",
              f"New Parts C/D known DeepSeek provider spend: **${spend['deepseek_followup_provider_usd']:.8f}**, plus **${spend['deepseek_unknown_provider_reserved_usd']:.8f}** retained for unknown usage; Gemini: **${spend['gemini_actual_usage_priced_usd']:.8f}**. Tracked calendar-day known DeepSeek spend, including last night's requests after midnight America/New_York: **${spend['deepseek_calendar_today_provider_usd']:.8f}**. Source: spend_today.json; historical ledgers are not reset. Account balance is checked through the read-only API and reported in the handoff, outside the experiment artifacts.", "",
              "Limits: one Windows machine, one overnight headline run, repeated source tasks/occurrences and small per-group L3/side-row samples. The recorded hourly provider latency drift is observational; order, cache, load and generated patch variation confound later comparisons. Gate counts are descriptive only. L4 is a deterministic stub-LLM replay using recorded DEV responses, excluding real provider/tool latency; sampled RSS has coarse realized intervals and no worst-case memory guarantee. Its historical source predates the subsequent SDK-only export-loss counters. Ingestion measures the deployed classifier's full configured path plus a measurement Postgres sink, not the Phase 4 offline detector implementation or paid repair throughput.", "",
              "Deviations are explicit in amendment_1.md and amendment_2.md: recorded-response L4, separate controlled recovery barrier, smaller L3 sample/two concurrency levels, local NLI cache repair, Gemini wire-format/minimal-thinking adaptation, cap censoring if present and sealed-TEST-dependent validation skips. All frozen checks before/after each part remain mandatory. Full-suite outcome and exact skip reasons are in analysis_validation.md and validation.json.", ""]
    p.write_text("\n".join(lines),encoding="utf-8")
    headline = dict(experiment_id="phase5_headline", L1=a["L1"], L2=a["L2"],
                    L3_ingestion_max_events_s=ingestion["max_sustained_events_s"], L3_heals=levels,
                    L3_ingestion_max_stable_lag_events_s=ingestion["max_stable_lag_events_s"],
                    L4_added_healthy_ms=sdk["collector_healthy"]["paired_added_per_step"],
                    gemini_completed=current["completed_n"], spend=spend)
    atomic_json(RESULTS/"headline.json",headline)


if __name__ == "__main__":
    main()
