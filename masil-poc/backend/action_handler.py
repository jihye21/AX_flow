# backend/action_handler.py
import os
import json
import uuid
import subprocess
from datetime import datetime
from tools import mock_supplier
from integrations import supplier_adapter_template
from utils import idempotency

RUNS_DIR = os.environ.get("RUNS_DIR", "masil-poc/results")

def now_iso():
    return datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def write_event(run_out, event):
    events_file = os.path.join(run_out, "events_log.csv")
    header_needed = not os.path.exists(events_file)
    with open(events_file, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("event_id|run_id|entity_type|entity_id|event_type|actor|payload|timestamp\n")
        f.write("|".join([
            event["event_id"],
            event["run_id"],
            event["entity_type"],
            event["entity_id"],
            event["event_type"],
            event["actor"],
            json.dumps(event["payload"], ensure_ascii=False),
            event["timestamp"]
        ]) + "\n")

def record_approval(run_out, approval_id, plan_id, actor):
    # append approval record file
    approvals_file = os.path.join(run_out, "approvals.csv")
    header = not os.path.exists(approvals_file)
    with open(approvals_file, "a", encoding="utf-8") as f:
        if header:
            f.write("approval_id|plan_id|actor|status|comment|timestamp\n")
        f.write("|".join([approval_id, plan_id, actor, "APPROVED", "", now_iso()]) + "\n")

def execute_approval(run_out, approval_id, po_id, amount, actor, signature_token=None, execute_mode="dry"):
    """
    execute_mode: "dry" or "real"
    This function chooses mock or real adapter based on FEATURE_REAL_EXECUTION env.
    """
    run_id = None
    # try get run_id from run_metadata.json
    meta_path = os.path.join(run_out, "run_metadata.json")
    if os.path.exists(meta_path):
        try:
            run_id = json.load(open(meta_path)).get("run_id")
        except Exception:
            run_id = "unknown-run"
    else:
        run_id = "unknown-run"

    event_id = f"E-EXEC-{uuid.uuid4().hex[:8]}"
    # idempotency key
    idem_key = idempotency.make_key(run_id, po_id, approval_id)

    feature_real = os.getenv("FEATURE_REAL_EXECUTION", "false").lower() == "true"
    # honor execute_mode param: allow forcing dry in prod if needed
    real_exec = feature_real and execute_mode == "real"

    if real_exec:
        # call real adapter (template) - implement send_payment in supplier_adapter_template
        try:
            resp = supplier_adapter_template.send_payment(run_id=run_id, po_id=po_id, amount=amount, idempotency_key=idem_key)
            event = {
                "event_id": event_id,
                "run_id": run_id,
                "entity_type": "PO",
                "entity_id": po_id,
                "event_type": "SUPPLIER_SENT",
                "actor": actor,
                "payload": resp,
                "timestamp": now_iso()
            }
            write_event(run_out, event)
            return event
        except Exception as e:
            # log failure event
            event = {
                "event_id": event_id,
                "run_id": run_id,
                "entity_type": "PO",
                "entity_id": po_id,
                "event_type": "SUPPLIER_FAILED",
                "actor": actor,
                "payload": {"error": str(e)},
                "timestamp": now_iso()
            }
            write_event(run_out, event)
            raise
    else:
        # dry-run / mock supplier
        ev = mock_supplier.simulate_response(po_id=po_id, amount=amount, scenario="random", run_id=run_id, supplier="MockSup")
        write_event(run_out, ev)
        return ev