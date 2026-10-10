#!/bin/zsh
set -euo pipefail
ROOT=${0:A:h}
TEST_UID=${SUDO_UID:-}
TEST_GID=${SUDO_GID:-}
MONITOR_PID=""
PROBE_PIDS=()
WATCHDOG_PID=""
CLEANED=0
[[ $EUID == 0 && -n "$TEST_UID" && -n "$TEST_GID" ]] || { echo "run with sudo after make fault-sign" >&2; exit 77; }
WORK=$(mktemp -d "${TMPDIR:-/tmp}/macos-es-fault.XXXXXX"); WORK=${WORK:A}; chmod 0700 "$WORK"
cleanup() {
  (( CLEANED )) && return 0
  CLEANED=1
  set +e
  [[ -n "$WATCHDOG_PID" ]] && kill "$WATCHDOG_PID" 2>/dev/null || true
  for pid in $PROBE_PIDS; do
    kill -0 "$pid" 2>/dev/null && kill -TERM -- -"$pid" 2>/dev/null || true
  done
  if [[ -n "$MONITOR_PID" ]] && kill -0 "$MONITOR_PID" 2>/dev/null; then
    kill -TERM -- -"$MONITOR_PID" 2>/dev/null || true
    for _ in {1..50}; do
      kill -0 "$MONITOR_PID" 2>/dev/null || break
      sleep .1
    done
    kill -0 "$MONITOR_PID" 2>/dev/null && kill -KILL -- -"$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
  fi
  for pid in $PROBE_PIDS; do
    wait "$pid" 2>/dev/null || true
  done
  chown -R "$TEST_UID:$TEST_GID" "$WORK"
  echo "evidence directory: $WORK"
}
source "$ROOT/fault_traps.sh"
run_case(){
  local mode=$1 binary=$2 probes=$3
  local ready=$WORK/$mode.ready log=$WORK/$mode.jsonl error=$WORK/$mode.stderr
  local pids_file=$WORK/$mode.pids exit_code pid
  PROBE_PIDS=()
  /usr/bin/python3 -c 'import os,sys; os.setsid(); os.execv(sys.argv[1],sys.argv[1:])' \
    "$binary" --ready "$ready" --duration 2 /usr/bin/true >"$log" 2>"$error" &
  MONITOR_PID=$!
  for _ in {1..100};do [[ -e "$ready" ]]&&break;kill -0 "$MONITOR_PID" 2>/dev/null||{ cat "$error" >&2;return 1;};sleep .02;done
  [[ -e "$ready" ]]||return 1
  for ((i = 0; i < probes; i++)); do
    /usr/bin/python3 "$ROOT/launch_as_user.py" "$TEST_UID" "$WORK" /usr/bin/true &
    PROBE_PIDS+=($!)
    echo $! >>"$pids_file"
  done
  /usr/bin/python3 "$ROOT/fault_watchdog.py" 5 0 $PROBE_PIDS &
  WATCHDOG_PID=$!
  for pid in $PROBE_PIDS; do
    wait "$pid"
  done
  kill "$WATCHDOG_PID" 2>/dev/null || true
  wait "$WATCHDOG_PID" 2>/dev/null || true
  WATCHDOG_PID=""
  PROBE_PIDS=()
  /usr/bin/python3 "$ROOT/fault_watchdog.py" 10 1 "$MONITOR_PID" &
  WATCHDOG_PID=$!
  if wait "$MONITOR_PID"; then
    exit_code=0
  else
    exit_code=$?
  fi
  kill "$WATCHDOG_PID" 2>/dev/null || true
  wait "$WATCHDOG_PID" 2>/dev/null || true
  WATCHDOG_PID=""
  MONITOR_PID=""
  /usr/bin/python3 "$ROOT/validate_es_fault_evidence.py" "$mode" "$log" "$error" "$pids_file" "$exit_code"
}
run_case replay "$ROOT/build/es-continuous-replay-test" 8
run_case overflow "$ROOT/build/es-continuous-overflow-test" 100
echo 'PASS real_es_replay=verified real_es_overflow=verified existing_sessions=untouched model_requests=0'
