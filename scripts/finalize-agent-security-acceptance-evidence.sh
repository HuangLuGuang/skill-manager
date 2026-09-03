#!/usr/bin/env bash
set -euo pipefail

EVIDENCE_DIR=""

usage() {
  echo "Usage: $0 --evidence-dir /absolute/controlled/path"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --evidence-dir) EVIDENCE_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$EVIDENCE_DIR" || "$EVIDENCE_DIR" != /* ]]; then
  echo "--evidence-dir must be an explicit absolute path" >&2
  exit 2
fi
if [[ ! -d "$EVIDENCE_DIR" ]]; then
  echo "Evidence directory does not exist: $EVIDENCE_DIR" >&2
  exit 2
fi
if [[ ! -f "$EVIDENCE_DIR/acceptance-results.json" ]]; then
  echo "acceptance-results.json is required before finalizing evidence" >&2
  exit 2
fi
if [[ -n "$(find "$EVIDENCE_DIR" -type l -print -quit)" ]]; then
  echo "Evidence directory must not contain symbolic links" >&2
  exit 2
fi

TEMP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/agent-security-manifest.XXXXXX")"
trap 'rm -f "$TEMP_MANIFEST"' EXIT

(
  cd "$EVIDENCE_DIR"
  find . -type f ! -name manifest.sha256 -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done >"$TEMP_MANIFEST"
)

if [[ ! -s "$TEMP_MANIFEST" ]]; then
  echo "Refusing to write an empty sha256 manifest" >&2
  exit 1
fi
mv "$TEMP_MANIFEST" "$EVIDENCE_DIR/manifest.sha256"
trap - EXIT
echo "Evidence finalized: $EVIDENCE_DIR/manifest.sha256"
