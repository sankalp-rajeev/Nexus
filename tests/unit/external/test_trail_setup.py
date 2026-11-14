"""Split/join and dev-isolation checks using synthetic data only."""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.external import prepare_trail as setup
from scripts.external import trail_dev_check as check


def synthetic_files(tmp_path, monkeypatch):
    files = {}
    for split, offset, count in (("gaia", 1, 4), ("swe_bench", 10, 2)):
        rows = [{"trace": json.dumps({"trace_id": f"{i:032x}", "spans": []}),
                 "labels": json.dumps({"trace_id": f"{i:032x}", "errors": [], "scores": []})}
                for i in range(offset, offset + count)]
        path = tmp_path / (split + ".parquet")
        pq.write_table(pa.Table.from_pylist(rows), path)
        files[split] = path
    monkeypatch.setattr(setup, "parquet_files", lambda: files)
    monkeypatch.setattr(setup, "EXPECTED", {"gaia": 4, "swe_bench": 2})
    monkeypatch.setattr(setup, "DEV_COUNTS", {"gaia": 2, "swe_bench": 1})
    monkeypatch.setattr(setup, "SPLITS", tmp_path / "sealed")
    return files


def test_seal_is_deterministic_disjoint_and_refuses_replacement(tmp_path, monkeypatch):
    synthetic_files(tmp_path, monkeypatch)
    manifest = setup.seal()
    assert setup.seal() == manifest
    for split in setup.EXPECTED:
        dev = set((setup.SPLITS / f"dev_{split}.txt").read_text().splitlines())
        test = set((setup.SPLITS / f"test_{split}.txt").read_text().splitlines())
        assert not dev & test
        assert len(dev) == setup.DEV_COUNTS[split]
        assert len(dev | test) == setup.EXPECTED[split]
    (setup.SPLITS / "dev_gaia.txt").write_text("tampered\n")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        setup.seal()


def test_label_join_uses_ids_and_reports_invalid_missing_and_orphan_keys(tmp_path, monkeypatch):
    files = synthetic_files(tmp_path, monkeypatch)
    rows = pq.read_table(files["gaia"]).to_pylist()
    rows[0]["labels"] = json.dumps({"trace_id": f"{2:032x}"})
    rows[1]["labels"] = json.dumps({"errors": []})
    rows[2]["labels"] = "invalid synthetic JSON"
    rows[3]["labels"] = json.dumps({"trace_id": f"{99:032x}"})
    pq.write_table(pa.Table.from_pylist(rows), files["gaia"])
    _, audit = setup.read_ids()
    gaia = audit["gaia"]
    assert gaia["joined"] == 1
    assert gaia["traces_without_labels"] == [f"{i:032x}" for i in (1, 3, 4)]
    assert gaia["labels_without_traces"] == [f"{99:032x}"]
    assert gaia["row_trace_ids_with_missing_label_trace_id"] == [f"{2:032x}"]
    assert gaia["row_trace_ids_with_invalid_label_json"] == [f"{3:032x}"]


def test_duplicate_label_keys_fail_closed(tmp_path, monkeypatch):
    files = synthetic_files(tmp_path, monkeypatch)
    rows = pq.read_table(files["gaia"]).to_pylist()
    rows[1]["labels"] = rows[0]["labels"]
    pq.write_table(pa.Table.from_pylist(rows), files["gaia"])
    with pytest.raises(RuntimeError, match="Duplicate label"):
        setup.read_ids()


def test_dev_loader_never_deserializes_test_or_reads_labels(monkeypatch):
    selected, sealed = f"{1:032x}", f"{2:032x}"
    # The sealed trace is intentionally not parseable after its leading ID.
    table = pa.table({"trace": [json.dumps({"trace_id": selected, "spans": []}),
                                '{"trace_id": "' + sealed + '", INVALID SEALED DATA']})
    def read_table(path, columns):
        assert columns == ["trace"]
        return table
    monkeypatch.setattr(check, "dev_ids", lambda: {"synthetic": {selected}})
    monkeypatch.setattr(check, "parquet_files", lambda: {"synthetic": "unused"})
    monkeypatch.setattr(pq, "read_table", read_table)
    assert list(check.dev_traces()) == [("synthetic", {"trace_id": selected, "spans": []})]


@pytest.mark.parametrize("text,readable", [(None, False), ("OK", False), ("x" * 30, False), ("synthetic source has readable text", True)])
def test_readable_source_gate(text, readable):
    assert check.readable_source(text) is readable
