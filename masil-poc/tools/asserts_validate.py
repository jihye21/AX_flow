#!/usr/bin/env python3
# masil-poc/tools/asserts_validate.py
# Usage: python3 asserts_validate.py <validation_report_path>
# Exit codes:
# 0 - OK
# 1 - validation_report not found or malformed
# 2 - validation error found

import sys, json, os

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 asserts_validate.py <validation_report.json>", file=sys.stderr)
        return 1
    vr = sys.argv[1]
    if not os.path.isfile(vr):
        print("validation_report.json not found:", vr, file=sys.stderr)
        return 1
    try:
        r = json.load(open(vr, encoding='utf-8'))
    except Exception as e:
        print("Failed to parse validation_report.json:", e, file=sys.stderr)
        return 1
    for entry in r.get('report', []):
        if entry.get('status') != 'ok':
            print("validation error:", entry, file=sys.stderr)
            return 2
    print("validation OK")
    return 0

if __name__ == '__main__':
    sys.exit(main())