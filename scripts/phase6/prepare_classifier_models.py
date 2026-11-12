"""Build-time staging of the classifier's pinned NLI and embedding snapshots."""
import json
from pathlib import Path
import re

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[2]
MODELS = ("cross-encoder/nli-MiniLM2-L6-H768", "sentence-transformers/all-MiniLM-L6-v2")


def main():
    pins = json.loads((ROOT / ".github/model-revisions.json").read_text())
    for repo in MODELS:
        revision = pins[repo]
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError(f"Exact model revision required: {repo}")
        target = ROOT / repo
        snapshot_download(repo_id=repo, revision=revision, local_dir=target, token=False,
                          allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "README.md"])
        if not all((target / name).is_file() for name in ("config.json", "model.safetensors", "tokenizer.json")):
            raise RuntimeError(f"Incomplete model snapshot: {repo}@{revision}")
        (target / ".nexus-model-revision").write_text(revision + "\n")
        print(f"Baked classifier model: {repo}@{revision}")


if __name__ == "__main__":
    main()
