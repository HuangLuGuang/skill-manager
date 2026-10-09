#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/deploy/offline.py" upgrade --install-dir "$ROOT" "$@"
