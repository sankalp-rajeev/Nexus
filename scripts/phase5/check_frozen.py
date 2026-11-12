"""Read-only Phase 5 freeze check; never imports or opens benchmark splits.

Container Dockerfiles and requirements are deliberately outside the freeze.
Frozen content must match after CRLF-to-LF normalization; checkout-only CRLF
differences are informational. No working file or Git setting is modified.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TAG = "phase4-test-scored"
PATHS = (
    "services/detectors/",
    "bench/detector_view.py",
    "services/critic/",
    ":(exclude)services/critic/Dockerfile",
    ":(exclude)services/critic/requirements.txt",
    "services/healer/gate.py",
    "bench/heal/",
    "bench/agent.py",
    "bench/tools.py",
    "bench/world.py",
    "bench/labeler.py",
)


def git(*args):
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout


def main():
    if git("branch", "--show-current").decode().strip() != "phase-5-perf":
        raise RuntimeError("Phase 5 must run on phase-5-perf")
    git("merge-base", "--is-ancestor", TAG, "HEAD")
    print(f"Frozen reference: {TAG}")
    tree = git("ls-tree", "-r", "--name-only", TAG, "--",
               *(p for p in PATHS if not p.startswith(":")))
    paths = b"".join(line + b"\n" for line in tree.splitlines()
                     if line.decode() not in {
                         "services/critic/Dockerfile", "services/critic/requirements.txt"})
    print("Exact frozen paths:\n" + paths.decode(), end="")
    print(f"git diff --stat {TAG} -- " + " ".join(PATHS), flush=True)
    diff = git("diff", "--stat", TAG, "--", *PATHS)
    sys.stdout.write(diff.decode())
    if diff or git("diff", "--name-only", TAG, "--", *PATHS):
        raise RuntimeError("Frozen paths differ; STOP")
    # Independently compare content, permitting only the Windows CRLF conversion.
    for name in paths.decode().splitlines():
        working = (ROOT / name).read_bytes()
        scored = git("show", f"{TAG}:{name}")
        if working.replace(b"\r\n", b"\n") != scored.replace(b"\r\n", b"\n"):
            raise RuntimeError(f"Frozen working bytes differ: {name}; STOP")
        if working != scored:
            print(f"INFO: raw-byte CRLF-only difference: {name}")
    print("PASS: empty diff; all frozen content matches after CRLF-to-LF normalization.")


if __name__ == "__main__":
    main()
