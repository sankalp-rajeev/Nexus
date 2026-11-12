"""Require all 11 Phase 5 services healthy for five uninterrupted minutes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.phase5.yml"]


def snapshot():
    ids = subprocess.check_output([*COMPOSE, "ps", "--all", "-q"], cwd=ROOT, text=True).split()
    if len(ids) != 11:
        raise RuntimeError(f"Expected 11 containers, got {len(ids)}")
    # Restrict inspect output so environment credentials cannot enter this report.
    rows = []
    for container in ids:
        raw = subprocess.check_output(
            ["docker", "inspect", "--format",
             '{{.Name}}|{{.RestartCount}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.StartedAt}}',
             container], cwd=ROOT, text=True).strip()
        name, restarts, state, health, started = raw.split("|")
        rows.append(dict(name=name, restarts=int(restarts), state=state, health=health, started=started))
    return sorted(rows, key=lambda r: r["name"])


def main():
    initial = snapshot()
    out = ROOT / "data/phase5/runs"
    out.mkdir(parents=True, exist_ok=True)
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), snapshots=[])
    deadline = time.monotonic() + 300
    while True:
        current = snapshot()
        if any(r["state"] != "running" or r["health"] != "healthy" for r in current):
            raise RuntimeError("Every service must remain healthy")
        if current != initial:
            raise RuntimeError("Container identity, start time or restart count changed")
        report["snapshots"].append(dict(at=datetime.now(timezone.utc).isoformat(), containers=current))
        (out / "stack_stability.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        print(f"11/11 healthy, unchanged restarts; {max(0, round(remaining))} seconds remaining", flush=True)
        time.sleep(min(30, remaining))
    print("PASS: 11/11 healthy for 300 seconds without a restart", flush=True)
    subprocess.run([*COMPOSE, "ps"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
