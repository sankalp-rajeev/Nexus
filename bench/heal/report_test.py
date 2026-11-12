"""Render reports/phase4/test_scoring.md from the A3 test result files.

    python -m bench.heal.report_test

Reads only the scored result files (test: results/heal_{nopatch,generic,
critic_v1_structured}_test.json; dev, for the side-by-side: the committed dev result
files) and the A3 test sets. Rendering only: no run, no scoring, no rule.
CONTEXT_BLEED has 3 scored test failures, so its cells are counts only, never rates.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from bench.heal.report_a2 import _k, _p, h4_table, promotion_table
from bench.heal.score import PRIMARY
from bench.heal.sets import REPO, TEST_SETS_PATH, load_sets
from services.common.results import report_header

RES = os.path.join(REPO, "results")
REPORT = os.path.join(REPO, "reports", "phase4", "test_scoring.md")
ARM = "v1_structured"
FILES = (("no patch", "heal_nopatch_test.json"), ("generic", "heal_generic_test.json"),
         (ARM, f"heal_critic_{ARM}_test.json"))
CLASSES = ("HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")
TAGS = ("other_fix", "reverts_injection")
SMALL = "CONTEXT_BLEED"  # n = 3 scored on test: counts only


def _load(name) -> dict[str, Any]:
    with open(os.path.join(RES, name), encoding="utf-8") as fh:
        return json.load(fh)["results"]


def _rows(d, outcome=PRIMARY):
    return d["by_outcome"][outcome]["per_failure_rows"]


def _cp(k, n) -> dict[str, Any]:
    from services.healer.gate import proportion
    return proportion(k, n)


def _fmt(k, n, fault=None) -> str:
    """k/n with rate and 95% Clopper-Pearson interval; counts only for CONTEXT_BLEED."""
    if n == 0:
        return "–"
    return f"{k}/{n}" if fault == SMALL else _p(_cp(k, n))


def _mean(xs) -> str:
    xs = [x for x in xs if x is not None]
    return f"{sum(xs) / len(xs):.2f}" if xs else "–"


# --- 1. H1-H3 per class and tag, net of no patch ------------------------------------

def net_table(docs) -> list[str]:
    nop = {r["failure_id"]: r for r in _rows(docs["no patch"])}
    out = ["| Arm | Class | Tag | Patches | H1 repair (s0–2) | No patch, same failures | "
           "H1 net of no patch | H2 generalize (held-out > no patch) | Mean held-out rate, "
           "patch vs no patch | H3 regress (≥1 break) | No patch H3, same failures |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in ("generic", ARM):
        rows = _rows(docs[arm])
        for tag in TAGS:
            for c in (*CLASSES, None):
                rs = [r for r in rows if r["tag"] == tag and (c is None or r["fault"] == c)]
                if not rs:
                    continue
                n = len(rs)
                fault = c
                k1 = sum(r["gate"]["check1_own_task"] for r in rs)
                k0 = sum(nop[r["failure_id"]]["gate"]["check1_own_task"] for r in rs)
                k2 = sum(r["gate"]["check2_heldout"] for r in rs)
                k3 = sum(bool(r["gate"]["regression_breaks"]) for r in rs)
                k30 = sum(bool(nop[r["failure_id"]]["gate"]["regression_breaks"]) for r in rs)
                net = f"{k1 - k0:+d}" if fault == SMALL else f"{k1 - k0:+d} ({(k1 - k0) / n:+.2f})"
                held = (f"{_mean([r['gate']['heldout_rate_patch'] for r in rs])} vs "
                        f"{_mean([r['gate']['heldout_rate_nopatch'] for r in rs])}")
                if fault == SMALL:
                    held = (f"{sum(sum(r['heldout_patch'].values()) for r in rs)} vs "
                            f"{sum(sum(r['heldout_nopatch'].values()) for r in rs)} held-out "
                            f"tasks safe (of {sum(r['gate']['heldout_n'] for r in rs)})")
                name = f"**{c}**" if c else "**all**"
                out.append(f"| {arm} | {name if c is None else c} | {tag} | {n} | "
                           f"{_fmt(k1, n, fault)} | {_k(_cp(k0, n))} | {net} | "
                           f"{_fmt(k2, n, fault)} | {held} | {_fmt(k3, n, fault)} | "
                           f"{_k(_cp(k30, n))} |")
    return out


# --- 3. critic vs generic per class --------------------------------------------------

def vs_generic(docs, sets) -> list[str]:
    from bench.heal.score import eligible
    elig = [f for f in sets["failures"] if eligible(f, PRIMARY)]
    out = ["| Class | Eligible failures | No patch: own task safe | Generic: patches / repaired "
           "/ promoted / H3 breaks | v1_structured: patches / repaired / promoted / H3 breaks | "
           "v1_structured promoted, other_fix only | Promoted per eligible failure: generic vs "
           "v1_structured |", "|---|---|---|---|---|---|---|"]
    for c in (*CLASSES, None):
        ids = {f["failure_id"] for f in elig if c is None or f["fault"] == c}
        cell, prom = [], {}
        for arm in ("no patch", "generic", ARM):
            rs = [r for r in _rows(docs[arm]) if r["failure_id"] in ids]
            rep = sum(r["gate"]["check1_own_task"] for r in rs)
            if arm == "no patch":
                cell.append(f"{rep}/{len(ids)}")
                continue
            prom[arm] = sum(r["gate"]["promoted"] for r in rs)
            h3 = sum(bool(r["gate"]["regression_breaks"]) for r in rs)
            cell.append(f"{len(rs)} / {rep} / {prom[arm]} / {h3}")
        of = sum(r["gate"]["promoted"] for r in _rows(docs[ARM])
                 if r["failure_id"] in ids and r["tag"] == "other_fix")
        n = len(ids)
        both = (f"{prom['generic']}/{n} vs {prom[ARM]}/{n}" if c == SMALL else
                f"{_p(_cp(prom['generic'], n))} vs {_p(_cp(prom[ARM], n))}")
        out.append(f"| {c or '**all**'} | {n} | {cell[0]} | {cell[1]} | {cell[2]} | {of} | {both} |")
    return out


# --- 4. PLAN_DRIFT -------------------------------------------------------------------

def plan_drift(docs, sets) -> list[str]:
    pd_ids = [f["failure_id"] for f in sets["failures"] if f["fault"] == "PLAN_DRIFT"]
    n = len(pd_ids)
    nop = [r for r in _rows(docs["no patch"]) if r["fault"] == "PLAN_DRIFT"]
    lines = [f"There are {n} PLAN_DRIFT test failures, all Qwen (ollama), all scored. With no "
             f"patch, {sum(r['gate']['check1_own_task'] for r in nop)} of {n} are already safe "
             f"on their own task at ≥ 2 of 3 seeds.", ""]
    for arm in ("generic", ARM):
        rs = [r for r in _rows(docs[arm]) if r["fault"] == "PLAN_DRIFT"]
        if not rs:
            lines.append(f"- **{arm}:** no PLAN_DRIFT patch.")
            continue
        g = [r["gate"] for r in rs]
        tags = Counter(r["tag"] for r in rs)
        k1, k2 = sum(x["check1_own_task"] for x in g), sum(x["check2_heldout"] for x in g)
        k3, kp = sum(bool(x["regression_breaks"]) for x in g), sum(x["promoted"] for x in g)
        own = sum(sum(r["own_runs"]) for r in rs)
        lines.append(
            f"- **{arm}:** {len(rs)} patches ({tags['other_fix']} other_fix, "
            f"{tags['reverts_injection']} reverts_injection). Own task repaired {k1}/{len(rs)} "
            f"({own}/{3 * len(rs)} safe runs). Held-out better than no patch {k2}/{len(rs)} "
            f"(mean held-out rate {_mean([x['heldout_rate_patch'] for x in g])} vs no patch "
            f"{_mean([x['heldout_rate_nopatch'] for x in g])}). Regression breaks on "
            f"{k3}/{len(rs)}. **Gate promoted {kp}/{len(rs)}.**")
    crit = [r for r in _rows(docs[ARM]) if r["fault"] == "PLAN_DRIFT"]
    gen = [r for r in _rows(docs["generic"]) if r["fault"] == "PLAN_DRIFT"]
    kc = sum(r["gate"]["promoted"] for r in crit)
    kg = sum(r["gate"]["promoted"] for r in gen)
    verdict = ("The critic did not heal PLAN_DRIFT on test" if kc == 0 else
               f"The critic got {kc} of {n} PLAN_DRIFT failures through the gate")
    lines += ["", f"**Plainly:** {verdict}; generic got {kg} of {n}. "
              "See the per-class table above for the intervals."]
    return lines


# --- 5. usable patches ----------------------------------------------------------------

def usable(docs, sets) -> list[str]:
    props = docs[ARM]["proposals"]
    n = len(props)
    ok = sum(v["status"] == "patch" for v in props.values())
    by = Counter((fid.split("|")[0], v["reason"]) for fid, v in props.items()
                 if v["status"] != "patch")
    out = [f"**{ok}/{n} test failures got a usable `v1_structured` patch.** The other "
           f"{n - ok}, by class and reason (A1: a fallback, an invalid proposal or a failed "
           "Phase 3 dry run gives no patch; no failure was re-asked):", "",
           "| Class | Reason | Failures |", "|---|---|---|"]
    for (c, why), k in sorted(by.items()):
        out.append(f"| {c} | {why} | {k} |")
    excl = docs[ARM]["by_outcome"][PRIMARY]["no_observable_harm_excluded"]
    elig = docs[ARM]["by_outcome"][PRIMARY]["per_failure_rate"]
    out += ["", f"\"No proposal generated\" is the failure whose detector prediction was NORMAL, "
            "so it had no evidence (59/60 had evidence; A3 §2). Of the 50 patches, "
            f"{len(excl)} are on no-observable-harm CONTEXT_BLEED failures and are left out of "
            f"H1/H2/gate (their H3 breaks: "
            f"{', '.join(str(len(e['regression_breaks'])) for e in excl)}). That leaves "
            f"{elig['eligible_failures'] - elig['no_patch']} scored patches on "
            f"{elig['eligible_failures']} eligible failures."]
    return out


# --- 6. CONTEXT_BLEED, counts only -----------------------------------------------------

def context_bleed(docs, sets) -> list[str]:
    cb = [f for f in sets["failures"] if f["fault"] == SMALL]
    out = [f"{len(cb)} CONTEXT_BLEED test failures; 9 are excluded for no observable harm, so "
           "**n = 3** are scored. Counts only; no rate is reported.", ""]
    for arm in ("no patch", "generic", ARM):
        rs = [r for r in _rows(docs[arm]) if r["fault"] == SMALL]
        if not rs:
            out.append(f"- **{arm}:** no patch (template inapplicable, D58).")
            continue
        g = [r["gate"] for r in rs]
        if arm == "no patch":
            out.append(f"- **{arm}:** own task safe on {sum(x['check1_own_task'] for x in g)} "
                       f"of {len(rs)}.")
            continue
        out.append(f"- **{arm}:** {len(rs)} scored patches. Repaired "
                   f"{sum(x['check1_own_task'] for x in g)}, held-out better "
                   f"{sum(x['check2_heldout'] for x in g)}, with regression breaks "
                   f"{sum(bool(x['regression_breaks']) for x in g)}, gate promoted "
                   f"{sum(x['promoted'] for x in g)}.")
    return out


# --- 7. dev vs test ---------------------------------------------------------------------

def _dev_rows() -> list[tuple[str, str, dict, dict, dict]]:
    """(arm, label, all-summary, H4, net_of_H5) for the committed dev results."""
    crit = _load(f"heal_critic_{ARM}_dev.json")["by_outcome"][PRIMARY]
    gen_a2 = _load("heal_generic_a2_dev.json")["by_outcome"][PRIMARY]
    gen_a1 = _load("heal_generic_dev.json")
    g1 = {"all": gen_a1["summary"][PRIMARY]["all"], "H4": dict(gen_a1["H4"][PRIMARY]),
          "net": gen_a1["net_of_H5"][PRIMARY]}
    g1["H4"]["gate_false_promotions"] = g1["H4"].pop("gate_false_promotions_on_confirmation")
    return [
        (ARM, "dev (A2 regression set)", crit["summary_per_failure"]["all"], crit["H4"],
         crit["net_of_H5"], crit["per_failure_rate"]),
        ("generic", "dev, HALLUCINATION only (A2 set)", gen_a2["summary_per_failure"]["all"],
         gen_a2["H4"], gen_a2["net_of_H5"], gen_a2["per_failure_rate"]),
        ("generic", "dev, all 3 classes (A1 12-task set)", g1["all"], g1["H4"], g1["net"],
         gen_a1["per_failure_rate"][PRIMARY]),
    ]


def dev_vs_test(docs) -> list[str]:
    out = ["| Arm | Split | Patches scored | Patch per eligible failure | H1 repair | H1 net of "
           "no patch | H2 generalize | H3 regress | Gate promoted | Gate false promotions "
           "(s3–5) | Old rule promoted | Old-rule false promotions |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def line(arm, label, s, h, net, rate):
        miss = rate.get('no_patch', rate.get('no_applicable_patch', 0))
        cov = f"{rate['eligible_failures'] - miss}/{rate['eligible_failures']}"
        return (f"| {arm} | {label} | {s['n_patches']} | {cov} | {_p(s['H1_repair'])} | "
                f"{net['H1_net']:+.2f} | {_p(s['H2_generalize'])} | {_p(s['H3_regress'])} | "
                f"{_p(s['gate_promoted'])} | {h['gate_false_promotions']} | "
                f"{h['old_rule_promoted']} | {h['old_rule_false_promotions']} |")

    dev = {(a, lab): (s, h, n, r) for a, lab, s, h, n, r in _dev_rows()}
    for arm in (ARM, "generic"):
        b = docs[arm]["by_outcome"][PRIMARY]
        for (a, lab), v in dev.items():
            if a == arm:
                out.append(line(a, lab, *v))
        out.append(line(arm, "**test** (A2 set)", b["summary_per_failure"]["all"], b["H4"],
                        b["net_of_H5"], b["per_failure_rate"]))
        if arm == "generic":
            h = b["summary_per_failure"]["by_fault"].get("HALLUCINATION")
            if h:
                out.append(f"| generic | **test**, HALLUCINATION only | {h['n_patches']} | – | "
                           f"{_p(h['H1_repair'])} | – | {_p(h['H2_generalize'])} | "
                           f"{_p(h['H3_regress'])} | {_p(h['gate_promoted'])} | – | "
                           f"{_k(h['old_rule_promoted'])} | {h['old_rule_false_promotions']} |")
    return out


def dev_vs_test_class(docs) -> list[str]:
    crit = _load(f"heal_critic_{ARM}_dev.json")["by_outcome"][PRIMARY]["summary_per_failure"]
    test = docs[ARM]["by_outcome"][PRIMARY]["summary_per_failure"]
    out = [f"`{ARM}`, gate promoted per class (per scored patch):", "",
           "| Class | Dev | Test |", "|---|---|---|"]
    for c in CLASSES:
        d, t = crit["by_fault"].get(c), test["by_fault"].get(c)
        fmt = _k if c == SMALL else _p
        out.append(f"| {c} | {fmt(d['gate_promoted']) if d else '–'} | "
                   f"{fmt(t['gate_promoted']) if t else '–'} |")
    for tag in TAGS:
        d, t = crit["by_tag"].get(tag), test["by_tag"].get(tag)
        out.append(f"| tag={tag} | {_p(d['gate_promoted']) if d else '–'} | "
                   f"{_p(t['gate_promoted']) if t else '–'} |")
    return out


# --- 8. seed noise ----------------------------------------------------------------------

def seed_noise(docs) -> list[str]:
    out = ["Descriptive only; no test or threshold uses these numbers.", "",
           "| Split | Arm | Cells, s0–2 (patch × task × env) | Seeds disagree within s0–2 | "
           "Promoted-patch task cells re-run on s3–5 | Task outcome flips s0–2 → s3–5 |",
           "|---|---|---|---|---|---|"]
    dev = _load("heal_seed_noise_dev.json")
    for arm, n in dev["arms"].items():
        out.append(f"| dev | {arm} | {n['within_s0_2_all']['n']} | {_p(n['within_s0_2_all'])} | "
                   f"{n['confirm_task_flips_all']['n']} | {_p(n['confirm_task_flips_all'])} |")
    a = dev["all_arms"]
    out.append(f"| dev | **all** | {a['within_s0_2']['n']} | {_p(a['within_s0_2'])} | "
               f"{a['confirm_task_flips']['n']} | {_p(a['confirm_task_flips'])} |")
    for arm in ("generic", ARM):
        n = docs[arm].get("seed_noise")
        if n:
            out.append(f"| test | {arm} | {n['within_s0_2_all']['n']} | "
                       f"{_p(n['within_s0_2_all'])} | {n['confirm_task_flips_all']['n']} | "
                       f"{_p(n['confirm_task_flips_all'])} |")
    return out


# --- 9. spend ---------------------------------------------------------------------------

def _spend() -> dict[str, float]:
    """Critic calls (test critic log) and agent runs (per-run cost_usd in the test store)."""
    from bench.heal.harness import RunStore
    from bench.heal.test_phase import TEST_RUNS_PATH, critic_spent
    store = RunStore(TEST_RUNS_PATH).by_id.values()
    runs = sum(r["cost_usd"] for r in store)
    c = critic_spent()
    return {"critic_usd": c, "runs_usd": runs, "total_usd": c + runs, "n_runs": len(store)}


def main() -> int:
    docs = {a: _load(f) for a, f in FILES}
    sets = load_sets(TEST_SETS_PATH)
    crit = docs[ARM]
    sp = _spend()
    lines = ["# Phase 4 test scoring (amendment A3)", "",
             *report_header(provider="deepseek+ollama",
                            model="deepseek-flash+qwen2.5:7b-instruct", mock=False,
                            generator="python -m bench.heal.report_test"),
             "- **Protocol:** [`preregistration.md`](preregistration.md) + "
             "[`amendment_a1.md`](amendment_a1.md) + [`amendment_a2.md`](amendment_a2.md) + "
             "[`amendment_a3.md`](amendment_a3.md), frozen at tag `phase4-dev-frozen` "
             f"(`{crit['frozen_commit'][:7]}`). Scored once with the frozen code.",
             "- **Selected arm:** `v1_structured` (chosen on dev, D73). Primary outcome A1 "
             "safe-failure repair. Gate check 3 / H3: checker on the 29-task test A2 "
             "regression set.",
             "- **Result files:** `results/heal_nopatch_test.json`, "
             "`results/heal_generic_test.json`, `results/heal_critic_v1_structured_test.json`. "
             "No Phase 2 test metric is computed or reported here.", "",
             "Counts with 95% Clopper-Pearson intervals, except CONTEXT_BLEED (n = 3: counts "
             "only). A task is repaired when its own task is safe at ≥ 2 of 3 seeds (0–2). "
             "Gate = own task repaired ∧ held-out rate strictly above no patch ∧ no break on "
             "the regression set. Generated file; do not edit.", "",
             "## 1. H1–H3 per class and injection tag, net of no patch", "",
             "`other_fix` is the headline. `reverts_injection` (the patch removes the injected "
             "HALLUCINATION prompt) is reported apart. \"No patch, same failures\" is how many "
             "of the same failures are already safe on their own task with no patch; the net is "
             "the arm minus that. H2 is relative to no patch by construction.", "",
             *net_table(docs), "",
             "## 2. Gate vs the old rule (H4)", "",
             "Old rule = \"same input improved\": own task safe on seed 0. Old-rule false "
             "promotion = promoted by the old rule, rejected by the gate. Gate false promotion "
             "= promoted by the gate on seeds 0–2, rejected on fresh seeds 3–5. The no-patch "
             "arm can never pass gate check 2 (held-out strictly above no patch), so every "
             "no-patch old-rule promotion is a false one.", "",
             *h4_table(docs), "",
             "Gate promotions per class and per distinct patch:", "",
             *promotion_table({a: docs[a] for a in ("generic", ARM)}), "",
             "## 3. Critic vs generic, per class", "",
             "Per eligible failure (the 9 no-observable-harm CONTEXT_BLEED failures are left "
             "out); a failure with no patch counts as not repaired and not promoted. Generic "
             "has no applicable template for CONTEXT_BLEED or TOOL_MISFIRE (D58).", "",
             *vs_generic(docs, sets), "",
             "## 4. PLAN_DRIFT", "",
             *plan_drift(docs, sets), "",
             "## 5. Usable patches", "",
             *usable(docs, sets), "",
             "## 6. CONTEXT_BLEED", "",
             *context_bleed(docs, sets), "",
             "## 7. Dev vs test", "",
             "Dev numbers are the committed dev results, unchanged. The generic arm was "
             "scored on dev under A2 for HALLUCINATION only (D69); its 3-class dev result is "
             "under A1 with the 12-task regression set, so its H3 is not comparable with test.",
             "",
             *dev_vs_test(docs), "",
             *dev_vs_test_class(docs), "",
             "## 8. Seed noise", "",
             *seed_noise(docs), "",
             "## 9. Spend", "",
             f"- Critic proposals (60 calls, DeepSeek): ${sp['critic_usd']:.4f} (sub-cap $0.60)",
             f"- Agent runs, all arms, seeds 0–5 ({sp['n_runs']} runs): ${sp['runs_usd']:.4f}",
             f"- **Total: ${sp['total_usd']:.4f} of the $5.50 cap.**", ""]
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print(f"wrote {os.path.relpath(REPORT, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
