#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAPPING="$REPO_DIR/docs/acceptance/agent-security-vnext/e2e-regression-cases.json"
OUTPUT_DIR=""

usage() {
  echo "Usage: $0 --output-dir /absolute/empty/path"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" != /* ]]; then
  echo "--output-dir must be an explicit absolute path" >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "Refusing to overwrite non-empty E2E evidence directory: $OUTPUT_DIR" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cd "$REPO_DIR"

TEST_IDS=()
while IFS= read -r test_id; do
  TEST_IDS+=("$test_id")
done < <(python3 - "$MAPPING" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = [f"E2E-{index:02d}" for index in range(1, 11)]
actual = [item.get("id") for item in payload.get("cases", [])]
if payload.get("schema") != "agent-security-e2e-regression@1" or actual != expected:
    raise SystemExit("invalid or incomplete E2E regression mapping")
if payload.get("bank_environment_equivalent") is not False:
    raise SystemExit("E2E mapping must not claim bank-environment equivalence")
seen = set()
for case in payload["cases"]:
    tests = case.get("tests")
    if not isinstance(tests, list) or not tests:
        raise SystemExit(f"{case['id']} has no tests")
    for test_id in tests:
        if test_id not in seen:
            seen.add(test_id)
            print(test_id)
PY
)

uv run pytest "${TEST_IDS[@]}" -q \
  --junitxml="$OUTPUT_DIR/e2e-junit.xml" \
  2>&1 | tee "$OUTPUT_DIR/e2e-pytest.log"

SOURCE_KIND="release_provenance"
SOURCE_REF=""
WORKTREE_DIRTY="false"
SOURCE_TREE_SHA256=""
if [[ "$(git rev-parse --show-toplevel 2>/dev/null || true)" = "$REPO_DIR" ]]; then
  SOURCE_KIND="git_worktree"
  SOURCE_REF="$(git rev-parse HEAD)"
  if [[ -n "$(git status --short)" ]]; then
    WORKTREE_DIRTY="true"
  fi
  SOURCE_TREE_SHA256="$(python3 - "$REPO_DIR" <<'PY'
import hashlib
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = subprocess.run(
    ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    check=True,
    capture_output=True,
).stdout.split(b"\0")
digest = hashlib.sha256()
for raw_path in sorted(path for path in paths if path):
    relative = raw_path.decode("utf-8", "surrogateescape")
    path = root / relative
    digest.update(raw_path)
    digest.update(b"\0")
    if path.is_symlink():
        digest.update(b"symlink\0")
        digest.update(os.readlink(path).encode("utf-8", "surrogateescape"))
    else:
        digest.update(b"file\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    digest.update(b"\0")
print(digest.hexdigest())
PY
)"
elif [[ -f release-provenance.json ]]; then
  SOURCE_REF="$(python3 -c 'import json; print(json.load(open("release-provenance.json", encoding="utf-8"))["git_commit"])')"
  WORKTREE_DIRTY="$(python3 -c 'import json; print(str(json.load(open("release-provenance.json", encoding="utf-8"))["worktree_dirty"]).lower())')"
else
  echo "Neither Git source state nor release provenance is available" >&2
  exit 1
fi

E2E_SOURCE_KIND="$SOURCE_KIND" \
E2E_SOURCE_REF="$SOURCE_REF" \
E2E_WORKTREE_DIRTY="$WORKTREE_DIRTY" \
E2E_SOURCE_TREE_SHA256="$SOURCE_TREE_SHA256" \
python3 - "$MAPPING" "$OUTPUT_DIR/e2e-results.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

mapping = json.load(open(sys.argv[1], encoding="utf-8"))
result = {
    "schema": "agent-security-e2e-results@1",
    "scope": mapping["scope"],
    "bank_environment_equivalent": False,
    "source_kind": os.environ["E2E_SOURCE_KIND"],
    "source_ref": os.environ["E2E_SOURCE_REF"],
    "worktree_dirty": os.environ["E2E_WORKTREE_DIRTY"] == "true",
    "source_tree_sha256": os.environ["E2E_SOURCE_TREE_SHA256"] or None,
    "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "summary": {"passed": 10, "failed": 0},
    "cases": [
        {"id": case["id"], "status": "passed", "tests": case["tests"]}
        for case in mapping["cases"]
    ],
}
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")
PY

(
  cd "$OUTPUT_DIR"
  shasum -a 256 e2e-junit.xml e2e-pytest.log e2e-results.json >manifest.sha256
)
echo "E2E regression evidence collected in: $OUTPUT_DIR"
