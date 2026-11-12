# backend/integrations/supplier_adapter_template.py
import os, requests, json, time

SUPPLIER_API_URL = os.getenv("SUPPLIER_API_URL", "https://supplier.example/api")
API_KEY = os.getenv("SUPPLIER_API_KEY", None)
TIMEOUT = 30

def send_payment(run_id, po_id, amount, idempotency_key, beneficiary=None):
    """
    Template for sending payment request to supplier.
    Implement real auth, payload and error handling as needed.
    Returns a dict with at least: status, confirmed_amount, confirmed_date, reference
    """
    url = f"{SUPPLIER_API_URL}/payments"
    headers = {"Content-Type":"application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    payload = {
        "run_id": run_id,
        "po_id": po_id,
        "amount": amount,
        "idempotency_key": idempotency_key,
        "beneficiary": beneficiary or {}
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()