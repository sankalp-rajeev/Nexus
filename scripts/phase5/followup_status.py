"""Read-only counts/spend/status for the capped follow-up experiments."""
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2] / "data/phase5/runs"


def status():
    output = {}
    for name, folder in (("L3 heals", "l3_heals"),("Gemini side", "gemini_side")):
        root = ROOT/folder
        if not (root/"budget.sqlite3").exists():
            continue
        with sqlite3.connect(f"file:{(root/'budget.sqlite3').as_posix()}?mode=ro",uri=True) as conn:
            dollars, stopped = conn.execute("SELECT provider_spent,stopped FROM budget").fetchone()
            attempts = conn.execute("SELECT count(*) FROM calls").fetchone()[0]
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (root/"records").glob("*.json")]
        output[name] = dict(done=len(records), planned=20, DeepSeek_provider_usd=dollars,
                            DeepSeek_attempts=attempts, status="capped" if stopped else "complete" if len(records)==20 else "running")
        if folder == "l3_heals":
            output[name]["done_by_level"] = {str(c):sum(r["item_id"].startswith(f"c{c}-") for r in records) for c in (1,4)}
        path = root/"gemini.sqlite3"
        if path.exists():
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True) as conn:
                rows = [json.loads(r[0]) for r in conn.execute("SELECT record FROM calls")]
                output[name]["Gemini_stopped"] = bool(conn.execute("SELECT stopped FROM state WHERE id=1").fetchone()[0])
            output[name]["Gemini_usage_priced_usd"] = sum(r.get("cost_usd") or 0 for r in rows)
    return output


if __name__ == "__main__":
    print(json.dumps(status()))
