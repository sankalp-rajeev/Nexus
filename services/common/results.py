"""Write experiment result files to ``results/`` (Improvement Plan, rule 1).

Every result JSON carries provenance: experiment id, UTC date, git commit (and
whether the tree was dirty), provider/model, mock flag and seed. RESULTS.md is
generated from these files by ``scripts/build_results_md.py``; never hand-edit
numbers into it.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import subprocess
from typing import Any

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_DIR = os.path.join(REPO, "results")


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=REPO, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


def provenance(*, provider: str, model: str, mock: bool, seed: int | None) -> dict[str, Any]:
    return {
        "date_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        # Dirty = uncommitted *source* changes; generated outputs don't count.
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no", "--", ".",
                               ":!results", ":!RESULTS.md", ":!docs")),
        "provider": provider,
        "model": model,
        "mock": mock,
        "seed": seed,
    }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; None when n == 0."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def rate(successes: int, n: int) -> dict[str, Any]:
    """A proportion reported with its counts and 95% interval (rule 3)."""
    return {
        "value": round(successes / n, 4) if n else None,
        "k": successes,
        "n": n,
        "ci95": wilson_interval(successes, n),
    }


def write_result(experiment_id: str, filename: str, payload: dict[str, Any],
                 *, provenance_info: dict[str, Any], summary: str) -> str:
    """Write ``results/<filename>`` and return its path.

    ``summary`` is the one-line human-readable result used in RESULTS.md.
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)
    doc = {
        "experiment_id": experiment_id,
        "summary": summary,
        "provenance": provenance_info,
        "results": payload,
    }
    path = os.path.join(RESULTS_DIR, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, sort_keys=False, default=str)
        fh.write("\n")
    return path


def report_header(*, provider: str, model: str, mock: bool, generator: str,
                  result_file: str | None = None) -> list[str]:
    """Standard provenance header every docs/*report*.md must carry."""
    lines = [
        f"- **Provider:** {provider}",
        f"- **Model:** {model}",
        f"- **Mock:** {'yes' if mock else 'no'}",
        f"- **Generated:** {_dt.date.today().isoformat()} at commit "
        f"`{_git('rev-parse', '--short', 'HEAD')}` by `{generator}`",
    ]
    if result_file:
        lines.append(f"- **Result file:** [`{result_file}`](../{result_file})")
    return lines
