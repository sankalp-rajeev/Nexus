"""Cold-start lite host-ingress regression; preserves every container/volume.

Run from the repository with an already built image. A unique service and volume
keep old validation data intact. All HTTP requests originate on the host and use
the documented port 18000. The container is stopped in finally, never removed.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def command(*args, timeout=120):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                          check=True, timeout=timeout)


def docker(*args):
    return command("docker", *args).stdout


def http(path, data=None):
    request = urllib.request.Request(
        "http://127.0.0.1:18000" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    # Do not inherit proxy settings for this strictly local request.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
        return {"status_code": response.status, "body": json.load(response)}


def inspect(name):
    return json.loads(docker("inspect", name))[0]


def memory_bytes(value):
    number, unit = re.fullmatch(r"([\d.]+)([A-Za-z]+)", value.strip()).groups()
    return round(float(number) * {"B": 1, "KiB": 1024, "MiB": 1024**2,
                                 "GiB": 1024**3}[unit])


def run(image, output, hold_seconds=300):
    output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    service = "nexus-lite-61d-" + run_id
    name = "nexus-lite-" + service + "-1"
    compose_path = output / "lite.compose.json"
    result = {"status": "running", "project": "nexus-lite", "run_id": run_id,
              "container": name, "image": image, "samples": []}

    def save():
        (output / "lite-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    def note(message):
        print(datetime.now(timezone.utc).isoformat(), message, flush=True)
        save()

    def sample():
        row = json.loads(docker("stats", "--no-stream", "--format", "{{json .}}", name))
        result["samples"].append({"utc": datetime.now(timezone.utc).isoformat(),
                                  "ram_bytes": memory_bytes(row["MemUsage"].split("/")[0]),
                                  "cli_memory": row["MemUsage"]})

    def compose(*args):
        return command("docker", "compose", "--project-directory", str(ROOT),
                       "-p", "nexus-lite", "-f", str(compose_path), *args)

    assert not docker("ps", "-q", "--filter", "label=com.docker.compose.project=nexus-lite").strip(), "Lite already running"
    config = json.loads(command("docker", "compose", "--project-directory", str(ROOT),
                                "-p", "nexus-lite", "-f", str(ROOT / "docker-compose.lite.yml"),
                                "config", "--format", "json").stdout)
    assert not config["networks"]["default"].get("internal", False)
    config["networks"]["default"]["internal"] = False
    svc = config["services"].pop("nexus-lite")
    svc.pop("build")
    svc["image"] = image
    svc["pull_policy"] = "never"
    svc["environment"].update({"DO_NOT_TRACK": "1", "OTEL_SDK_DISABLED": "true",
                                "HF_HUB_DISABLE_TELEMETRY": "1"})
    config["services"][service] = svc
    config["networks"]["default"]["name"] = "nexus-lite_61d_" + run_id
    existing_volumes = set(docker("volume", "ls", "-q").split())
    for volume in config["volumes"].values():
        volume["name"] = "nexus-lite_61d_" + run_id + "_data"
        assert volume["name"] not in existing_volumes
    compose_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    result["volumes"] = [v["name"] for v in config["volumes"].values()]
    result["image_id"] = docker("image", "inspect", image, "--format", "{{.Id}}").strip()
    result["image_revision"] = docker("image", "inspect", image, "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}').strip()
    try:
        note("Cold up: fresh lite service/volume, ordinary bridge, host port 18000")
        started = time.monotonic()
        up = compose("up", "-d", "--no-build", "--pull", "never")
        (output / "lite-up.txt").write_text(up.stdout + up.stderr, encoding="utf-8")
        deadline = started + 180
        while time.monotonic() < deadline:
            state = inspect(name)
            assert state["RestartCount"] == 0, "Restart during cold startup"
            if state["State"].get("Health", {}).get("Status") == "healthy":
                response = http("/health")
                assert response["status_code"] == 200 and response["body"]["status"] == "ok"
                result["startup_seconds"] = time.monotonic() - started
                break
            sample()
            time.sleep(2)
        else:
            raise RuntimeError("Cold startup/host health deadline exceeded")
        original_started_at = state["State"]["StartedAt"]
        result["started_at"] = original_started_at
        result["host_health_after_cold_up"] = response
        note(f"Host HTTP healthy in {result['startup_seconds']:.3f}s; holding {hold_seconds}s")
        held = time.monotonic()
        observations = []
        last_note = held
        while time.monotonic() - held < hold_seconds:
            state = inspect(name)
            assert state["RestartCount"] == 0 and state["State"]["StartedAt"] == original_started_at
            assert state["State"]["Status"] == "running" and state["State"]["Health"]["Status"] == "healthy"
            observations.append({"utc": datetime.now(timezone.utc).isoformat(), "restart_count": 0, "health": "healthy"})
            sample()
            if time.monotonic() - last_note >= 30:
                note(f"Lite idle {time.monotonic() - held:.1f}/{hold_seconds}s: healthy, zero restarts")
                last_note = time.monotonic()
            time.sleep(min(3, max(0, hold_seconds - (time.monotonic() - held))))
        result["idle_hold"] = {"seconds": time.monotonic() - held, "observations": observations}
        fixture = json.loads((ROOT / "scripts/phase6/fixtures/fictional_loop.json").read_text(encoding="utf-8"))
        response = http("/v1/spans", fixture)
        assert response["status_code"] == 202 and response["body"]["accepted"] == 4 and response["body"]["rejected"] == 0
        result["host_trace_response"] = response
        time.sleep(2)
        snapshot = http("/v1/lite/snapshot")["body"]
        assert len(snapshot["traces"]) == 1 and len(snapshot["alerts"]) == 1
        assert snapshot["alerts"][0]["failure_type"] == "LOOP_DETECTED"
        assert len(snapshot["proposals"]) == 1 and snapshot["proposals"][0]["source"] == "generic_fallback_no_llm"
        result["snapshot"] = snapshot
        result["host_health_after_trace"] = http("/health")
        assert result["host_health_after_trace"]["body"]["spans_received_total"] == 4
        state = inspect(name)
        assert state["RestartCount"] == 0 and state["State"]["StartedAt"] == original_started_at
        assert state["State"]["Health"]["Status"] == "healthy"
        sample()
        peak = max(s["ram_bytes"] for s in result["samples"])
        result["ram"] = {"per_service_peak_bytes": {"nexus-lite": peak}, "sum_of_service_peaks_bytes": peak,
                         "peak_sampled_total_bytes": peak, "sample_count": len(result["samples"])}
        result["restart_counts"] = {"nexus-lite": state["RestartCount"]}
        result["same_started_at_through_host_trace"] = True
        result["status"] = "pass"
        note("PASS: cold host HTTP, fictional trace/deterministic detector, no restart or stop/start")
    except Exception as exc:
        result["status"] = "fail"
        result["error"] = repr(exc)
        save()
        raise
    finally:
        logs = command("docker", "logs", name)
        (output / "lite.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        compose("stop")
        result["stopped"] = inspect(name)["State"]["Status"] == "exited"
        save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="nexus-lite-nexus-lite")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold-seconds", type=int, default=300)
    args = parser.parse_args()
    assert args.hold_seconds >= 0
    run(args.image, args.output.resolve(), args.hold_seconds)
