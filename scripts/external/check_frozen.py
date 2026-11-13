"""External branch entry point for the unchanged shared freeze check."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
from scripts.external.trail_dev_check import check_frozen


def check():
    import subprocess
    paths=("services/classifier/","services/collector/","services/detectors/",
           "bench/detector_view.py","sdk/nexus_agent/","sdk/nexus_llmops/",".github/model-revisions.json")
    cmd=["git","-c",f"safe.directory={ROOT.as_posix()}"]
    if subprocess.check_output(cmd+["diff","d9fef595","--",*paths],cwd=ROOT):
        raise RuntimeError("V1/live path differs from the authorized main merge")
    return {**check_frozen(),"v1_live_default_path_unchanged_from_merge":True}

if __name__ == "__main__":
    print("check_frozen.py PASS:", check())
