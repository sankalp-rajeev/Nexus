"""Read-only DeepSeek account balance; never log keys, headers or error bodies."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import httpx
from bench.llm import load_env
from scripts.phase5.measurement import atomic_json


def main():
    load_env(str(ROOT/".env"))
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), source="https://api.deepseek.com/user/balance")
    try:
        with httpx.Client(timeout=30,follow_redirects=False) as client:
            response = client.get(result["source"],headers={"Authorization":"Bearer "+os.environ["DEEPSEEK_API_KEY"]})
        result["http_status"] = response.status_code
        if response.status_code==200:
            data = response.json()
            result.update(is_available=data.get("is_available"),balances=[{k:b.get(k) for k in
                ("currency","total_balance","granted_balance","topped_up_balance")} for b in data.get("balance_infos",[])])
    except Exception as exc:
        result["error"] = type(exc).__name__
    atomic_json(ROOT/"data/phase5/runs/deepseek_balance.json",result)
    print(result)


if __name__ == "__main__":
    main()
