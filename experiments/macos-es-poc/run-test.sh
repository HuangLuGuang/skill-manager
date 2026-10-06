#!/bin/zsh
set -euo pipefail
ROOT=${0:A:h}
BUILD="$ROOT/build"
VALIDATOR="$ROOT/validate_evidence.py"
TEST_PARENT_PID=$$
[[ $EUID == 0 && -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]] || { echo "run: sudo ./run-test.sh" >&2; exit 77; }
[[ -x "$BUILD/es-monitor" && -x "$BUILD/file-probe" ]] || { echo "build as normal user first: make clean adhoc-sign" >&2; exit 65; }
WORK=$(mktemp -d "${TMPDIR:-/tmp}/macos-es-poc.XXXXXX")
chmod 0700 "$WORK"
READY="$WORK/ready"; BOUND="$WORK/bound"; LOG="$WORK/events.jsonl"; ERR="$WORK/monitor.stderr"
PROTECTED="$WORK/protected.txt"; ALLOWED="$WORK/allowed.txt"; MONITOR_PID=""; PASS=0
cleanup() {
  local failed=0
  if [[ -n "$MONITOR_PID" ]] && kill -0 "$MONITOR_PID" 2>/dev/null; then
    kill -TERM "$MONITOR_PID" 2>/dev/null || failed=1
    for _ in {1..50}; do kill -0 "$MONITOR_PID" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$MONITOR_PID" 2>/dev/null && failed=1
  fi
  rm -f "$PROTECTED" "$ALLOWED" "$READY" "$BOUND" || failed=1
  chown -R "$SUDO_UID:$SUDO_GID" "$WORK" || failed=1
  echo "evidence directory: $WORK"
  (( failed )) && { echo "cleanup failed" >&2; exit 1; }
  (( PASS )) && echo "PASS target_denies=100 target_allows=100 non_target_read=success post_exit_probe_read=success lifecycle=correlated"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'protected\n' > "$PROTECTED"; printf 'allowed\n' > "$ALLOWED"
"$BUILD/es-monitor" --enforce "$BUILD/file-probe" "$PROTECTED" "$READY" "$BOUND" >"$LOG" 2>"$ERR" &
MONITOR_PID=$!
for _ in {1..100}; do
  [[ -e "$READY" ]] && break
  if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
    set +e; wait "$MONITOR_PID"; early_status=$?; set -e
    MONITOR_PID=""
    cat "$ERR" >&2
    echo "monitor exited before readiness with status $early_status" >&2
    exit 77
  fi
  sleep 0.1
done
[[ -e "$READY" ]] || { echo "monitor readiness timeout" >&2; exit 75; }
"$BUILD/file-probe" --check "$PROTECTED" "$ALLOWED" 100 "$BOUND" | tee "$WORK/target-result.json"
target_pid=$(sed -E 's/.*"pid":([0-9]+).*/\1/' "$WORK/target-result.json")
/bin/cat "$PROTECTED" > "$WORK/non-target-read.txt"
[[ "$(<"$WORK/non-target-read.txt")" == protected ]]
for _ in {1..100}; do
  /usr/bin/python3 "$VALIDATOR" has-exit "$LOG" "$target_pid" && break
  sleep 0.1
done
/usr/bin/python3 "$VALIDATOR" has-exit "$LOG" "$target_pid" || { echo "target exit event timeout" >&2; exit 75; }
kill -TERM "$MONITOR_PID"
for _ in {1..100}; do kill -0 "$MONITOR_PID" 2>/dev/null || break; sleep 0.1; done
kill -0 "$MONITOR_PID" 2>/dev/null && { echo "monitor shutdown timeout" >&2; exit 75; }
set +e
wait "$MONITOR_PID"
monitor_status=$?
set -e
MONITOR_PID=""
[[ $monitor_status == 0 ]] || { echo "monitor exited with status $monitor_status" >&2; exit 1; }
"$BUILD/file-probe" --read-once "$PROTECTED" | tee "$WORK/post-exit-result.json"
/usr/bin/python3 "$VALIDATOR" validate "$LOG" "$WORK/target-result.json" "$ERR" "$TEST_PARENT_PID"
PASS=1
