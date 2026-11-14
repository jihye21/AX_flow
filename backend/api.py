# backend/api.py
from flask import Flask, request, jsonify, send_from_directory
import os, uuid, subprocess, threading, json, datetime, functools, csv, fcntl, time
from datetime import datetime, timezone

try:
    from llm_wrapper import generate_recommendations
except ImportError:
    from backend.llm_wrapper import generate_recommendations

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
RUNS_DIR = os.path.join(APP_ROOT, "..", "runs")
FRONTEND_DIR = os.path.join(APP_ROOT, "..", "frontend")
BASE_RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runs"))
os.makedirs(RUNS_DIR, exist_ok=True)

def determine_required_approvers(run_dir):
    required = ["purchase_lead"]
    summary_path = os.path.join(run_dir, "summary.json")
    if not os.path.isfile(summary_path):
        return required
    try:
        with open(summary_path, "r", encoding="utf-8") as fh:
            s = json.load(fh)
        # 격상 예: shortfall_count > 0 또는 shortfalls_sample 내 covenant 값이 임계치 미만
        if s.get("shortfall_count", 0) > 0:
            return ["group_ceo"]
        for item in s.get("shortfalls_sample", []):
            # item 형식: [date, metric, value]
            try:
                metric = str(item[1]).upper()
                val = int(item[2])
                if "COVENANT" in metric and val < 3000000000:
                    return ["group_ceo"]
            except Exception:
                continue
    except Exception:
        pass
    return required

app = Flask(__name__)
RUNS = {}

def map_user_to_role(user_name):
    mapping = {"alice":"purchase_lead", "bob":"finance_lead", "ceo":"group_ceo", "demo_user":"purchase_lead"}
    return mapping.get(user_name, "unknown")

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
    
    now = datetime.now(timezone.utc).isoformat()
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
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        # 개발용: 토큰 검사 비활성화
        return f(*a, **kw)
    return wrapper

def decision_file_path(run_id):
    d = os.path.join(BASE_RUNS_DIR, run_id)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "decision.json")

@app.route("/api/runs/<run_id>/decision", methods=["POST"])
@require_token
def run_decision(run_id):
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    role = payload.get("role")
    comment = payload.get("comment", "")
    actor = payload.get("actor", request.headers.get("X-User", "ui-user"))

    # 기본 검증
    if decision not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "decision must be APPROVED or REJECTED"}), 400
    if not role:
        return jsonify({"error": "role required"}), 400

    # run dir 확인
    run_dir = os.path.join(BASE_RUNS_DIR, run_id)
    if not os.path.isdir(run_dir):
        return jsonify({"error": "run not found"}), 404

    dec_path = decision_file_path(run_id)

    # decision.json이 없으면 summary 기반으로 required_approvers 초기화
    if not os.path.isfile(dec_path):
        required = determine_required_approvers(run_dir)
        doc_init = {"required_approvers": required, "approvals": [], "audit": []}
        with open(dec_path, "w", encoding="utf-8") as fh:
            json.dump(doc_init, fh, indent=2, ensure_ascii=False)

    # load decision doc
    try:
        with open(dec_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        doc = {"required_approvers": [], "approvals": [], "audit": []}

    required_roles = doc.get("required_approvers", [])

    # 권한 체크: role이 required_roles에 있어야 승인 처리 허용
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if role not in required_roles:
        # forbidden: approvals에는 추가하지 말고 audit에 기록만 남김
        doc.setdefault("audit", []).append({
            "actor": actor,
            "action": "forbidden_attempt",
            "detail": {"role": role},
            "at": now
        })
        # save doc (atomic)
        tmp = dec_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as tf:
            json.dump(doc, tf, indent=2, ensure_ascii=False)
            tf.flush(); os.fsync(tf.fileno())
        os.replace(tmp, dec_path)
        return jsonify({"error": "forbidden", "reason": "role not allowed for this run"}), 403

    # 승인/반려 처리: 허용된 role만 여기서 처리
    entry = {
        "id": uuid.uuid4().hex,
        "role": role,
        "actor": actor,
        "decision": decision,
        "comment": comment,
        "at": now,
        "approved_via_ui": True
    }
    doc.setdefault("approvals", []).append(entry)
    doc.setdefault("audit", []).append({"actor": actor, "action": "decision", "detail": entry, "at": now})

    # save decision.json atomically
    tmp = dec_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as tf:
        json.dump(doc, tf, indent=2, ensure_ascii=False)
        tf.flush(); os.fsync(tf.fileno())
    os.replace(tmp, dec_path)

    # 상태 판정(파일 기반 approvals로만 판정)
    required_roles = doc.get("required_approvers", [])
    def role_is_approved(r):
        return any(a.get("role") == r and a.get("decision") == "APPROVED" for a in doc.get("approvals", []))
    all_approved = all(role_is_approved(r) for r in required_roles)

    run = RUNS.setdefault(run_id, {})
    run.setdefault("approval_state", {})
    run["approval_state"].setdefault("approvals", {})
    run["approval_state"]["approvals"][role] = {"status": decision, "actor": actor, "at": now, "comment": comment}
    run["status"] = "APPROVED" if all_approved else ("PARTIALLY_APPROVED" if any(a.get("decision") == "APPROVED" for a in doc.get("approvals", [])) else "PENDING")

    # run metadata update
    meta_path = os.path.join(run_dir, "run_metadata.json")
    try:
        meta = json.load(open(meta_path, "r", encoding="utf-8"))
    except Exception:
        meta = {}
    meta.setdefault("decisions", []).append(entry)
    meta["last_decision_at"] = now
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)

    return jsonify({"ok": True, "entry": entry, "run_status": run["status"]}), 200
    
@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)