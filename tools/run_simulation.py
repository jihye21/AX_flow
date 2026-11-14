#!/usr/bin/env python3
# tools/run_simulation.py
# Usage example:
# python3 tools/run_simulation.py --demand campaign_demand_base.csv --scenario base --out runs/run_20261114_test

import argparse, csv, hashlib, json, os, re, subprocess, sys, datetime, shutil

REQ_COLS = ["campaign_id","start_date","end_date","sku"]
NUM_COLS = ["expected_daily_orders"]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def validate_csv(path):
    problems = []
    with open(path, newline='') as fh:
        rdr = csv.DictReader(fh)
        # check columns
        for c in REQ_COLS:
            if c not in rdr.fieldnames:
                problems.append(f"missing column: {c}")
        # row checks
        for i,row in enumerate(rdr, start=1):
            for c in REQ_COLS:
                if not row.get(c):
                    problems.append(f"row {i}: empty {c}")
            # date format
            sd = row.get("start_date","")
            ed = row.get("end_date","")
            if sd and not DATE_RE.match(sd):
                problems.append(f"row {i}: bad start_date {sd}")
            if ed and not DATE_RE.match(ed):
                problems.append(f"row {i}: bad end_date {ed}")
            # numeric
            for n in NUM_COLS:
                v = row.get(n)
                if v is None or v=="":
                    problems.append(f"row {i}: empty numeric {n}")
                else:
                    try:
                        if int(float(v)) < 0:
                            problems.append(f"row {i}: negative {n}")
                    except:
                        problems.append(f"row {i}: non-numeric {n}={v}")
    return problems

def run_simulator(sim_cmd, env=None):
    # sim_cmd: list
    p = subprocess.Popen(sim_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    out_lines = []
    for line in p.stdout:
        print(line, end="")  # live log
        out_lines.append(line)
    p.wait()
    return p.returncode, "".join(out_lines)

def check_outputs(outdir):
    # checks for typical artifacts; adapt names as needed
    required = ["full_cash_projection.csv", "manifest.json", "validation_report.json"]
    missing = []
    for r in required:
        if not os.path.isfile(os.path.join(outdir, r)):
            missing.append(r)
    # quick content check for projection shortfalls
    shortfalls = []
    proj_path = os.path.join(outdir, "full_cash_projection.csv")
    if os.path.isfile(proj_path):
        with open(proj_path, newline='') as fh:
            rdr = csv.DictReader(fh)
            for row in rdr:
                try:
                    if int(float(row.get("projected_shortfall",0)))>0:
                        shortfalls.append((row.get("date"), row.get("sku"), row.get("projected_shortfall")))
                except:
                    pass
    return missing, shortfalls

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", required=True)
    ap.add_argument("--scenario", default="base")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sim-cmd", default="python3 masil-poc/backend/cash_simulator.py")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--noop-mock-replies", action="store_true", help="if set, simulator will treat supplier replies as mocked (if simulator supports)")
    args = ap.parse_args()

    demand = args.demand
    outdir = args.out
    sim_cmd_template = args.sim_cmd.split()

    os.makedirs(outdir, exist_ok=True)
    meta = {
        "demand_file": os.path.abspath(demand),
        "demand_hash": file_hash(demand),
        "scenario": args.scenario,
        "started_at": datetime.datetime.utcnow().isoformat()+"Z",
        "cwd": os.getcwd()
    }
    with open(os.path.join(outdir, "run_metadata.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    # 1. validate CSV
    problems = validate_csv(demand)
    if problems:
        print("VALIDATION FAILED:", problems, file=sys.stderr)
        with open(os.path.join(outdir, "validation_errors.txt"), "w") as fh:
            fh.write("\n".join(problems))
        sys.exit(2)
    print("CSV validation passed")

    # 2. prepare sim command
    sim_cmd = sim_cmd_template + ["--data", "masil-poc/original", "--out", outdir, "--scenario", args.scenario]

    if args.noop_mock_replies:
        sim_cmd += ["--mock-replies"]
    print("Running simulator:", " ".join(sim_cmd))

    # 3. run simulator
    rc, logs = run_simulator(sim_cmd)
    with open(os.path.join(outdir, "simulator.log"), "w") as fh:
        fh.write(logs)

    if rc != 0:
        print(f"Simulator failed with rc={rc}", file=sys.stderr)
        sys.exit(3)

    # 4. check outputs
    missing, shortfalls = check_outputs(outdir)
    summary = {
        "missing_artifacts": missing,
        "shortfall_count": len(shortfalls),
        "shortfalls_sample": shortfalls[:10],
        "finished_at": datetime.datetime.utcnow().isoformat()+"Z"
    }
    with open(os.path.join(outdir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    # write markdown summary
    with open(os.path.join(outdir, "summary.md"), "w") as fh:
        fh.write("# Run summary\n\n")
        fh.write(json.dumps(summary, indent=2))

    if missing:
        print("Missing artifacts:", missing, file=sys.stderr)
        sys.exit(4)
    print("Simulation finished OK. Shortfalls:", summary["shortfall_count"])
    sys.exit(0)

if __name__ == "__main__":
    main()