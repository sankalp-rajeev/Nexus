"""Stage pinned inference artifacts as local model-name directories for CI.

Frozen constructors retain their model IDs. Those IDs resolve to local pinned
snapshots, without offline environment flags or any scoring/loader monkeypatch.
No dataset, prompts, credentials or provider API calls are involved.
"""
import argparse
from fnmatch import fnmatch
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = ("*.json", "*.safetensors", "*.txt", "*.model", "README.md")
OUTPUT_NAMES = {
    "cross-encoder/nli-deberta-v3-base": "deberta",
    "cross-encoder/nli-MiniLM2-L6-H768": "classifier_nli",
    "sentence-transformers/all-MiniLM-L6-v2": "embedder",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", action="store_true")
    parser.add_argument("--from-cache", type=Path, help="Copy an existing local HF hub cache instead of downloading")
    args = parser.parse_args()
    pins = json.loads((ROOT/".github/model-revisions.json").read_text(encoding="utf-8"))
    if set(pins) != set(OUTPUT_NAMES):
        raise ValueError("Expected the three configured CI models")
    for repo, revision in pins.items():
        name = OUTPUT_NAMES[repo]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+",repo) or not re.fullmatch(r"[a-f0-9]{40}",revision):
            raise ValueError("Model ID and exact 40-character revision required")
        if args.outputs:
            print(f"{name}={revision}")
            continue
        target = ROOT/repo
        marker = target/".nexus-model-revision"
        ready = marker.exists() and marker.read_text().strip()==revision and all(
            (target/p).is_file() for p in ("config.json","model.safetensors","tokenizer.json"))
        if not ready:
            if args.from_cache:
                snapshot = args.from_cache/("models--"+repo.replace("/","--"))/"snapshots"/revision
                if not snapshot.is_dir():
                    raise RuntimeError(f"Pinned model not cached: {repo}@{revision}")
                for source in snapshot.rglob("*"):
                    relative = source.relative_to(snapshot)
                    if source.is_file() and any(fnmatch(relative.as_posix(),p) for p in PATTERNS):
                        destination = target/relative
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(source,destination)
            else:
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id=repo, revision=revision, local_dir=target,
                                  allow_patterns=list(PATTERNS),token=False)
            if not all((target/p).is_file() for p in ("config.json","model.safetensors","tokenizer.json")):
                raise RuntimeError(f"Pinned model incomplete: {repo}@{revision}")
            marker.write_text(revision+"\n",encoding="utf-8")
        print(f"Pinned model ready: {repo}@{revision}")


if __name__ == "__main__":
    main()
