"""Run Docker with .env values redacted from captured diagnostic output."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def redact(text):
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.split(" #")[0].strip().strip('"').strip("'")
            if value and (len(value) >= 8 or any(k in key.upper() for k in ("KEY", "TOKEN", "PASSWORD", "WEBHOOK"))):
                text = text.replace(value, "[REDACTED]")
    return text


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    result = subprocess.run(["docker", *sys.argv[1:]], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(redact(result.stdout.decode("utf-8", errors="replace")), flush=True)
    sys.exit(result.returncode)
