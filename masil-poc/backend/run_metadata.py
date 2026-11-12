#!/usr/bin/env python3
import argparse,json,os,uuid,csv
from datetime import datetime
def read_assumptions(path):
    if not path or not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.reader(f, delimiter='|'):
            if len(r) >= 2:
                out[r[0]] = r[1]
    return out
def write_meta(outdir, meta):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "run_metadata.json")
    with open(path, "w", encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("Wrote metadata to", path)
def load_meta(outdir):
    path = os.path.join(outdir, "run_metadata.json")
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--assumptions")
    parser.add_argument("--out", required=True)
    parser.add_argument("--update-finish", action="store_true")
    args = parser.parse_args()
    if args.update_finish:
        meta = load_meta(args.out)
        if not meta:
            print("No metadata found to update.")
            return
        meta['finished_at'] = datetime.utcnow().isoformat() + "Z"
        write_meta(args.out, meta)
        return
    run_id = str(uuid.uuid4())
    started_at = datetime.utcnow().isoformat() + "Z"
    assumptions = read_assumptions(args.assumptions) if args.assumptions else {}
    meta = {
        "run_id": run_id,
        "scenario": args.scenario,
        "started_at": started_at,
        "finished_at": None,
        "assumptions": assumptions,
        "git_commit": None,
        "platform": "linux_codespace_poc",
        "notes": "PoC run metadata"
    }
    write_meta(args.out, meta)

if __name__ == "__main__":
    main()
