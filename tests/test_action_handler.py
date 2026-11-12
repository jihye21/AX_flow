# tests/test_action_handler.py
import os
from backend.action_handler import execute_approval
import tempfile
import json

def test_execute_mock(tmp_path, monkeypatch):
    # prepare a fake run_out with run_metadata.json
    run_out = str(tmp_path / "run1")
    os.makedirs(run_out, exist_ok=True)
    meta = {"run_id":"test-run-1"}
    with open(os.path.join(run_out, "run_metadata.json"), "w") as f:
        json.dump(meta, f)
    # ensure FEATURE_REAL_EXECUTION false
    monkeypatch.setenv("FEATURE_REAL_EXECUTION", "false")
    ev = execute_approval(run_out, approval_id="A1", po_id="SPO-1", amount=1000, actor="tester")
    assert ev["entity_id"] == "SPO-1"
    assert "SUPPLIER" in ev["event_type"]