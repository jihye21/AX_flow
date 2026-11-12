#!/usr/bin/env python3
# update_run_metadata_finish.py
# Usage:
#   python3 update_run_metadata_finish.py --file results/<run_id>/run_metadata.json
#   python3 update_run_metadata_finish.py --file results/<run_id>/run_metadata.json --timestamp 2026-11-12T05:54:21Z

import argparse, json, os
from datetime import datetime, timezone

def iso_now_utc():
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace('+00:00','Z')

def main():
    p = argparse.ArgumentParser(description="Update run_metadata.json finished_at field")
    p.add_argument("--file", "-f", required=True, help="path to run_metadata.json")
    p.add_argument("--timestamp", "-t", required=False, help="ISO8601 timestamp to set (e.g. 2026-11-12T05:54:21Z). If omitted, uses current UTC time.")
    args = p.parse_args()

    path = args.file
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}")
        return 2

    with open(path, "r", encoding="utf-8") as rf:
        try:
            meta = json.load(rf)
        except Exception as e:
            print(f"Error: failed to parse JSON: {e}")
            return 3

    ts = args.timestamp if args.timestamp else iso_now_utc()
    meta['finished_at'] = ts

    # write back (atomic write recommended)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as wf:
        json.dump(meta, wf, ensure_ascii=False, indent=2)
        wf.write("\n")
    os.replace(tmp, path)
    print(f"Updated finished_at -> {ts} in {path}")
    return 0

if __name__ == "__main__":
    exit(main())