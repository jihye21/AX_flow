# backend/utils/idempotency.py
import hashlib

def make_key(run_id, po_id, approval_id):
    raw = f"{run_id}:{po_id}:{approval_id}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()