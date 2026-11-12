import os
import hashlib
import json
import sys
from datetime import datetime, timezone

EXCLUDE_FILENAMES = {"manifest.json"}  # manifest 자기참조 방지
EXCLUDE_SUFFIXES = {'.tmp', '.swp', '~'}  # 임시 파일 확장자 예시
EXCLUDE_DIRS = {'.git', '__pycache__'}  # 순회 제외 디렉토리

GENERATOR_VERSION = "tools/generate_manifest.py v1.1"

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def should_exclude(relpath):
    # relpath: 경로 상대 run_out
    name = os.path.basename(relpath)
    if name in EXCLUDE_FILENAMES:
        return True
    for suf in EXCLUDE_SUFFIXES:
        if name.endswith(suf):
            return True
    # 디렉토리 기반 제외 (상위 폴더명 포함 검사)
    parts = relpath.split(os.sep)
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
    return False

def main(run_out):
    if not os.path.isdir(run_out):
        print("run_out not found:", run_out, file=sys.stderr)
        return 2

    manifest = {}
    # walk run_out; 상대경로 기준으로 manifest에 추가
    for root, dirs, files in os.walk(run_out):
        # 디렉토리 필터: EXCLUDE_DIRS를 만나면 그 하위로 가지 않음
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in sorted(files):
            abs_path = os.path.join(root, f)
            rel = os.path.relpath(abs_path, run_out)
            # skip if exclude
            if should_exclude(rel):
                continue
            try:
                manifest[rel] = sha256_of_file(abs_path)
            except Exception as e:
                print(f"[WARN] Failed to hash {abs_path}: {e}", file=sys.stderr)

    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": GENERATOR_VERSION,
        "run_id": os.path.basename(os.path.normpath(run_out)),
        "manifest": manifest
    }

    tmp_path = os.path.join(run_out, "manifest.json.tmp")
    final_path = os.path.join(run_out, "manifest.json")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fo:
            json.dump(out, fo, ensure_ascii=False, indent=2)
            fo.write("\n")
        # atomic replace
        os.replace(tmp_path, final_path)
    except Exception as e:
        # cleanup tmp if exists
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        print(f"[ERROR] Failed to write manifest: {e}", file=sys.stderr)
        return 3

    print("Wrote manifest.json to", final_path)
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 tools/generate_manifest.py <run_out_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))