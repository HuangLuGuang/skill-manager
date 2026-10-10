#!/bin/zsh
set -euo pipefail
ROOT=${0:A:h}
make -C "$ROOT" build/test-continuous-state build/test-continuous-faults build/test-bounded-log build/test-bounded-log-enospc
"$ROOT/build/test-continuous-state"
"$ROOT/build/test-continuous-faults"
"$ROOT/build/test-bounded-log"
"$ROOT/build/test-bounded-log-enospc"
/usr/bin/python3 -B -m unittest discover -s "$ROOT" -v -p 'test_*.py'
echo 'PASS source=test_injection deterministic_faults=verified'
