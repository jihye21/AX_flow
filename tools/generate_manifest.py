#!/usr/bin/env python3
import os,hashlib,json,sys
from datetime import datetime,timezone

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def main(run_out):
    if not os.path.isdir(run_out):
        print("run_out not found:", run_out); return 2
    manifest = {}
    for root,_,files in os.walk(run_out):
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, run_out)
            manifest[rel] = sha256_of_file(p)
    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": "tools/generate_manifest.py v1",
        "run_id": os.path.basename(os.path.normpath(run_out)),
        "manifest": manifest
    }
    with open(os.path.join(run_out, "manifest.json"), "w", encoding="utf-8") as fo:
        json.dump(out, fo, ensure_ascii=False, indent=2)
    print("Wrote manifest.json to", os.path.join(run_out, "manifest.json"))
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 tools/generate_manifest.py <run_out_dir>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))