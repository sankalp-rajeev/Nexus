"""Offline DEV provenance check. Never opens TEST run or result files.

Whole-file labels hashing treats the explicitly requested provenance input as
opaque bytes: no TEST row, label, trace or task is deserialized.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

from bench.heal.config import ConfigPatch, apply_patch, config_hash, faulted_config
from services.critic.arms import original_prompts
from services.critic.round2_legacy import BASE, git_source


def sha(data):
    return hashlib.sha256(data).hexdigest()


def doc(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def source(ref, path):
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "show", f"{ref}:{path}"], cwd=ROOT)


def audit():
    protocol = doc("reports/phase3/round3/protocol.json")
    reconciliation = doc("reports/phase3/round3/phase4_reconciliation.json")
    sets = doc("reports/phase4/prereg_sets.json")
    rows = []

    def check(name, recorded, data, method, local=None):
        now = sha(data)
        raw = data if local is None else local
        lf = raw.replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        rows.append(dict(name=name, recorded=recorded, now=now, match=recorded == now,
                         method=method, working_raw_sha256=sha(raw),
                         working_lf_sha256=sha(lf), working_crlf_sha256=sha(crlf)))

    for key, path in (("detector_view_sha256", "bench/detector_view.py"),
                      ("prediction_source_sha256", "results/phase2_dev_predictions.json")):
        check(path, protocol[key], (ROOT / path).read_bytes(), "working read_bytes")
    check("labels.csv (DEV prereg provenance)", sets["labels_sha256"],
          (ROOT / "data/nexusbench/labels.csv").read_bytes(), "sets.file_sha256: rb, opaque bytes")
    for key, path, ref in (
        ("labels_sha256", "data/nexusbench/labels.csv", reconciliation["main_commit"]),
        ("prereg_sets_sha256", "reports/phase4/prereg_sets.json", reconciliation["phase4_commit"])):
        check("reconciliation: " + path, reconciliation[key], source(ref, path),
              f"git show {ref}:{path}", (ROOT / path).read_bytes())
    for name, recorded in reconciliation["loader_contract_sha256"].items():
        path = f"bench/heal/{name}.py"
        check("loader contract: " + name, recorded, source(reconciliation["phase4_commit"], path),
              "git show pinned Phase 4 commit", (ROOT / path).read_bytes())
    for name, recorded in protocol["original_source_sha256"].items():
        path = "services/critic/" + name
        check("original source: " + name, recorded, git_source(path),
              f"git show {BASE}", (ROOT / path).read_bytes())
    hashes = original_prompts()[1]
    provenance_records = 0
    for arm in ("v1_structured", "new"):
        with (ROOT / f"reports/phase3/round3/{arm}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                rec = json.loads(line)
                assert rec["trace_id"] in {f["trace_id"] for f in sets["failures"]}
                prov = rec.get("provenance") or (rec.get("proposal") or {}).get("provenance") or {}
                for name, recorded in prov.get("prompt_hashes", {}).items():
                    provenance_records += 1
                    rows.append(dict(name=f"prompt provenance: {arm}/{rec['trace_id']}/{name}",
                                     recorded=recorded, now=hashes[name], match=recorded == hashes[name],
                                     method="arms.original_prompts(): pinned git bytes"))
    patches = {ConfigPatch.none().patch_hash: ConfigPatch.none()}
    for path in (ROOT / "results").glob("heal*dev.json"):
        for h, value in json.loads(path.read_text(encoding="utf-8"))["results"].get("patches", {}).items():
            patch = ConfigPatch.from_json(value)
            if patch.patch_hash != h:
                raise RuntimeError(f"Patch registry key mismatch: {path.name}")
            patches[h] = patch
    configurations = {}
    count = 0
    missing = set()
    # harness.py documents this as DEV; test_phase.py uses heal_runs_test.jsonl.
    with (ROOT / "results/heal_runs.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            rec = json.loads(line)
            patch = patches.get(rec["patch_hash"])
            if patch is None:
                missing.add(rec["patch_hash"])
                continue
            fault = "HALLUCINATION" if rec["base"] == "guess" else "NONE"
            now = config_hash(apply_patch(faulted_config(fault), patch))
            key = (rec["base"], rec["patch_hash"], rec["intended_config_hash"], rec["applied_config_hash"])
            configurations[key] = now
            count += 1
    for (base, patch, intended, applied), now in sorted(configurations.items()):
        for kind, recorded in (("intended", intended), ("applied", applied)):
            rows.append(dict(name=f"config {kind}: {base}/{patch}", recorded=recorded,
                             now=now, match=recorded == now,
                             method="config_hash(apply_patch(faulted_config, saved patch)); canonical JSON"))
    return dict(status="PASS" if all(r["match"] for r in rows) and not missing else "FAIL",
                checks=rows, config_run_records=count, distinct_configs=len(configurations),
                prompt_provenance_checks=provenance_records, missing_patch_hashes=sorted(missing))


if __name__ == "__main__":
    result = audit()
    if "--save" in sys.argv:
        out = ROOT / "reports/phase5"
        out.mkdir(parents=True, exist_ok=True)
        (out / "hash_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("name | Phase 4 recorded | now | match")
    for r in result["checks"]:
        print(f"{r['name']} | {r['recorded']} | {r['now']} | {r['match']}")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}))
    sys.exit(0 if result["status"] == "PASS" else 1)
