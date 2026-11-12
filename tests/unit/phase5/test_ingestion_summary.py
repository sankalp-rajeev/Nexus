"""Keep independently timed load experiments and their criteria visible."""
import json

from scripts.phase5 import finalize


def test_addon_summary_preserves_original_and_selects_highest_passing_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(finalize,"RESULTS",tmp_path)

    def step(rate, sustainable):
        return dict(offered_rate_events_s=rate,accepted_events_s=rate+.01,
                    sustainable=sustainable,resources={},
                    lag_growth={"classifier":{"growing":not sustainable}})

    original = dict(steps=[step(20,True),step(80,False)],machine={"host":"same"},
                    started_at="initial-start",ended_at="initial-end")
    checkpoint = dict(step(40,False), offered_traces=446, assembled_traces_at_detection_drain=445,
                      assembled_traces_post_run=446, lag_growth={"classifier":{"growing":False}})
    addon = dict(steps=[step(30,True),checkpoint,step(60,False)],machine={"host":"same"},
                 started_at="addon-start",ended_at="addon-end")
    initial_path = tmp_path/"ingestion_load.json"
    initial_path.write_text(json.dumps(original),encoding="utf-8")
    initial_bytes = initial_path.read_bytes()
    (tmp_path/"ingestion_load_addon.json").write_text(json.dumps(addon),encoding="utf-8")
    result = finalize.finish_ingestion()
    assert result["max_sustained_events_s"] == 30.01
    assert result["max_stable_lag_events_s"] == 40.01
    assert result["persistence_checkpoint_exceptions"][0]["assembled_post_run"] == 446
    assert [s["offered_rate_events_s"] for s in result["steps"]] == [20,30,40,60,80]
    assert [r["run"] for r in result["run_windows"]] == ["initial","add-on"]
    assert len(result["sources"]) == 2
    assert initial_path.read_bytes() == initial_bytes
