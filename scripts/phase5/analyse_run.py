"""Offline aggregate analysis of the registered DEV run; never reads TEST."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data/phase5/runs"
SEED = 2026111201
BOOTSTRAPS = 10000
STAGES = ("detect", "classify", "critic_call", "gate_repair", "gate_heldout", "gate_regression")
GATES = STAGES[3:]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def group_of(record):
    states = record["stage_status"]
    if all(states[s] == "complete" for s in GATES):
        return "full_gate"
    if record["gate_decision"] == "rejected" and all(states[s] == "skipped" for s in GATES):
        return "fast_exit"
    return "partial_or_interrupted"


def percentiles(values, key, ci=True):
    a = np.asarray(values, dtype=float)
    if not len(a):
        return dict(n=0, p50=None, p90=None, ci95_p50=None, ci95_p90=None)
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError("Invalid or missing durations must be reported, not silently dropped")
    point = np.quantile(a, [.5, .9], method="linear")
    out = dict(n=len(a), p50=float(point[0]), p90=float(point[1]))
    if ci:
        seed = int.from_bytes(hashlib.sha256(f"{SEED}:{key}".encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        samples = a[rng.integers(0, len(a), size=(BOOTSTRAPS, len(a)))]
        estimates = np.quantile(samples, [.5, .9], axis=1, method="linear")
        bounds = np.quantile(estimates, [.025, .975], axis=1, method="linear")
        out.update(ci95_p50=bounds[:, 0].tolist(), ci95_p90=bounds[:, 1].tolist(), bootstrap_seed=seed)
    return out


def mean_median(values):
    known = [v for v in values if v is not None]
    return dict(n=len(known), missing=len(values) - len(known),
                mean=float(np.mean(known)) if known else None,
                median=float(np.median(known)) if known else None,
                total=float(sum(known)))


def latency_group(records, name):
    total = sum(r["total_s"] for r in records)
    result = dict(total_s=percentiles([r["total_s"] for r in records], name + ":total"),
                  status_counts=dict(Counter(r["status"] for r in records)), stages={})
    stage_sum = 0.0
    for stage in STAGES:
        ran = [r["stages_s"][stage] for r in records if r["stage_status"][stage] in {"complete", "error"} and r["stages_s"][stage] is not None]
        seconds = sum(ran)
        stage_sum += seconds
        result["stages"][stage] = dict(percentiles(ran, name + ":" + stage),
            state_counts=dict(Counter(r["stage_status"][stage] for r in records)),
            sum_s=seconds, aggregate_share_of_total=seconds / total if total else None)
    result["aggregate_total_s"] = total
    result["unattributed_overhead_s"] = total - stage_sum
    result["unattributed_share"] = (total - stage_sum) / total if total else None
    return result


def analyse():
    manifest = load(ROOT / "reports/phase5/sample_manifest.json")
    records = []
    for item in manifest["items"]:
        r = load(RUN / "records" / (item["item_id"] + ".json"))
        if not r.get("complete") or r["split"] != "dev" or any(r[k] != item[k] for k in ("item_id", "trace_id", "task_id", "fault")):
            raise ValueError("Record identity/split/completion differs from registration")
        records.append(r)
    if len(records) != 100 or len({r["item_id"] for r in records}) != 100:
        raise ValueError("Expected all 100 unique registered occurrence records")
    source_hash = hashlib.sha256(b"".join((RUN / "records" / (r["item_id"] + ".json")).read_bytes() for r in records)).hexdigest()
    buckets = {name: [r for r in records if group_of(r) == name] for name in ("fast_exit", "full_gate", "partial_or_interrupted")}
    l1 = {"all_heals": latency_group(records, "all_heals")}
    l1.update({name: latency_group(rs, name) for name, rs in buckets.items()})
    l2 = {
        "ledger_usd": mean_median([r["ledger"]["cost_usd"] for r in records]),
        "provider_usd": mean_median([r["provider"]["cost_usd"] for r in records]),
        **{k: mean_median([r["provider"][k] for r in records]) for k in ("input_tokens", "cache_hit_input_tokens", "cache_miss_input_tokens", "output_tokens")},
    }
    l2["provider_to_ledger_ratio_of_totals"] = l2["provider_usd"]["total"] / l2["ledger_usd"]["total"]
    l2["cache_hit_rate_token_weighted"] = l2["cache_hit_input_tokens"]["total"] / l2["input_tokens"]["total"]
    l2["per_heal_provider_to_ledger_ratio"] = mean_median([
        r["provider"]["cost_usd"] / r["ledger"]["cost_usd"] if r["provider"]["cost_usd"] is not None and r["ledger"]["cost_usd"] else None for r in records])
    l2["per_heal_provider_to_ledger_ratio"].pop("total")  # summing ratios is not an overall cost ratio
    calls = [c for r in records for c in r["calls"]]
    if len({c["call_id"] for c in calls}) != len(calls):
        raise ValueError("Repeated API call IDs across occurrence records")
    with sqlite3.connect((RUN / "budget.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as conn:
        stored = [json.loads(r[0]) for r in conn.execute("SELECT record FROM calls")]
        budget = conn.execute("SELECT cap,spent,provider_cap,provider_spent,stopped FROM budget WHERE id=1").fetchone()
    main = [c for c in stored if c["heal_id"].startswith("heal-")]
    smoke = [c for c in stored if c["heal_id"].startswith("smoke-")]
    if {c["call_id"] for c in main} != {c["call_id"] for c in calls} or len(main) + len(smoke) != len(stored):
        raise ValueError("Unreconciled API attempts; refuse to drop them")
    reconciliation = dict(main_api_attempts=len(main), smoke_api_attempts=len(smoke),
        main_ledger_usd=sum(c["ledger_usd"] for c in main), smoke_ledger_usd=sum(c["ledger_usd"] for c in smoke),
        main_provider_usd=sum(c["provider_actual_usd"] for c in main),
        smoke_provider_usd=sum(c["provider_actual_usd"] for c in smoke),
        budget_ledger_usd=budget[1], budget_provider_usd=budget[3], ledger_cap_usd=budget[0],
        provider_cap_usd=budget[2], cap_hit=bool(budget[4]))
    if not np.isclose(l2["ledger_usd"]["total"], reconciliation["main_ledger_usd"], atol=1e-10) or not np.isclose(l2["provider_usd"]["total"], reconciliation["main_provider_usd"], atol=1e-10):
        raise ValueError("Per-heal cost does not reconcile to durable API ledger")
    start = min(datetime.fromisoformat(r["started_at"]) for r in records)
    hours = defaultdict(list)
    for r in records:
        hours[int((datetime.fromisoformat(r["started_at"]) - start).total_seconds() // 3600)].append(r)
    hourly = []
    for hour, rs in sorted(hours.items()):
        # Calls are bucketed by their own start time, independently of heal cohorts.
        hour_calls = [c for c in calls if int((datetime.fromisoformat(c["started_at"]) - start).total_seconds() // 3600) == hour]
        elapsed = [(datetime.fromisoformat(c["ended_at"]) - datetime.fromisoformat(c["started_at"])).total_seconds() for c in hour_calls if c.get("ended_at")]
        full = [r for r in rs if group_of(r) == "full_gate"]
        hourly.append(dict(run_hour=hour + 1, from_local=(start + timedelta(hours=hour)).isoformat(),
            to_local=(start + timedelta(hours=hour + 1)).isoformat(), n=len(rs),
            group_counts=dict(Counter(group_of(r) for r in rs)),
            all_total_s=percentiles([r["total_s"] for r in rs], "hour", False),
            full_gate_total_s=percentiles([r["total_s"] for r in full], "hour-full", False),
            critic_call_s=percentiles([r["stages_s"]["critic_call"] for r in rs], "hour-critic", False),
            api_attempts_in_hour=len(hour_calls), api_attempt_elapsed_s=percentiles(elapsed, "hour-api", False),
            cache_hit_rate_token_weighted=sum(c["provider_cost"]["cache_hit_input_tokens"] for c in hour_calls) / sum(c["provider_cost"]["input_tokens"] for c in hour_calls) if hour_calls else None))
    # Include any final hour with API calls but no newly-starting heal.
    call_hours = {int((datetime.fromisoformat(c["started_at"]) - start).total_seconds() // 3600) for c in calls}
    for hour in sorted(call_hours - set(hours)):
        cs = [c for c in calls if int((datetime.fromisoformat(c["started_at"]) - start).total_seconds() // 3600) == hour]
        elapsed = [(datetime.fromisoformat(c["ended_at"]) - datetime.fromisoformat(c["started_at"])).total_seconds() for c in cs if c.get("ended_at")]
        hourly.append(dict(run_hour=hour + 1, from_local=(start + timedelta(hours=hour)).isoformat(), to_local=(start + timedelta(hours=hour + 1)).isoformat(), n=0, group_counts={}, all_total_s=percentiles([], "", False), full_gate_total_s=percentiles([], "", False), critic_call_s=percentiles([], "", False), api_attempts_in_hour=len(cs), api_attempt_elapsed_s=percentiles(elapsed, "", False), cache_hit_rate_token_weighted=sum(c["provider_cost"]["cache_hit_input_tokens"] for c in cs)/sum(c["provider_cost"]["input_tokens"] for c in cs)))
    agent_rows, critic_retries, critic_requests_after_retry = [], 0, 0
    critic_attempt_distribution = Counter()
    for r in records:
        work = RUN / "work" / r["item_id"]
        for path in work.glob("*/agent_runs.jsonl"):
            agent_rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for path in work.glob("*/critic_calls.jsonl"):
            settled = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                c = json.loads(line)
                settled[c["call_id"]] = c
            attempts = [c["attempt"] for c in settled.values()]
            retry = max(attempts, default=0)
            critic_retries += retry
            critic_attempt_distribution[retry] += 1
            critic_requests_after_retry += sum(c["attempt"] > 0 for c in settled.values())
    errors = dict(terminal_heal_status=dict(Counter(r["status"] for r in records)),
        api_attempts=len(calls), api_error_total=sum(bool(c["error"]) for c in calls),
        api_error_counts=dict(Counter(c["error"] for c in calls if c["error"])),
        http_status_counts=dict(Counter(str(c["http_status"]) for c in calls)),
        unknown_or_unsettled_api_attempts=sum(c["status"] != "settled" for c in calls),
        missing_provider_usage=sum(c["provider_cost"] is None for c in calls),
        heal_timeout_count=sum(r["status"] == "timeout" for r in records),
        recorded_api_timeout_count=sum(r["timeout_count"] for r in records),
        api_transport_retries_after_failed_request=sum(bool(c["error"]) for c in calls),
        critic_validation_retry_rounds=critic_retries,
        heals_without_critic_api_calls=sum(not any(c["temperature"] == .2 for c in r["calls"]) for r in records),
        critic_heals_by_retry_round_count=dict(critic_attempt_distribution),
        critic_paid_requests_on_retry_rounds=critic_requests_after_retry,
        agent_run_records=len(agent_rows), agent_run_error_count=sum(r["status"] != "ok" for r in agent_rows),
        agent_run_retry_attempts=sum(max(r["attempts"] - 1, 0) for r in agent_rows),
        actor_invalid_json_responses=sum(r["invalid_json"] for r in agent_rows),
        orphan_attempt_directories=sum(len(list((RUN / "work" / r["item_id"]).glob("*/critic_calls.jsonl"))) > 1 for r in records))
    decisions = defaultdict(Counter)
    for r in records:
        decisions[r["failure_class"]][r["gate_decision"]] += 1
    return dict(experiment_id="phase5-L1-L2-dev", generated_at=datetime.now(timezone.utc).isoformat(),
        methodology=dict(split="DEV only", n=100, concurrency=2, source_registration="phase5-prereg",
            sample_sha256=manifest["id_list_sha256"], source_records_sha256=source_hash,
            bootstrap_replicates=BOOTSTRAPS, bootstrap_seed=SEED, bootstrap_method="occurrence-level nonparametric percentile CI; key-derived SHA256 RNG seeds; linear quantiles",
            bootstrap_limit="conditional on this run/sample; time correlation and repeated source tasks are not removed",
            grouping="full_gate: all three gate stages complete; fast_exit: rejected and all gate stages skipped; other cases retained as partial/interrupted",
            stage_share="sum of recorded stage seconds / sum of total seconds in the same group",
            costs="main 100 only; smoke reconciled separately; provider dollars use API usage and registered rates, not invoice",
            hourly="elapsed-hour bins anchored at first heal start; heals by start, API attempts independently by request start; partial hours retained",
            hourly_caution="task mix, cache state, concurrency and retries confound provider-load attribution"),
        run_window=dict(started_at=start.isoformat(), ended_at=max(datetime.fromisoformat(r["ended_at"]) for r in records).isoformat()),
        L1=l1, L2=l2, hourly=sorted(hourly, key=lambda x: x["run_hour"]), errors_and_retries=errors,
        gate_decisions=dict(label="Descriptive only; not a re-estimate of Phase 4 rates", by_detector_failure_class={k: dict(v) for k, v in sorted(decisions.items())}),
        spend_reconciliation=reconciliation)


def fmt(value):
    return "n/a" if value is None else f"{value:.6f}" if value < .01 else f"{value:.3f}"


def ci(value, bounds):
    return "n/a" if value is None else f"{fmt(value)} [{fmt(bounds[0])}, {fmt(bounds[1])}]"


def write_report(result):
    lines = ["# Phase 5 results", "", "## Part A: L1 latency and L2 cost", "",
        "DEV only; fixed concurrency 2. All 100 registered occurrences are retained. "
        "Smoke is excluded from per-heal endpoints and reconciled separately below.", "",
        f"Run: {result['run_window']['started_at']} to {result['run_window']['ended_at']}.", "",
        "Fast exit means rejected with all three gate stages recorded as skipped. Full gate means all three completed. "
        "No duration threshold is used; partial/interrupted cases have their own retained group.", "",
        "### L1: seconds, point estimate [bootstrap 95% CI]", "",
        "| Recorded-stage group | n | p50 seconds [95% CI] | p90 seconds [95% CI] |", "|---|---:|---:|---:|"]
    for name, group in result["L1"].items():
        q = group["total_s"]
        lines.append(f"| {name} | {q['n']} | {ci(q['p50'], q['ci95_p50'])} | {ci(q['p90'], q['ci95_p90'])} |")
    lines += ["", f"Percentile bootstrap: {BOOTSTRAPS:,} resamples, fixed seed {SEED}, occurrence-level sampling; "
        "linear quantiles. CIs are conditional on this run and do not eliminate time correlation or repeated-source-task dependence.", "",
        "### Per-stage latency and aggregate share of total time", "",
        "| Stage | Ran | Skipped | p50 seconds [95% CI] | p90 seconds [95% CI] | Share of all-heal total |", "|---|---:|---:|---:|---:|---:|"]
    for name, q in result["L1"]["all_heals"]["stages"].items():
        lines.append(f"| {name} | {q['n']} | {q['state_counts'].get('skipped', 0)} | {ci(q['p50'], q['ci95_p50'])} | {ci(q['p90'], q['ci95_p90'])} | {q['aggregate_share_of_total']:.4%} |")
    lines += ["", f"Unattributed loading/configuration/final bookkeeping: {result['L1']['all_heals']['unattributed_share']:.2%} "
        "of total. Stage quantiles exclude explicitly skipped stages, whose counts remain visible. "
        "The JSON also includes stage distributions/shares separately for fast exits and full-gate heals.", "",
        "### L2: main-run cost and tokens per heal", "",
        "| Metric | Mean | Median | Total |", "|---|---:|---:|---:|"]
    for key in ("ledger_usd", "provider_usd", "input_tokens", "cache_hit_input_tokens", "cache_miss_input_tokens", "output_tokens"):
        q = result["L2"][key]
        digits = 8 if key.endswith("usd") else 2
        lines.append(f"| {key} | {q['mean']:.{digits}f} | {q['median']:.{digits}f} | {q['total']:.{digits}f} |")
    l2 = result["L2"]
    lines += ["", f"Provider/ledger ratio of totals: **{l2['provider_to_ledger_ratio_of_totals']:.6f}**. "
        f"Token-weighted input cache-hit rate: **{l2['cache_hit_rate_token_weighted']:.2%}**. "
        "The cost gap includes both cache discounts and time-of-day pricing; it is not a cache-only effect. "
        "Provider dollars price API-reported usage at the registered schedule, not an invoice.", "",
        "### Latency by elapsed hour", "",
        "Heals are bucketed by start time; API attempts by their own request start. Final partial hours are retained. "
        "Full-gate-only and per-request views help expose fast-exit mix effects. These observational differences do not isolate provider load.", "",
        "| Run hour | Start (local offset) | Heals (fast/full) | All p50/p90 s | Full gate p50/p90 s | API p50/p90 s | API attempts |", "|---|---|---:|---:|---:|---:|---:|"]
    for h in result["hourly"]:
        a, f, api = h["all_total_s"], h["full_gate_total_s"], h["api_attempt_elapsed_s"]
        lines.append(f"| {h['run_hour']} | {h['from_local']} | {h['n']} ({h['group_counts'].get('fast_exit', 0)}/{h['group_counts'].get('full_gate', 0)}) | {fmt(a['p50'])}/{fmt(a['p90'])} | {fmt(f['p50'])}/{fmt(f['p90'])} | {fmt(api['p50'])}/{fmt(api['p90'])} | {h['api_attempts_in_hour']} |")
    complete_hours = [h for h in result["hourly"] if datetime.fromisoformat(h["to_local"]) <= datetime.fromisoformat(result["run_window"]["ended_at"])]
    first, last = complete_hours[0], complete_hours[-1]
    peak = max(complete_hours, key=lambda h: h["api_attempt_elapsed_s"]["p50"])
    lines += ["", f"API-attempt p50 was {first['api_attempt_elapsed_s']['p50']:.3f}s in hour {first['run_hour']}, "
        f"peaked at {peak['api_attempt_elapsed_s']['p50']:.3f}s in hour {peak['run_hour']}, "
        f"and was {last['api_attempt_elapsed_s']['p50']:.3f}s in hour {last['run_hour']}. "
        "The full-gate hourly medians are non-monotonic. This shows modest request-time drift, "
        "not evidence that provider load alone caused the variation."]
    lines += ["", "![Latency over the run](figures/heal_latency_by_hour.png)", "", "### Errors, timeouts and retries", ""]
    for key, value in result["errors_and_retries"].items():
        lines.append(f"- `{key}`: {json.dumps(value, sort_keys=True)}")
    lines += ["", "Transport retries count failed API attempts; critic validation retries are separate generated proposals. "
        "Actor invalid JSON responses are model protocol errors/corrective turns, not transport retries. "
        "Four NORMAL detector outcomes made no paid critic request; their recorded critic-stage timer covers the no-op branch. "
        "All paid attempts, including retries, reconcile to the durable ledger; no heal or attempt was silently dropped.", "",
        "### Gate decisions: descriptive only, not a re-estimate of Phase 4 rates", "",
        "| Detector failure class | Promoted | Rejected | Other |", "|---|---:|---:|---:|"]
    for name, counts in result["gate_decisions"]["by_detector_failure_class"].items():
        lines.append(f"| {name} | {counts.get('promoted', 0)} | {counts.get('rejected', 0)} | {sum(v for k,v in counts.items() if k not in {'promoted','rejected'})} |")
    s = result["spend_reconciliation"]
    lines += ["", "### Budget reconciliation", "",
        f"Main 100: ledger ${s['main_ledger_usd']:.8f}, provider ${s['main_provider_usd']:.9f}. "
        f"Smoke: ledger ${s['smoke_ledger_usd']:.8f}, provider ${s['smoke_provider_usd']:.9f}. "
        f"Shared totals: ledger **${s['budget_ledger_usd']:.8f}**, provider **${s['budget_provider_usd']:.9f}**. "
        f"Caps: ${s['ledger_cap_usd']:.2f}/${s['provider_cap_usd']:.2f}; cap hit: {s['cap_hit']}.", "",
        "Source: registered DEV occurrence JSON plus the read-only SQLite API ledger and local actor/critic retry ledgers. "
        "Only aggregate results are committed; raw records remain ignored under `data/phase5/runs/`.", ""]
    report_path = ROOT / "reports/phase5/results.md"
    previous = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    part_b = "\n## Part B:" + previous.split("\n## Part B:", 1)[1] if "\n## Part B:" in previous else ""
    report_path.write_text("\n".join(lines) + part_b, encoding="utf-8")


def plot_hourly(result):
    os.environ.setdefault("MPLCONFIGDIR", str(RUN / "mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hours = result["hourly"]
    x = [h["run_hour"] for h in hours]
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for key, label, color in (("all_total_s", "All heals", "#35608d"), ("full_gate_total_s", "Full gate", "#aa6235")):
        axes[0].plot(x, [h[key]["p50"] for h in hours], marker="o", label=label + " p50", color=color)
        axes[0].plot(x, [h[key]["p90"] for h in hours], linestyle="--", label=label + " p90", color=color)
    axes[0].set(title="Heal latency by start hour (concurrency 2)", ylabel="Time to terminal decision (s)")
    axes[0].legend(ncol=2)
    for q, style in (("p50", "-"), ("p90", "--")):
        axes[1].plot(x, [h["api_attempt_elapsed_s"][q] for h in hours], linestyle=style, marker="o", label="API attempt " + q, color="#35608d")
    axes[1].set(title="Actual API attempt elapsed time by request-start hour", xlabel="Elapsed hour from first heal start", ylabel="API attempt elapsed (s)", xticks=x)
    axes[1].legend()
    for ax in axes:
        ax.grid(axis="y", alpha=.2)
    fig.text(.01, .005, f"Source: 100 DEV heals, {result['run_window']['started_at']} to {result['run_window']['ended_at']}; linear quantiles, partial hours retained.", fontsize=7)
    fig.tight_layout(rect=(0, .03, 1, 1))
    target = ROOT / "reports/phase5/figures"
    target.mkdir(parents=True, exist_ok=True)
    fig.savefig(target / "heal_latency_by_hour.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    result = analyse()
    result["analysis_base_commit"] = subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result["analysis_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target = ROOT / "results/phase5"
    target.mkdir(parents=True, exist_ok=True)
    (target / "heal_latency_cost.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_report(result)
    plot_hourly(result)
    print(json.dumps(dict(groups={k:v["total_s"] for k,v in result["L1"].items()}, L2=result["L2"], errors=result["errors_and_retries"], spend=result["spend_reconciliation"]), indent=2))
