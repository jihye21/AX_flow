# backend/api.py
from flask import Flask, request, jsonify, send_from_directory
import os, uuid, subprocess, threading, json, datetime

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
RUNS_DIR = os.path.join(APP_ROOT, "..", "runs")
FRONTEND_DIR = os.path.join(APP_ROOT, "..", "frontend")
os.makedirs(RUNS_DIR, exist_ok=True)

app = Flask(__name__)

# simple in-memory run store (for MVP). For production use DB.
RUNS = {}

def run_worker(run_id, demand_path, scenario):
    run = RUNS[run_id]
    outdir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(outdir, exist_ok=True)
    # call the run script
    cmd = ["python3", os.path.join(APP_ROOT,"..","tools","run_simulation.py"),
           "--demand", demand_path, "--scenario", scenario, "--out", outdir]
    # run and capture returncode
    rc = subprocess.call(cmd)
    run['returncode'] = rc
    run['finished_at'] = datetime.datetime.utcnow().isoformat()+"Z"
    run['status'] = "COMPLETED" if rc==0 else "FAILED"
    # load summary if exists
    summary_path = os.path.join(outdir,"summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path) as fh:
            run['summary'] = json.load(fh)

@app.route("/api/campaigns", methods=["POST"])
def upload_campaign():
    # expects multipart/form-data with 'demand_file' and optional 'metadata'
    f = request.files.get("demand_file")
    if not f:
        return jsonify({"error":"missing demand_file"}), 400
    campaign_name = request.form.get("campaign_name","campaign-"+uuid.uuid4().hex[:6])
    fname = f"{campaign_name}_{uuid.uuid4().hex[:6]}.csv"
    saved = os.path.join(RUNS_DIR, fname)
    f.save(saved)
    return jsonify({"campaign_name": campaign_name, "file": fname}), 201

@app.route("/api/runs", methods=["POST"])
def start_run():
    data = request.get_json() or {}
    demand_file = data.get("demand_file")  # relative filename under runs dir or absolute path
    scenario = data.get("scenario","base")
    if not demand_file:
        return jsonify({"error":"demand_file required"}), 400
    # support relative stored in RUNS_DIR
    if not os.path.isabs(demand_file):
        demand_path = os.path.join(RUNS_DIR, demand_file)
    else:
        demand_path = demand_file
    if not os.path.isfile(demand_path):
        return jsonify({"error":"demand_file not found", "path": demand_path}), 404
    run_id = "run-"+uuid.uuid4().hex[:8]
    RUNS[run_id] = {"id":run_id, "demand_file":demand_path, "scenario":scenario, "status":"QUEUED", "created_at":datetime.datetime.utcnow().isoformat()+"Z"}
    # start background thread
    t = threading.Thread(target=run_worker, args=(run_id, demand_path, scenario), daemon=True)
    t.start()
    return jsonify({"run_id": run_id, "status":"QUEUED"}), 202

@app.route("/api/runs/<run_id>", methods=["GET"])
def get_run(run_id):
    run = RUNS.get(run_id)
    if not run:
        return jsonify({"error":"not found"}), 404
    return jsonify(run)

@app.route("/artifacts/<run_id>/<path:filename>", methods=["GET"])
def get_artifact(run_id, filename):
    outdir = os.path.join(RUNS_DIR, run_id)
    if not os.path.isdir(outdir):
        return jsonify({"error":"run not found"}), 404
    return send_from_directory(outdir, filename, as_attachment=True)

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)