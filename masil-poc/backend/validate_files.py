#!/usr/bin/env python3
import argparse,csv,os,json,hashlib,sys
from pathlib import Path
MAPPINGS = {
    "mkt_budget_plan_ms.csv": ["plan_id","campaign_id","requested_budget_krw","expected_gmv_krw","settlement_date","contract_deadline"],
    "fin_cash_daily_ms.csv": ["date","closing_balance"],
    "fin_ar_aging_ms.csv": ["ar_id","due_date","amount_krw"],
    "fin_ap_aging_ms.csv": ["ap_id","payment_due_date","amount_krw","po_id"],
    "sc_purchase_orders_ms.csv": ["po_id","amount_krw","payment_due_date"]
}
def checksum_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
def check_file(path, required_cols):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='|')
        try:
            header = next(reader)
        except StopIteration:
            return False, "Empty file"
    missing = [c for c in required_cols if c not in header]
    if missing:
        return False, f"Missing columns: {missing}"
    return True, None
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    original = Path(args.dir)
    results = Path(args.out)
    results.mkdir(parents=True, exist_ok=True)
    log = []
    error = False
    for fname, cols in MAPPINGS.items():
        fpath = original / fname
        if not fpath.exists():
            log.append({"file": fname, "status": "missing", "msg": f"Missing file: {fname}"})
            error = True
            continue
        ok, err = check_file(fpath, cols)
        chk = checksum_file(fpath)
        if not ok:
            log.append({"file": fname, "status": "invalid", "msg": err, "sha256": chk})
            error = True
        else:
            log.append({"file": fname, "status": "ok", "sha256": chk})
    outp = results / "validation_report.json"
    with open(outp, "w", encoding='utf-8') as fw:
        json.dump({"report": log}, fw, ensure_ascii=False, indent=2)
    if error:
        print("Validation failed. See", outp)
        sys.exit(4)
    print("Validation passed. See", outp)
    sys.exit(0)

if __name__ == "__main__":
    main()
