"""Scan staged blobs for prohibited paths and secrets without printing values."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT)


def main():
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    names = [n for n in names if n]
    if not names:
        raise RuntimeError("No staged files to scan")
    secrets = []
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #")[0].strip().strip('"').strip("'")
        if value and value not in {"nexus_dev_password", "your_gemini_api_key_here"} and any(k in key.upper() for k in ("KEY", "SECRET", "TOKEN", "PASSWORD", "WEBHOOK")):
            secrets.append(value.encode())
    patterns = [rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}", rb"AIza[0-9A-Za-z_-]{30,}",
                rb"gh[opusr]_[A-Za-z0-9]{30,}", rb"github_pat_[A-Za-z0-9_]{30,}",
                rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
    for name in names:
        path = Path(name)
        if (path.name == ".env" or any(p in {"runs", "logs"} for p in path.parts)
                or path.suffix in {".jsonl", ".patch"} or path.name == "frozen_patches_export.tgz"):
            raise RuntimeError(f"Prohibited staged path: {name}")
        blob = git("show", ":" + name)
        if any(secret in blob for secret in secrets) or any(re.search(pattern, blob) for pattern in patterns):
            raise RuntimeError(f"Possible secret in staged file: {name}; no values printed")
    print(f"PASS: {len(names)} explicitly staged files; no forbidden paths or detected secrets")


if __name__ == "__main__":
    main()
