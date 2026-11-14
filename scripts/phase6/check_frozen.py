"""Check Phase 6 against the shared Phase 5 freeze without opening TEST."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase5.check_frozen import PATHS, TAG, git  # noqa: E402


def check_branch(branch: str) -> None:
    """Refuse only on main: work happens on a branch and reaches main through a PR.

    Any other branch (and a detached HEAD, reported as "") is allowed.
    """
    if branch == "main":
        raise RuntimeError("Run the Phase 6 frozen check on a working branch, not on main")


def main():
    check_branch(git("branch", "--show-current").decode().strip())
    git("merge-base", "--is-ancestor", TAG, "HEAD")
    print(f"Frozen reference: {TAG}")
    tree = git("ls-tree", "-r", "--name-only", TAG, "--",
               *(p for p in PATHS if not p.startswith(":")))
    excluded = {p.removeprefix(":(exclude)") for p in PATHS
                if p.startswith(":(exclude)")}
    paths = b"".join(line + b"\n" for line in tree.splitlines()
                     if line.decode() not in excluded)
    print("Exact frozen paths:\n" + paths.decode(), end="")
    print(f"git diff --stat {TAG} -- " + " ".join(PATHS), flush=True)
    diff = git("diff", "--stat", TAG, "--", *PATHS)
    sys.stdout.write(diff.decode())
    if diff or git("diff", "--name-only", TAG, "--", *PATHS):
        raise RuntimeError("Frozen paths differ; STOP")
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
