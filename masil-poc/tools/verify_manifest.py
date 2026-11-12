#!/usr/bin/env python3

import os
import sys
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Tuple

def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def parse_iso(s: str) -> datetime:
    # Accepts ISO8601 like "2026-11-12T05:58:17Z" or with offset "+09:00"
    try:
        # Python 3.11 supports fromisoformat with Z, but otherwise handle Z:
        if s.endswith('Z'):
            return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(timezone.utc)
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        raise ValueError(f"Invalid ISO timestamp: {s}")

def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def verify_manifest(run_out: str) -> Tuple[int, Dict]:
    manifest_path = os.path.join(run_out, 'manifest.json')
    if not os.path.isfile(manifest_path):
        print(f"[ERROR] manifest.json not found at: {manifest_path}", file=sys.stderr)
        return 1, {}

    try:
        m = load_json(manifest_path)
    except Exception as e:
        print(f"[ERROR] Failed to parse manifest.json: {e}", file=sys.stderr)
        return 1, {}

    manifest_map = m.get('manifest')
    created_at = m.get('created_at')
    generator_version = m.get('generator_version', None)
    run_id_from_manifest = m.get('run_id', None)

    if not isinstance(manifest_map, dict):
        print("[ERROR] manifest.json missing 'manifest' object or malformed.", file=sys.stderr)
        return 1, {}

    missing = []
    mismatches = []

    for rel, expected_hash in sorted(manifest_map.items()):
        file_path = os.path.join(run_out, rel)
        if not os.path.exists(file_path):
            missing.append(rel)
            continue
        try:
            actual = sha256_of_file(file_path)
        except Exception as e:
            print(f"[ERROR] Failed to hash file {file_path}: {e}", file=sys.stderr)
            return 6, {}
        if actual.lower() != expected_hash.lower():
            mismatches.append((rel, expected_hash, actual))

    result = {
        "manifest_path": manifest_path,
        "created_at": created_at,
        "generator_version": generator_version,
        "run_id_from_manifest": run_id_from_manifest,
        "missing_files": missing,
        "hash_mismatches": mismatches
    }

    if missing:
        print("[ERROR] Missing files referenced in manifest:", file=sys.stderr)
        for fn in missing:
            print("  -", fn, file=sys.stderr)
        return 2, result

    if mismatches:
        print("[ERROR] Hash mismatches detected:", file=sys.stderr)
        for rel, exp, act in mismatches:
            print(f"  - {rel}", file=sys.stderr)
            print(f"      expected: {exp}", file=sys.stderr)
            print(f"      actual:   {act}", file=sys.stderr)
        return 3, result

    # Optional: check timing consistency with run_metadata.finished_at
    run_meta_path = os.path.join(run_out, 'run_metadata.json')
    if os.path.isfile(run_meta_path):
        try:
            run_meta = load_json(run_meta_path)
            finished_at = run_meta.get('finished_at')
            if finished_at:
                if not created_at:
                    print("[WARN] manifest.created_at missing while run_metadata.finished_at exists.", file=sys.stderr)
                else:
                    try:
                        created_dt = parse_iso(created_at)
                        finished_dt = parse_iso(finished_at)
                        # require manifest.created_at >= finished_at (allow equal)
                        if created_dt < finished_dt:
                            print("[ERROR] Timing inconsistency:", file=sys.stderr)
                            print(f"  manifest.created_at: {created_at} (UTC {created_dt.isoformat()})", file=sys.stderr)
                            print(f"  run_metadata.finished_at: {finished_at} (UTC {finished_dt.isoformat()})", file=sys.stderr)
                            result['timing'] = {
                                'manifest_created_at': created_at,
                                'run_finished_at': finished_at
                            }
                            return 4, result
                    except ValueError as e:
                        print(f"[WARN] Timestamp parse error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Could not read run_metadata.json: {e}", file=sys.stderr)

    print("[OK] manifest verification passed. All files present and hashes match.")
    # print summary
    print("Summary:")
    print("  manifest:", manifest_path)
    if created_at:
        print("  manifest.created_at:", created_at)
    if generator_version:
        print("  generator_version:", generator_version)
    if run_id_from_manifest:
        print("  run_id (from manifest):", run_id_from_manifest)
    return 0, result

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 verify_manifest.py <run_out_dir>", file=sys.stderr)
        print("Example: python3 verify_manifest.py masil-poc/results/db395f82-454b-45dc-adaa-e5e671a08091", file=sys.stderr)
        sys.exit(5)
    run_out = sys.argv[1]
    if not os.path.isdir(run_out):
        print(f"[ERROR] run_out directory does not exist: {run_out}", file=sys.stderr)
        sys.exit(5)
    try:
        code, info = verify_manifest(run_out)
        # Optionally print JSON summary to stdout file for CI consumption
        # with open(os.path.join(run_out, 'verify_manifest_summary.json'), 'w', encoding='utf-8') as f:
        #     json.dump(info, f, ensure_ascii=False, indent=2)
        sys.exit(code)
    except Exception as e:
        print(f"[ERROR] Unexpected exception: {e}", file=sys.stderr)
        sys.exit(6)

if __name__ == '__main__':
    main()