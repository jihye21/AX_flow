# backend/api.py
from flask import Flask, request, jsonify, send_from_directory
import os, uuid, subprocess, threading, json, datetime, functools, csv

try:
    from llm_wrapper import generate_recommendations
except ImportError:
    from backend.llm_wrapper import generate_recommendations

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
RUNS_DIR = os.path.join(APP_ROOT, "..", "runs")
FRONTEND_DIR = os.path.join(APP_ROOT, "..", "frontend")
os.makedirs(RUNS_DIR, exist_ok=True)

app = Flask(__name__)
RUNS = {}

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def run_worker(run_id, demand_path, scenario):
    run = RUNS[run_id]
    outdir = os.path.join(RUNS_DIR, run_id)
    ensure_dir(outdir)
    
    cmd = [
        "python3",
        os.path.join(APP_ROOT, "..", "tools", "run_simulation.py"),
        "--demand", demand_path,
        "--scenario", scenario,
        "--out", outdir
    ]
    rc = subprocess.call(cmd)
    
    now = datetime.datetime.utcnow().isoformat() + "Z"
    run['returncode'] = rc
    run['finished_at'] = now
    
    if rc == 0:
        run['status'] = "NEEDS_APPROVAL"
        run['approval_state'] = {
            "rule": "1억 원 이상 현금 변동/PO 조정 건 (구매팀장 + 재무팀장 2인 필수 승인)",
            "required_roles": ["purchase_lead", "finance_lead"],
            "approvals": {
                "purchase_lead": {"status": "PENDING", "actor": None, "at": None, "comment": ""},
                "finance_lead": {"status": "PENDING", "actor": None, "at": None, "comment": ""}
            }
        }
        run['notifications'] = [
            {
                "channel": "Slack (#ops-alert)",
                "recipient": "@구매팀장 @재무팀장",
                "message": f"[{run_id}] 시뮬레이션({scenario}) 완료. 결재 승인이 필요합니다.",
                "sent_at": now
            },
            {
                "channel": "Email",
                "recipient": "purchase_lead@company.com, finance_lead@company.com",
                "message": f"[긴급결재요청] Run {run_id} 검토 및 승인 요청",
                "sent_at": now
            }
        ]
    else:
        run['status'] = "FAILED"
    
    summary_path = os.path.join(outdir, "summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path, encoding='utf-8') as fh:
            summary_data = json.load(fh)
            run['summary'] = summary_data

        domain_chk = summary_data.get("domain_constraint_check", {})
        if domain_chk.get("status") == "VIOLATED":
            run['status'] = "BLOCKED_BY_DOMAIN_RULE"
            run['notifications'].append({
                "channel": "Slack (#qa-quality & #sales-vip)",
                "recipient": "@품질보증팀 @영업팀 @구매팀장",
                "message": f"[{run_id}] ⛔ 도메인 제약 위반 감지! {domain_chk.get('reason')} (대상: {', '.join(domain_chk.get('blocked_pos', []))})",
                "sent_at": now
            })

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
        
    outdir = os.path.join(RUNS_DIR, run_id)
    decision_path = os.path.join(outdir, "decision.json")
    if os.path.isfile(decision_path):
        with open(decision_path, "r", encoding="utf-8") as fh:
            run["decision_log"] = json.load(fh)
            
    replan_summary = os.path.join(outdir, "replan_run", "summary.json")
    if os.path.isfile(replan_summary):
        with open(replan_summary, "r", encoding="utf-8") as fh:
            run["replan_summary"] = json.load(fh)
            
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
    role = payload.get("role") or request.headers.get("X-Role", "unknown")
    actor = request.headers.get("X-User", role)
    
    if decision not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "decision must be APPROVED or REJECTED"}), 400
    if role not in ("purchase_lead", "finance_lead"):
        return jsonify({"error": f"권한 없음: '{role}' 역할은 결재 권한이 없습니다."}), 403

    now = datetime.datetime.utcnow().isoformat() + "Z"
    entry = {
        "id": uuid.uuid4().hex,
        "role": role,
        "actor": actor,
        "decision": decision,
        "comment": comment,
        "at": now
    }

    path = decision_file_path(run_id)
    if os.path.isfile(path):
        with open(path, "r", encoding='utf-8') as fh:
            doc = json.load(fh)
    else:
        doc = {"approvals": [], "audit": []}
    doc["approvals"].append(entry)
    doc["audit"].append({"actor": actor, "role": role, "action": "decision", "detail": entry, "at": now})
    with open(path, "w", encoding='utf-8') as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    run = RUNS.get(run_id)
    if run and "approval_state" in run:
        app_state = run["approval_state"]
        app_state["approvals"][role] = {
            "status": decision,
            "actor": actor,
            "at": now,
            "comment": comment
        }
        run["last_decision"] = entry
        run.setdefault("notifications", [])

        if decision == "REJECTED":
            run["status"] = "REJECTED_REPLANNING"
            run["notifications"].append({
                "channel": "Slack (#ops-alert)",
                "recipient": "@마케팅팀 @구매팀장 @재무팀장",
                "message": f"[{run_id}] {role} 반려(REJECTED) 처리됨. 캠페인 30% 축소 플랜 B 자동 재계산 시작.",
                "sent_at": now
            })
        else:
            all_approved = all(
                v["status"] == "APPROVED" for v in app_state["approvals"].values()
            )
            if all_approved:
                run["status"] = "APPROVED"
                run["erp_sync"] = {
                    "status": "COMMITTED (MOCK)",
                    "idempotency_key": f"erp-{run_id}-{uuid.uuid4().hex[:6]}",
                    "synced_at": now
                }
                run["notifications"].append({
                    "channel": "Slack (#erp-sync) & Email",
                    "recipient": "@ERP담당자 @구매팀 @재무팀",
                    "message": f"[{run_id}] 최종 다중 승인(2/2) 완료! ERP 반영 트랜잭션 전송됨.",
                    "sent_at": now
                })
            else:
                run["status"] = "PARTIALLY_APPROVED"
                next_role = "재무팀장(finance_lead)" if role == "purchase_lead" else "구매팀장(purchase_lead)"
                run["notifications"].append({
                    "channel": "Slack (#ops-alert)",
                    "recipient": f"@{next_role}",
                    "message": f"[{run_id}] 1차 승인({role}) 완료. 다음 결재자({next_role}) 승인 대기 중.",
                    "sent_at": now
                })

    if decision == "REJECTED":
        run_dir = os.path.join(RUNS_DIR, run_id)
        demand = run.get("demand_file") if run else None
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

    return jsonify({"ok": True, "entry": entry, "status": run["status"] if run else "RECORDED"}), 200

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)