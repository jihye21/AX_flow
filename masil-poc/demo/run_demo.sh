#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# default scenario
SCENARIO="${1:-base}"
RUN_RESULTS_DIR="${REPO_ROOT}/results"
# validate inputs
python3 "${REPO_ROOT}/backend/validate_files.py" --dir "${REPO_ROOT}/original" --out "${RUN_RESULTS_DIR}" || (echo "Validation failed" && exit 4)
# generate run metadata (creates results/run_metadata.json)
python3 "${REPO_ROOT}/backend/run_metadata.py" --scenario "${SCENARIO}" --assumptions "${REPO_ROOT}/inputs/assumptions.csv" --out "${RUN_RESULTS_DIR}"
RUN_ID="$(python3 -c "import json,sys; print(json.load(open('${RUN_RESULTS_DIR}/run_metadata.json'))['run_id'])")"
RUN_OUT="${RUN_RESULTS_DIR}/${RUN_ID}"
rm -rf "${RUN_OUT}"
mkdir -p "${RUN_OUT}"
# run simulator and generators targeting run folder
python3 "${REPO_ROOT}/backend/cash_simulator.py" --scenario "${SCENARIO}" --out "${RUN_OUT}" --data "${REPO_ROOT}/original"
python3 "${REPO_ROOT}/backend/generate_approvals.py" --data "${REPO_ROOT}/original" --proj "${RUN_OUT}/full_cash_projection.csv" --out "${RUN_OUT}"
python3 "${REPO_ROOT}/backend/generate_report.py" --proj "${RUN_OUT}/full_cash_projection.csv" --out "${RUN_OUT}"
# copy validation and metadata for audit trace
cp "${RUN_RESULTS_DIR}/validation_report.json" "${RUN_OUT}/" 2>/dev/null || true
cp "${RUN_RESULTS_DIR}/run_metadata.json" "${RUN_OUT}/"
# create manifest (sha256) for run folder
python3 - <<'PY'
import os,sys,hashlib,json
run_out=sys.argv[1]
manifest={}
for root,_,files in os.walk(run_out):
    for f in sorted(files):
        p=os.path.join(root,f)
        with open(p,'rb') as fh:
            h=hashlib.sha256(fh.read()).hexdigest()
        manifest[os.path.relpath(p,run_out)]=h
print(json.dumps(manifest,indent=2,ensure_ascii=False))
with open(os.path.join(run_out,'manifest.json'),'w',encoding='utf-8') as fo:
    json.dump(manifest,fo,ensure_ascii=False,indent=2)
PY "${RUN_OUT}"
# zip run folder
ZIP_NAME="poc_${RUN_ID}.zip"
rm -f "${ZIP_NAME}"
( cd "${RUN_OUT}" && zip -r "../${ZIP_NAME}" . )
echo "Created ${ZIP_NAME} in ${RUN_RESULTS_DIR}"
