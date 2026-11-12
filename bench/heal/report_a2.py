"""Render reports/phase4/critic_arms_dev.md from the A2 result files (no runs, no calls).

    python -m bench.heal.report_a2
"""

from __future__ import annotations

import json
import os
from typing import Any

from bench.heal.harness import REST_CAP_USD, REST_LEDGER, STATE_DIR
from bench.heal.sets import REPO
from services.common.results import report_header

RES = os.path.join(REPO, "results")
REPORT = os.path.join(REPO, "reports", "phase4", "critic_arms_dev.md")
ARMS = (("generic", "heal_generic_a2_dev.json"), ("new", "heal_critic_new_dev.json"),
        ("v1_structured", "heal_critic_v1_structured_dev.json"))


def _load(name) -> dict[str, Any] | None:
    p = os.path.join(RES, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)["results"]


def _p(d) -> str:
    if not d or d["n"] == 0:
        return "–"
    lo, hi = d["ci95_clopper_pearson"]
    return f"{d['k']}/{d['n']} ({d['value']:.2f}; {lo:.2f}–{hi:.2f})"


def _k(d) -> str:
    return "–" if not d or d["n"] == 0 else f"{d['k']}/{d['n']}"


def _fp(b, tag=None, fault=None) -> tuple[int, int]:
    """(gate false promotions, confirmations scored) within a slice of per-failure rows."""
    rows = [r for r in b["per_failure_rows"] if (tag is None or r["tag"] == tag)
            and (fault is None or r["fault"] == fault)]
    ids = {r["failure_id"] for r in rows}
    conf = [c for c in b["confirmation"] if c["failure_id"] in ids]
    return sum(c.get("false_promotion", False) for c in conf), sum(c["status"] == "scored"
                                                                   for c in conf)


def arm_table(docs, outcome="a1") -> list[str]:
    head = ["| Arm | Slice | Unit | n | H1 repair | H2 generalize | H3 regress | Gate promoted | "
            "Gate false promotions (s3–5) | Old-rule promoted | Old-rule false promotions | "
            "Harmful own-pass |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    out = list(head)
    for arm, d in docs.items():
        b = d["by_outcome"][outcome]
        pf, pd = b["summary_per_failure"], b["summary_per_distinct_patch"]
        slices = [("all", None, None)]
        slices += [(f"tag={t}", t, None) for t in pf["by_tag"]]
        slices += [(f"fault={f}", None, f) for f in pf["by_fault"]]
        for name, tag, fault in slices:
            s = pf["all"] if name == "all" else (pf["by_tag"][tag] if tag else pf["by_fault"][fault])
            sd = pd["all"] if name == "all" else (pd["by_tag"].get(tag) if tag
                                                   else pd["by_fault"].get(fault))
            fp, nconf = _fp(b, tag, fault)
            out.append(f"| {arm} | {name} | per failure | {s['n_patches']} | {_p(s['H1_repair'])} | "
                       f"{_p(s['H2_generalize'])} | {_p(s['H3_regress'])} | "
                       f"{_p(s['gate_promoted'])} | {fp} ({nconf} confirmed) | "
                       f"{_k(s['old_rule_promoted'])} | {s['old_rule_false_promotions']} | "
                       f"{s['harmful_own_pass']} |")
            if sd:
                out.append(f"| {arm} | {name} | per distinct patch | {sd['n_distinct']} "
                           f"(covers {sd['failures_covered']}, max {sd['max_failures_per_patch']}"
                           f"/patch) | {_k(sd['H1_repair'])} | {_k(sd['H2_generalize'])} | "
                           f"{_k(sd['H3_regress'])} | {_k(sd['gate_promoted'])} | "
                           f"{sd['gate_false_promotions']} | – | {sd['old_rule_false_promotions']} | "
                           f"{sd['harmful_own_pass']} |")
    return out


def h4_table(docs, outcome="a1") -> list[str]:
    out = ["| Arm | Tag | Patches | Old rule promoted | Old-rule false promotions | Gate promoted | "
           "Gate false promotions (s3–5) |", "|---|---|---|---|---|---|---|"]
    for arm, d in docs.items():
        b = d["by_outcome"][outcome]
        h = b["H4"]
        out.append(f"| {arm} | all | {h['n_patches']} | {h['old_rule_promoted']} | "
                   f"{h['old_rule_false_promotions']} | {h['gate_promoted']} | "
                   f"{h['gate_false_promotions']} |")
        for tag, x in b["H4_by_tag"].items():
            if x["n_patches"]:
                out.append(f"| {arm} | {tag} | {x['n_patches']} | {x['old_rule_promoted']} | "
                           f"{x['old_rule_false_promotions']} | {x['gate_promoted']} | "
                           f"{x['gate_false_promotions']} |")
    return out


def coverage(docs) -> list[str]:
    out = ["| Arm | Eligible failures (A1) | Got a patch | No patch (reasons) | "
           "H1 per failure (no patch = not repaired) | No-harm bleed excluded (H3 breaks) |",
           "|---|---|---|---|---|---|"]
    for arm, d in docs.items():
        b = d["by_outcome"]["a1"]
        r = b["per_failure_rate"]
        reasons = ", ".join(f"{k}: {v}" for k, v in r.get("no_patch_reasons", {}).items()) or "–"
        excl = b["no_observable_harm_excluded"]
        out.append(f"| {arm} | {r['eligible_failures']} | {r['eligible_failures'] - r['no_patch']} "
                   f"| {r['no_patch']} ({reasons}) | {_p(r['H1_per_failure'])} | {len(excl)} "
                   f"({sum(bool(e['regression_breaks']) for e in excl)} with breaks) |")
    return out


def promotion_table(docs) -> list[str]:
    """D72 item 2: gate promotions (seeds 0-2) per class, per failure and per distinct
    patch, split by injection tag."""
    out = ["| Arm | Class | Tag | Patches | Promoted (per failure) | Distinct patches | "
           "Promoted (per distinct) | Confirmed on s3–5 | False promotions |",
           "|---|---|---|---|---|---|---|---|---|"]
    for arm, d in docs.items():
        b = d["by_outcome"]["a1"]
        rows, dist = b["per_failure_rows"], b["summary_per_distinct_patch"]["patches"]
        conf = {c["failure_id"]: c for c in b["confirmation"]}
        keys = sorted({(r["fault"], r["tag"]) for r in rows})
        for fault, tag in keys:
            rs = [r for r in rows if r["fault"] == fault and r["tag"] == tag]
            ds = [x for x in dist if x["fault"] == fault and x["tag"] == tag]
            prom = [r for r in rs if r["gate"]["promoted"]]
            cs = [conf[r["failure_id"]] for r in prom if r["failure_id"] in conf]
            out.append(f"| {arm} | {fault} | {tag} | {len(rs)} | {len(prom)} | {len(ds)} | "
                       f"{sum(x['promoted_any'] for x in ds)} | "
                       f"{sum(c['status'] == 'scored' and not c.get('false_promotion') for c in cs)}"
                       f"/{len(prom)} hold | {sum(c.get('false_promotion', False) for c in cs)} |")
        tot = {t: sum(r["gate"]["promoted"] for r in rows if r["tag"] == t)
               for t in ("other_fix", "reverts_injection")}
        out.append(f"| {arm} | **all** | other_fix {tot['other_fix']}, reverts_injection "
                   f"{tot['reverts_injection']} | {len(rows)} | {sum(tot.values())} | "
                   f"{len(dist)} | {sum(x['promoted_any'] for x in dist)} | | "
                   f"{b['H4']['gate_false_promotions']} |")
    return out


def noise_lines(docs) -> list[str]:
    out = ["| Arm | Cells (patch × task × env), seeds 0–2 | Seeds disagree | of which faulted | "
           "of which regression | Promoted-patch task cells re-run on s3–5 | Task outcome "
           "flips s0–2 → s3–5 |", "|---|---|---|---|---|---|---|"]
    for arm, d in docs.items():
        n = d.get("seed_noise")
        if not n:
            continue
        w = n["within_s0_2"]
        out.append(f"| {arm} | {n['within_s0_2_all']['n']} | {_p(n['within_s0_2_all'])} | "
                   f"{_p(w.get('faulted'))} | {_p(w.get('regression'))} | "
                   f"{n['confirm_task_flips_all']['n']} | {_p(n['confirm_task_flips_all'])} |")
    return out


def noise_note(docs) -> str:
    ns = [d["seed_noise"] for d in docs.values() if d.get("seed_noise")]
    mixed = sum(n["within_s0_2_all"]["k"] for n in ns)
    cells = sum(n["within_s0_2_all"]["n"] for n in ns)
    flips = sum(n["confirm_task_flips_all"]["k"] for n in ns)
    fc = sum(n["confirm_task_flips_all"]["n"] for n in ns)
    rate = mixed / cells if cells else 0.0

    def part(kind):
        k = sum(n["within_s0_2"].get(kind, {}).get("k", 0) for n in ns)
        m = sum(n["within_s0_2"].get(kind, {}).get("n", 0) for n in ns)
        return k, m
    fk, fn = part("faulted")
    rk, rn = part("regression")
    head = (f"Over the arms in this report (generic HALLUCINATION, `new`, `v1_structured`), the seeds disagree in {mixed} of {cells} cells ({rate:.1%}): "
            f"{fk} of {fn} faulted cells ({fk / fn if fn else 0:.1%}) and {rk} of {rn} "
            f"regression cells ({rk / rn if rn else 0:.1%}). {flips} of {fc} task outcomes "
            "on promoted patches flip between seeds 0–2 and 3–5. The earlier no-patch runs "
            "had 0 of 111.")
    flip_rate = flips / fc if fc else 0.0
    if flip_rate < 0.05:
        return head + (" Patched prompts add some within-seed noise, mostly on faulted tasks. "
                       "But the 2-of-3 task outcome almost never changes on fresh seeds. So "
                       "the confirmation mostly tests determinism at temperature 0, not "
                       "robustness, and few gate false promotions are expected by "
                       "construction. Descriptive only; the selection rule is unchanged.")
    return head + (" Task outcomes flip often enough that the fresh-seed confirmation is a "
                   "real check, not only a determinism test.")


def test_cost_lines(sel) -> list[str]:
    t = sel.get("test_cost_estimate")
    if not t:
        return ["Not estimated (no arm selected)."]
    a = t["assumptions"]
    dev = "; ".join(f"{k}: {v['runs']} runs, ${v['usd']:.3f}" for k, v in t["dev_measured"].items())
    return [f"Arm `{t['arm']}`. Built from dev measurements only. Nothing was run or read on "
            "the test split.", "",
            f"- Dev, measured: {dev}.",
            f"- Assumptions: {a['test_failures']} test failures (12 per class, the same rule); "
            f"{a['test_regression_tasks']} regression tasks (all 20 test QA tasks, from the "
            f"datasheet's 40 QA tasks minus 20 dev, plus 3 per other family); scale "
            f"{a['scale_vs_dev']}× dev; the same promotion rate as dev ({a['promotion_rate_as_dev']}); "
            f"critic ${a['critic_usd_per_proposal']}/proposal (Phase 3 round 3).",
            f"- **Estimate: ${t['est_total_usd']:.2f}** (critic proposals "
            f"${t['est_critic_proposals_usd']:.3f} + agent runs ${t['est_agent_runs_usd']:.3f}), "
            f"plus about {t['est_qwen_hours']} h of local Qwen.", "",
            "This is a planning estimate, not a cap. The test scoring needs its own cap and "
            "go-ahead."]


def spend_lines() -> list[str]:
    def total(name):
        p = os.path.join(STATE_DIR, name)
        if not os.path.exists(p):
            return 0.0, 0
        rows = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
        return sum(r["cost_usd"] for r in rows), len(rows)
    rest, nr = total(REST_LEDGER)
    h6, nh = total("cost_ledger_h6.jsonl")
    return [f"- Rest-of-phase ledger (critic arms, confirmations, generic confirmations, Gemini "
            f"probe): ${rest:.4f} over {nr} paid calls.",
            f"- H6 ledger: ${h6:.4f} over {nh} paid calls. 600 judgments in total; the rest were "
            "byte-identical judge inputs, served from the response cache.",
            f"- Total ${rest + h6:.4f} of the ${REST_CAP_USD:.2f} cap (D72). Preparation ledger "
            "closed at $0.247 (D67)."]


def main() -> int:
    docs = {a: d for a, f in ARMS if (d := _load(f)) is not None}
    noise = (_load("heal_seed_noise_dev.json") or {}).get("arms", {})
    for a, d in docs.items():   # D74: seed noise has its own result file
        if a in noise:
            d["seed_noise"] = noise[a]
    sel = _load("heal_selection_dev.json") or {}
    h6 = _load("heal_h6_dev.json")
    lines = ["# Phase 4 critic arms on dev (amendment A2)", "",
             *report_header(provider="deepseek+ollama", model="deepseek-flash+qwen2.5:7b-instruct",
                            mock=False, generator="python -m bench.heal.report_a2"),
             "- **Protocol:** [`preregistration.md`](preregistration.md) + "
             "[`amendment_a1.md`](amendment_a1.md) + [`amendment_a2.md`](amendment_a2.md). "
             "Primary outcome: A1 safe-failure repair. Gate check 3 / H3: checker on the 29-task "
             "A2 regression set.",
             "- **Result files:** `results/heal_generic_a2_dev.json`, "
             "`results/heal_critic_new_dev.json`, `results/heal_critic_v1_structured_dev.json`, "
             "`results/heal_selection_dev.json`, `results/heal_h6_dev.json`, "
             "`results/heal_seed_noise_dev.json`. Dev only; the test "
             "split was not touched.", "",
             "Counts with 95% Clopper-Pearson intervals. A task passes at ≥ 2 of 3 seeds. A distinct "
             "patch (fault, diff hash) meets a good outcome only if it meets it on every failure it "
             "was applied to, and a bad one if it happens on any. Generated file; do not edit.", "",
             "## Arms (A1 outcome, A2 regression set)", "",
             "The generic row covers only the 12 HALLUCINATION patches re-scored under A2 "
             "(amendment A2 item 3). Every critic-arm HALLUCINATION patch is a whole-prompt "
             "replacement and is tagged `reverts_injection`; the headline is `other_fix`.", "",
             *arm_table(docs), "",
             "## Gate promotions by class and tag", "",
             "Promoted on seeds 0–2. `reverts_injection` = the patch removes the injected "
             "guessing prompt (HALLUCINATION only), kept out of the headline.", "",
             *promotion_table(docs), "",
             "## Seed noise (descriptive only)", "",
             "How often seeds disagree. This is not used by the gate or the selection rule "
             "(D72).", "", *noise_lines(docs), "", "NOISE_NOTE", "",
             "## Coverage", "", *coverage(docs), "",
             "## H4: old rule (\"same input improved\") vs the gate", "",
             "Old-rule false promotion: seed 0 of the own task passes but the patch fails check 2 "
             "or check 3. Gate false promotion: gate-promoted on seeds 0–2, but check 2 or 3 fails "
             "on fresh seeds 3–5.", "", *h4_table(docs), ""]
    lines += ["## Selection (pre-registered 1f / A1 §3)", ""]
    if sel.get("table"):
        lines += ["| Arm | Gate false promotions (s3–5) | H2 per failure |", "|---|---|---|"]
        lines += [f"| {a} | {t['gate_false_promotions']} | {t['H2_k']}/{t['H2_n']} "
                  f"({t['H2']:.2f}) |" for a, t in sel["table"].items()]
        lines += ["", f"**Selected: `{sel['selected']}`.**"
                  + (f" Unresolved tie: {sel['unresolved_tie']}." if sel.get("unresolved_tie")
                     else ""), ""]
        tag_h2 = []
        for a in sel["table"]:
            s = docs[a]["by_outcome"]["a1"]["summary_per_failure"]["by_tag"]
            tag_h2.append(f"`{a}` other_fix {_k(s.get('other_fix', {}).get('H2_generalize'))}, "
                          f"reverts_injection {_k(s.get('reverts_injection', {}).get('H2_generalize'))}")
        lines += ["Tie-break H2 by tag: " + "; ".join(tag_h2) + ". The rule uses every patch, "
                  "as pre-registered. Read the margin with that in mind: on `other_fix` alone, "
                  "the headline tag, the order of the two arms can differ.", ""]
        if sel.get("per_distinct"):
            lines += [f"Per distinct patch the same rule picks `{sel['per_distinct']['selected']}` "
                      f"({sel['per_distinct']['table']}).", ""]
    else:
        lines += [f"Not selected: {sel.get('reason', 'no result')}", ""]
    lines += ["## H6: judge bias", ""]
    if h6:
        lines += ["| Judge | Judged | Unparseable | κ (95% bootstrap) | Agreement | Judge pass / ref "
                  "fail | Judge fail / ref pass | κ, DeepSeek agent runs | κ, Qwen agent runs |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for m, j in h6["judges"].items():
            a, bp = j["all"], j["by_agent_provider"]
            ci = a["ci95_bootstrap"]
            lines.append(f"| {m} | {j['judged']} | {j['unparseable']} | {a['kappa']} "
                         f"({ci[0]}–{ci[1]}) | {a['agreement']} | "
                         f"{a['table']['judge_pass_ref_fail']} | {a['table']['judge_fail_ref_pass']} | "
                         f"{bp.get('deepseek', {}).get('kappa')} | {bp.get('ollama', {}).get('kappa')} |"
                         if ci else f"| {m} | {j['judged']} | {j['unparseable']} | – | – | – | – | – | – |")
        j0 = next(iter(h6["judges"].values()))["all"]["table"]
        ref_fail = j0["judge_pass_ref_fail"] + j0["judge_fail_ref_fail"]
        lines += ["", f"Only {ref_fail} of {h6['sample_n']} sampled runs fail by the deterministic "
                  "reference, so kappa is unstable here: raw agreement is high, and the two "
                  "judges' intervals overlap widely. Read the kappa difference as indicative, "
                  "not established."]
        lines += ["", f"Sample: {h6['sample_n']} critic-arm runs, seed `{h6['sample_seed']}`. "
                  "Reference: A1 safe-repair rule (faulted runs) or checker (regression runs).", ""]
    else:
        lines += ["Not run.", ""]
    lines += ["## Test scoring: cost estimate (nothing run)", "", *test_cost_lines(sel), ""]
    lines += ["## Spend", "", *spend_lines(), ""]
    lines = [noise_note(docs) if x == "NOISE_NOTE" else x for x in lines]
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("wrote", os.path.relpath(REPORT, REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
