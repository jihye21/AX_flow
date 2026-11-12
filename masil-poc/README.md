Masil PoC (Linux / Codespace)
Requirements:
- Python 3.8+ (python3 in PATH)
- pip packages: pandas, matplotlib, reportlab
Quick start (Codespace / Linux):
1) chmod +x create_poc_zip.sh && ./create_poc_zip.sh
2) Unzip masil-poc.zip, cd masil-poc
3) python3 -m venv .venv && source .venv/bin/activate
4) pip install --upgrade pip
5) pip install pandas matplotlib reportlab
6) cd demo && ./run_demo.sh base
7) results/<run_id>/ 에 full_cash_projection.csv, approval_flags.csv, cash_projection.png, one_pager.pdf, manifest.json, run_metadata.json 등이 생성됩니다.
