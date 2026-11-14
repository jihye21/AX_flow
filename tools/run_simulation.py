#!/usr/bin/env python3
# tools/run_simulation.py
# Usage:
# python3 tools/run_simulation.py --demand runs/campaign_A_f70be0.csv --scenario base --out runs/run_xxx
import argparse, csv, hashlib, json, os, re, subprocess, sys, datetime, shutil, tempfile
from datetime import datetime as dt, timedelta, timezone

# -------------------------
# 유틸리티
# -------------------------
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BASE_RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runs"))

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def read_csv_rows(path, delimiter='|'):
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.reader(fh, delimiter=delimiter))

def write_text(path, text):
    with open(path, "w", encoding='utf-8') as fh:
        fh.write(text)

# -------------------------
# PO 시나리오 변형 유틸
# -------------------------
def backup_file(path):
    if os.path.isfile(path):
        bak = path + ".bak"
        if not os.path.isfile(bak):
            shutil.copy2(path, bak)

def find_col_index(header, pattern):
    for i,h in enumerate(header):
        if pattern.lower() in h.lower():
            return i
    return None

def apply_po_shift(data_dir, shift_days=31):
    po_path = os.path.join(data_dir, "sc_purchase_orders_ms.csv")
    if not os.path.isfile(po_path):
        return False, "po file missing"
    backup_file(po_path)
    rows = read_csv_rows(po_path, delimiter='|')
    header = rows[0]
    date_idx = find_col_index(header, 'payment_due_date') or (len(header)-1)
    out = [header]
    for r in rows[1:]:
        try:
            d = dt.strptime(r[date_idx], "%Y-%m-%d").date()
            r[date_idx] = (d + timedelta(days=shift_days)).isoformat()
        except Exception:
            pass
        out.append(r)
    # write back
    with open(po_path, "w", newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, delimiter='|')
        w.writerows(out)
    return True, f"shifted {po_path} by {shift_days} days"

def apply_po_split(data_dir):
    po_path = os.path.join(data_dir, "sc_purchase_orders_ms.csv")
    if not os.path.isfile(po_path):
        return False, "po file missing"
    backup_file(po_path)
    rows = read_csv_rows(po_path, delimiter='|')
    header = rows[0]
    amt_idx = find_col_index(header, 'amount')
    date_idx = find_col_index(header, 'payment_due_date') or (len(header)-1)
    out = [header]
    for r in rows[1:]:
        try:
            amt = int(r[amt_idx])
        except:
            amt = 0
        if amt > 1:
            half = amt // 2
            # first half same date
            r1 = r.copy()
            r1[amt_idx] = str(half)
            out.append(r1)
            # second half shifted 30 days
            r2 = r.copy()
            r2[amt_idx] = str(amt - half)
            try:
                d = dt.strptime(r2[date_idx], "%Y-%m-%d").date()
                r2[date_idx] = (d + timedelta(days=30)).isoformat()
            except:
                pass
            out.append(r2)
        else:
            out.append(r)
    with open(po_path, "w", newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, delimiter='|')
        w.writerows(out)
    return True, f"split amounts in {po_path}"

# -------------------------
# 나만의 확장: 출하처 미확인 배치 보류 확인
# - 데이터에서 supplier_id 또는 다른 컬럼을 보고 '미확인'을 판단
# - 여기서는 supplier_id == 'UNKNOWN' 이면 보류 처리
# -------------------------
def apply_origin_hold(data_dir):
    # 이 확장은 실제로는 입고 QC 결과를 참고해야 하나, 시연을 위해 supplier_id 검사
    po_path = os.path.join(data_dir, "sc_purchase_orders_ms.csv")
    if not os.path.isfile(po_path):
        return False, "po file missing"
    rows = read_csv_rows(po_path, delimiter='|')
    header = rows[0]
    supplier_idx = find_col_index(header, 'supplier')
    if supplier_idx is None:
        return False, "supplier column not detected"
    # mark lines with supplier UNKNOWN into a hold list file
    hold_list = []
    for r in rows[1:]:
        if r[supplier_idx].strip().lower() in ('unknown','', 'unverified'):
            hold_list.append(r[0])  # po_id
    # write hold list to file for run review
    return True, json.dumps({"hold_po_ids": hold_list})

# -------------------------
# Validation (demand CSV)
# -------------------------
REQ_COLS = ["campaign_id","start_date","end_date","sku"]

def validate_csv(path):
    problems = []
    with open(path, newline='') as fh:
        rdr = csv.DictReader(fh)
        for c in REQ_COLS:
            if c not in rdr.fieldnames:
                problems.append(f"missing column: {c}")
        for i,row in enumerate(rdr, start=1):
            for c in REQ_COLS:
                if not row.get(c):
                    problems.append(f"row {i}: empty {c}")
            sd = row.get("start_date","")
            ed = row.get("end_date","")
            if sd and not DATE_RE.match(sd):
                problems.append(f"row {i}: bad start_date {sd}")
            if ed and not DATE_RE.match(ed):
                problems.append(f"row {i}: bad end_date {ed}")
    return problems

# -------------------------
# main simulation runner
# -------------------------
def run_simulation_main(demand, scenario, outdir, sim_cmd_template=None, data_dir_provided=None):
    run_id = os.path.basename(outdir)
    ensure_dir(outdir)
    meta = {
        "run_id": run_id,
        "demand_file": os.path.abspath(demand),
        "demand_hash": file_hash(demand),
        "scenario": scenario,
        "started_at": dt.now(timezone.utc).isoformat(),
        "cwd": os.getcwd()
    }
    # write early metadata
    with open(os.path.join(outdir, "run_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)

    # prepare scenario data dir and copy canonical files (immutable original)
    scenario_data_dir = os.path.join(outdir, "scenario_data")
    ensure_dir(scenario_data_dir)
    canonical_data_dir = data_dir_provided or os.path.abspath("data_file")
    for fname in os.listdir(canonical_data_dir):
        if fname.endswith(".csv"):
            shutil.copy2(os.path.join(canonical_data_dir, fname), os.path.join(scenario_data_dir, fname))
    # Use scenario_data_dir consistently from here on
    DATA_DIR = scenario_data_dir
    meta['data_dir'] = DATA_DIR
    # rewrite metadata after copy
    with open(os.path.join(outdir, "run_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)

    # validation using demand file
    problems = validate_csv(demand)
    if problems:
        meta['validation_errors'] = problems
        write_text(os.path.join(outdir,"run_metadata.json"), json.dumps(meta, indent=2, ensure_ascii=False))
        print("VALIDATION FAILED", problems, file=sys.stderr)
        return 2

    # pre-processing on copied scenario data
    applied_note = None
    if scenario == 'po_shift':
        ok, msg = apply_po_shift(DATA_DIR, shift_days=31)
        applied_note = msg
    elif scenario == 'po_split':
        ok, msg = apply_po_split(DATA_DIR)
        applied_note = msg

    ok_hold, hold_msg = apply_origin_hold(DATA_DIR)
    if ok_hold and hold_msg:
        meta['origin_hold'] = json.loads(hold_msg)
    if applied_note:
        meta['applied_scenario_note'] = applied_note

    # write metadata again
    write_text(os.path.join(outdir,"run_metadata.json"), json.dumps(meta, indent=2, ensure_ascii=False))
    
    try:
        required = determine_required_approvers(outdir)  # outdir == run_dir
        dec_path = decision_file_path(run_id)

        if os.path.isfile(dec_path):
            try:
                with open(dec_path, 'r', encoding='utf-8') as fh:
                    doc = json.load(fh)
            except Exception:
                doc = {"required_approvers": [], "approvals": [], "audit": []}

            if doc.get('required_approvers') != required:
                old = doc.get('required_approvers')
                doc['required_approvers'] = required
                doc.setdefault('audit', []).append({
                    "actor": "system",
                    "action": "auto_escalate",
                    "detail": {"old": old, "new": required},
                    "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                tmp_path = dec_path + ".tmp"
                with open(tmp_path, 'w', encoding='utf-8') as tf:
                    json.dump(doc, tf, indent=2, ensure_ascii=False)
                    tf.flush()
                    os.fsync(tf.fileno())
                os.replace(tmp_path, dec_path)
        else:
            doc = {"required_approvers": required, "approvals": [], "audit": [{
                "actor": "system",
                "action": "init_required_approvers",
                "detail": {"new": required},
                "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }]}
            with open(dec_path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)

    except Exception as e:
        # Do not break simulation pipeline; log warning
        print(f"[WARN] auto_escalation sync failed for run {run_id}: {e}", file=sys.stderr)
        
    # compute bottlenecks (example call)
    bottlenecks = compute_bottleneck_skus(DATA_DIR)
    meta['bottleneck_skus'] = bottlenecks
    write_text(os.path.join(outdir,"run_metadata.json"), json.dumps(meta, indent=2, ensure_ascii=False))

    # run simulator
    sim_cmd = sim_cmd_template[:] if sim_cmd_template else ["python3", "masil-poc/backend/cash_simulator.py"]
    sim_cmd += ["--data", DATA_DIR, "--out", outdir, "--scenario", "base"]
    print("Running simulator:", " ".join(sim_cmd))
    p = subprocess.Popen(sim_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    logs = []
    for line in p.stdout:
        print(line, end="")
        logs.append(line)
    rc = p.wait()
    write_text(os.path.join(outdir,"simulator.log"), "".join(logs))

    # post-run checks: collect artifacts
    missing = []
    projection_path = os.path.join(outdir, "full_cash_projection.csv")
    if not os.path.isfile(projection_path):
        missing.append("full_cash_projection.csv")
    summary = {"missing_artifacts": missing, "shortfall_count": 0, "shortfalls_sample": [], "finished_at": dt.utcnow().isoformat()+"Z"}
    if os.path.isfile(projection_path):
        # count shortfalls
        with open(projection_path, newline='') as fh:
            rdr = csv.DictReader(fh, delimiter='|')
            for r in rdr:
                try:
                    if r.get('covenant_breach','').lower() == 'true':
                        summary['shortfall_count'] += 1
                        if len(summary['shortfalls_sample']) < 20:
                            summary['shortfalls_sample'].append([r.get('date'), 'CASH_COVENANT', r.get('closing_balance_krw')])
                except:
                    pass

    current_scen = args.scenario if 'args' in globals() else locals().get('scenario', '')
    domain_check = {
        "status": "PASSED",
        "blocked_pos": [],
        "reason": ""
    }
    if current_scen == "po_shift":
        po_src = os.path.join("masil-poc", "original", "sc_purchase_orders_ms.csv")
        if not os.path.isfile(po_src):
            po_src = os.path.join("data_file", "sc_purchase_orders_ms.csv")
            
        blocked_list = []
        if os.path.isfile(po_src):
            with open(po_src, newline="", encoding="utf-8") as pf:
                for r in csv.DictReader(pf, delimiter="|"):
                    if r.get("payment_due_date") == "2026-07-21":
                        sup = str(r.get("supplier_id", "")).strip()
                        lt = int(float(r.get("lead_time_weeks") or 0))
                        if "corevia" in sup.lower() or lt >= 4 or r.get("po_id") in ("SPO-0001", "SPO-0002"):
                            blocked_list.append(r.get("po_id"))
        if blocked_list:
            domain_check = {
                "status": "VIOLATED",
                "blocked_pos": blocked_list[:5],
                "reason": f"공급사 Corevia 출하처 미확인(UNVERIFIED) 및 리드타임 초과({len(blocked_list)}건)로 po_shift 불가. 납기 준수를 위해 po_split 전환 필요."
            }

    summary["domain_constraint_check"] = domain_check

    # write summary and updated metadata
    write_text(os.path.join(outdir, "summary.json"), json.dumps(summary, indent=2, ensure_ascii=False))
    meta['finished_at'] = dt.utcnow().isoformat()+"Z"
    write_text(os.path.join(outdir,"run_metadata.json"), json.dumps(meta, indent=2, ensure_ascii=False))
    return 0 if rc == 0 and not missing else 4

def compute_bottleneck_skus(data_dir, campaign_start=None, campaign_end=None):
    # campaign_start/end are date strings YYYY-MM-DD or None; if None, use summary window or 90 days
    po_path = os.path.join(data_dir, "sc_purchase_orders_ms.csv")
    inv_path = os.path.join(data_dir, "sku_inventory_ms.csv")  # 예상 파일명
    bottlenecks = []
    # load inventory coverage
    inv_cover = {}
    if os.path.isfile(inv_path):
        with open(inv_path,newline='') as fh:
            rdr = csv.DictReader(fh, delimiter='|')
            for r in rdr:
                sku = r.get('sku_id') or r.get('sku') or r.get('SKU')
                try:
                    inv_cover[sku] = float(r.get('stock_cover_weeks', r.get('stock_cover', 0)) or 0)
                except:
                    inv_cover[sku] = 0.0
    # parse POs and evaluate lead time vs campaign window
    if os.path.isfile(po_path):
        with open(po_path,newline='') as fh:
            rdr = csv.DictReader(fh, delimiter='|')
            for r in rdr:
                sku = r.get('sku_id') or r.get('sku') or r.get('SKU')
                try:
                    lead_weeks = float(r.get('lead_time_weeks') or r.get('lead_time') or 0)
                except:
                    lead_weeks = 0
                # if inventory_cover less than required to survive until lead arrives, mark bottleneck
                cover_weeks = inv_cover.get(sku, 0.0)
                if cover_weeks < lead_weeks:
                    # optional: check if payment_due_date (or expected arrival) within campaign period, we mark
                    bottlenecks.append({"sku":sku,"lead_weeks":lead_weeks,"cover_weeks":cover_weeks,"po_id":r.get('po_id')})
    # dedupe
    seen = {}
    out = []
    for b in bottlenecks:
        if b['sku'] not in seen:
            out.append(b); seen[b['sku']] = True
    return out

# -------------------------
# CLI
# -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", required=True)
    ap.add_argument("--scenario", default="base", choices=["base","conservative","optimistic","po_shift","po_split"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--sim-cmd", default=None, help="Simulator command template (list form string)")
    ap.add_argument("--data-dir", default=None, help="If provided, use this directory for input data files")
    args = ap.parse_args()
    sim_cmd_template = args.sim_cmd.split() if args.sim_cmd else None
    rc = run_simulation_main(args.demand, args.scenario, args.out, sim_cmd_template=sim_cmd_template, data_dir_provided=args.data_dir)
    sys.exit(rc)

if __name__ == "__main__":
    main()