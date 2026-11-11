"""Offline saved-proposal hardening and proxy agreement audit. No generation."""
import collections
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(ROOT / "sdk"))

from nexus_agent.models import PatchProposal  # noqa: E402
from services.critic.dev_adapter import CLASSES, dev_labels  # noqa: E402
from services.critic.fault_reversal import phase1_config_constants, snapshots, tag_fix  # noqa: E402
from services.critic.hardening import inspect_patch  # noqa: E402
from services.critic.proxy_sample import ARMS  # noqa: E402
from services.critic.registry import ConfigRegistry  # noqa: E402

OUT = ROOT / "reports/phase3/round3_preflight"


def binary_agreement(pairs):
    """Pairs are (reviewer_grounded, literal_proxy_grounded). No sklearn needed."""
    counts = collections.Counter(pairs)
    n = len(pairs)
    agree = sum(a == b for a, b in pairs)
    reviewer_yes = sum(a for a, _ in pairs)
    proxy_yes = sum(b for _, b in pairs)
    observed = agree/n if n else None
    expected = (reviewer_yes*proxy_yes + (n-reviewer_yes)*(n-proxy_yes))/n**2 if n else None
    kappa = (observed-expected)/(1-expected) if expected is not None and expected != 1 else None
    return {"n": n, "agreement_count": agree, "agreement": observed,
            "expected_agreement": expected, "cohens_kappa": kappa,
            "reviewer_grounded": reviewer_yes, "proxy_grounded": proxy_yes,
            "confusion": {"both_grounded": counts[True, True],
                "reviewer_only_grounded": counts[True, False],
                "proxy_only_grounded": counts[False, True], "both_ungrounded": counts[False, False]}}


def score_proxy(sheet_path, key_path):
    sheet = sheet_path.read_text(encoding="utf-8")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    sections = re.split(r"^## (P\d{2})\s*$", sheet, flags=re.M)
    verdicts = {}
    for i in range(1, len(sections), 2):
        ident, body = sections[i:i+2]
        matches = re.findall(r"^\|\s*(grounded|ungrounded|unclear)\s*\|", body, re.M)
        if len(matches) != 1 or ident in verdicts:
            raise ValueError(f"Expected one unique verdict for {ident}")
        verdicts[ident] = matches[0]
    ids = [r["sample_id"] for r in key["samples"]]
    if len(ids) != 20 or len(set(ids)) != 20 or set(ids) != set(verdicts):
        raise ValueError("Reviewer/key must have exactly the same 20 unique sample IDs")
    details = [{"sample_id": r["sample_id"], "verdict": verdicts[r["sample_id"]],
                "proxy_grounded": bool(r["grounding"]["grounded"])} for r in key["samples"]]
    def pairs(unclear):
        return [(unclear if r["verdict"] == "unclear" else r["verdict"] == "grounded", r["proxy_grounded"])
                for r in details if unclear is not None or r["verdict"] != "unclear"]
    return {"reviewer": "model-reviewed, author-confirmed; revised after Codex feedback",
            "independent_human_validation": False, "counts": dict(collections.Counter(verdicts.values())),
            "unclear_as_ungrounded": binary_agreement(pairs(False)),
            "unclear_as_grounded": binary_agreement(pairs(True)),
            "unclear_excluded": binary_agreement(pairs(None)), "samples": details,
            "sheet_sha256": hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
            "key_sha256": hashlib.sha256(key_path.read_bytes()).hexdigest()}


def audit_round2(output=OUT):
    output.mkdir(parents=True, exist_ok=True)
    labels = {r["trace_id"]: r for r in dev_labels(ROOT / "data/nexusbench/labels.csv")}
    constants = phase1_config_constants()
    summary = {"snapshot": "phase-1-nexusbench literal constants; selected DEV fault for scoring only",
               "hardening_version": "explicit-reference-grammar-v1", "arms": {}, "sources_sha256": {}}
    for arm in ARMS:
        path = ROOT / f"results/critic_dev/round2/{arm}.jsonl"
        summary["sources_sha256"][arm] = hashlib.sha256(path.read_bytes()).hexdigest()
        saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        audits = []
        for record in saved:
            label = labels[record["trace_id"]]
            injected, clean = snapshots(label, constants=constants)
            p = PatchProposal.model_validate(record["proposal"])
            checks = inspect_patch(p, injected)
            try:
                ConfigRegistry(injected).apply(p)
                dry_run, reason = True, None
            except (ValueError, TypeError) as exc:
                dry_run, reason = False, str(exc)
            tag = tag_fix(p, injected, clean)
            audits.append({"trace_id": record["trace_id"], "failure_type": record["failure_type"],
                "arm": arm, **asdict(checks), "hardened_dry_run": dry_run, "rejection_reason": reason,
                "restored_paths": tag["restored_paths"],
                "proposal": {**record["proposal"], "no_op_patch": checks.no_op,
                    "bad_references": checks.bad_references, "fix_tag": tag["fix_tag"],
                    "clean_config_diff": tag["clean_config_diff"]}})
        summary["arms"][arm] = {"n": len(audits),
            "no_op": sum(r["no_op"] for r in audits),
            "bad_reference": sum(bool(r["bad_references"]) for r in audits),
            "both": sum(r["no_op"] and bool(r["bad_references"]) for r in audits),
            "hardened_dry_run": sum(r["hardened_dry_run"] for r in audits),
            "bad_reference_reasons": dict(collections.Counter(x for r in audits for x in r["bad_references"])),
            "fix_tags_per_class": {ft: dict(collections.Counter(r["proposal"]["fix_tag"] for r in audits
                                                                  if r["failure_type"] == ft)) for ft in CLASSES}}
        (output / f"{arm}_audited.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in audits)+"\n", encoding="utf-8")
    (output / "round2_hardening.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    summary = audit_round2()
    proxy = score_proxy(ROOT / "reports/phase3/proxy_sample.md", ROOT / "reports/phase3/proxy_sample_key.json")
    (OUT / "proxy_agreement.json").write_text(json.dumps(proxy, indent=2), encoding="utf-8")
    print(json.dumps({"round2": {arm: {k: v for k, v in block.items() if k not in {"bad_reference_reasons", "fix_tags_per_class"}}
                                for arm, block in summary["arms"].items()},
                      "proxy": {k: v for k, v in proxy.items() if k in {"counts", "unclear_as_ungrounded", "unclear_as_grounded"}}}, indent=2))


if __name__ == "__main__":
    main()
