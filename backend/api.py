# backend/api.py
from flask import Flask, request, jsonify, send_from_directory
import os, uuid, subprocess, threading, json, datetime, functools, csv

# llm_wrapper 연동 (같은 backend 폴더 내 위치)
try:
    from llm_wrapper import generate_recommendations
except ImportError:
    from backend.llm_wrapper import generate_recommendations

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
RUNS_DIR = os.path.join(APP_ROOT, "..", "runs")
FRONTEND_DIR = os.path.join(APP_ROOT, "..", "frontend")
os.makedirs(RUNS_DIR, exist_ok=True)

app = Flask(__name__)

# simple in-memory run store (for MVP). For production use DB.
RUNS = {}

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def run_worker(run_id, demand_path, scenario):
    run = RUNS[run_id]
    outdir = os.path.join(RUNS_DIR, run_id)
    ensure_dir(outdir)
    
    cmd = ["python3", os.path.join(APP_ROOT, "..", "tools", "run_simulation.py"),
           "--demand", demand_path, "--scenario", scenario, "--out", outdir]
    rc = subprocess.call(cmd)
    
    run['returncode'] = rc
    run['finished_at'] = datetime.datetime.utcnow().isoformat() + "Z"
    run['status'] = "COMPLETED" if rc == 0 else "FAILED"
    
    summary_path = os.path.join(outdir, "summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path, encoding='utf-8') as fh:
            run['summary'] = json.load(fh)
        # 시뮬레이션 성공 직후 AI 권고안(recommendations.json) 자동 생성
        try:
            run['recommendations'] = generate_recommendations(outdir)
        except Exception as e:
            run['recommendations_error'] = str(e)

@app.route("/api/campaigns", methods=["POST"])
def upload_campaign():
    f = request.files.get("demand_file")
    if not f:
        return jsonify({"error": "missing demand_file"}), 400
    campaign_name = request.form.get("campaign_name", "campaign-" + uuid.uuid4().hex[:6])
    fname = f"{campaign_name}_{uuid.uuid4().hex[:6]}.csv"
    saved = os.path.join(RUNS_DIR, fname)
    f.save(saved)
    return jsonify({"campaign_name": campaign_name, "file": fname}), 201

@app.route("/api/runs", methods=["POST"])
def start_run():
    data = request.get_json() or {}
    demand_file = data.get("demand_file")
    scenario = data.get("scenario", "base")
    if not demand_file:
        return jsonify({"error": "demand_file required"}), 400
        
    demand_path = demand_file if os.path.isabs(demand_file) else os.path.join(RUNS_DIR, demand_file)
    if not os.path.isfile(demand_path):
        return jsonify({"error": "demand_file not found", "path": demand_path}), 404
        
    run_id = "run-" + uuid.uuid4().hex[:8]
    RUNS[run_id] = {
        "id": run_id,
        "demand_file": demand_path,
        "scenario": scenario,
        "status": "QUEUED",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z"
    }
    t = threading.Thread(target=run_worker, args=(run_id, demand_path, scenario), daemon=True)
    t.start()
    return jsonify({"run_id": run_id, "status": "QUEUED"}), 202

@app.route("/api/runs/<run_id>", methods=["GET"])
def get_run(run_id):
    run = RUNS.get(run_id)
    if not run:
        return jsonify({"error": "not found"}), 404
    return jsonify(run)

@app.route("/artifacts/<run_id>/<path:filename>", methods=["GET"])
def get_artifact(run_id, filename):
    outdir = os.path.join(RUNS_DIR, run_id)
    if not os.path.isdir(outdir):
        return jsonify({"error": "run not found"}), 404
    return send_from_directory(outdir, filename, as_attachment=True)

def require_token(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        token = request.headers.get("X-Auth-Token") or request.args.get("token")
        if not token:
            return jsonify({"error": "missing token"}), 401
        return f(*a, **kw)
    return wrapper

def decision_file_path(run_id):
    d = os.path.join(RUNS_DIR, run_id)
    ensure_dir(d)
    return os.path.join(d, "decision.json")

@app.route("/api/runs/<run_id>/decision", methods=["POST"])
@require_token
def run_decision(run_id):
    payload = request.get_json() or {}
    decision = payload.get("decision")
    comment = payload.get("comment", "")
    actor = request.headers.get("X-User", "unknown")
    if decision not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "decision must be APPROVED or REJECTED"}), 400

    path = decision_file_path(run_id)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    entry = {
        "id": uuid.uuid4().hex,
        "actor": actor,
        "decision": decision,
        "comment": comment,
        "at": now
    }
    
    if os.path.isfile(path):
        with open(path, "r", encoding='utf-8') as fh:
            doc = json.load(fh)
    else:
        doc = {"approvals": [], "audit": []}
    doc["approvals"].append(entry)
    doc["audit"].append({"actor": actor, "action": "decision", "detail": entry, "at": now})
    with open(path, "w", encoding='utf-8') as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    # 메모리(RUNS) 상태 동기화
    if run_id in RUNS:
        RUNS[run_id]["status"] = "APPROVED" if decision == "APPROVED" else "REJECTED_REPLANNING"
        RUNS[run_id]["last_decision"] = entry

    run_dir = os.path.join(RUNS_DIR, run_id)
    meta_path = os.path.join(run_dir, "run_metadata.json")
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding='utf-8') as fh:
            rmeta = json.load(fh)
    else:
        rmeta = {}
    rmeta.setdefault("decisions", []).append(entry)
    rmeta["last_decision_at"] = now
    with open(meta_path, "w", encoding='utf-8') as fh:
        json.dump(rmeta, fh, indent=2, ensure_ascii=False)

    # 거절(REJECTED) 시 30% 축소 수요 CSV 자동 생성 및 재시뮬레이션 트리거
    if decision == "REJECTED":
        demand = rmeta.get("demand_file") or (RUNS[run_id].get("demand_file") if run_id in RUNS else None)
        if demand and os.path.isfile(demand):
            red_path = os.path.join(run_dir, "demand_reduced_30.csv")
            with open(demand, newline='', encoding='utf-8') as inf, open(red_path, 'w', newline='', encoding='utf-8') as outf:
                rdr = csv.reader(inf)
                w = csv.writer(outf)
                header = next(rdr)
                w.writerow(header)
                try:
                    idx = [h.lower() for h in header].index('expected_daily_orders')
                except ValueError:
                    idx = None
                for r in rdr:
                    if idx is not None and len(r) > idx and r[idx].strip() != "":
                        try:
                            v = int(float(r[idx]))
                            r[idx] = str(int(v * 0.7))
                        except Exception:
                            pass
                    w.writerow(r)
            outdir = os.path.join(run_dir, "replan_run")
            ensure_dir(outdir)
            script_path = os.path.join(APP_ROOT, "..", "tools", "run_simulation.py")
            cmd = ["python3", script_path, "--demand", red_path, "--scenario", "conservative", "--out", outdir]
            subprocess.Popen(cmd)
            
    return jsonify({"ok": True, "entry": entry}), 200

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
