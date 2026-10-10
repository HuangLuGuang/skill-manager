#!/bin/zsh
set -euo pipefail
ROOT=${0:A:h}; BUILD="$ROOT/build"; TEST_UID=${SUDO_UID:-}; TEST_GID=${SUDO_GID:-}
[[ $EUID == 0 && -n "$TEST_UID" && -n "$TEST_GID" ]] || { echo "run with sudo after normal-user build/sign" >&2; exit 77; }
HOME_DIR=$(dscl . -read "/Users/${SUDO_USER}" NFSHomeDirectory | awk '{print $2}')
CLAUDE=${1:-$HOME_DIR/.local/bin/claude}; CLAUDE=${CLAUDE:A}
JS=${2:-$HOME_DIR/.nvm/versions/node/v22.21.1/lib/node_modules/@openai/codex/bin/codex.js}; JS=${JS:A}
CODEX=$(find "${JS:h:h}" -path '*/codex-darwin-arm64/vendor/*/codex/codex' -type f -perm +111 -print -quit); CODEX=${CODEX:A}
FIXTURE=$BUILD/continuous-fixture
[[ -x "$BUILD/es-continuous-observer" && -x "$FIXTURE" && -x "$CLAUDE" && -x "$CODEX" ]] || { echo "observer, fixture, or Agent binary unavailable" >&2; exit 69; }
WORK=$(mktemp -d "${TMPDIR:-/tmp}/macos-es-continuous.XXXXXX"); WORK=${WORK:A}; chmod 0700 "$WORK"; chown "$TEST_UID:$TEST_GID" "$WORK"
READY=$WORK/ready; GO=$WORK/go; PARENT_FILE=$WORK/parent.pid; CHILD_FILE=$WORK/child.pid
LOG=$WORK/events.jsonl; ERR=$WORK/observer.stderr; MONITOR_PID=""; FIXTURE_PID=""; FIXTURE_PGID=""; CLAUDE_PGID=""; CODEX_PGID=""; PASS=0
cleanup(){
  local bad=0
  if [[ -n "$FIXTURE_PGID" ]]&&kill -0 -- -"$FIXTURE_PGID" 2>/dev/null;then kill -TERM -- -"$FIXTURE_PGID" 2>/dev/null||true;for _ in {1..50};do kill -0 -- -"$FIXTURE_PGID" 2>/dev/null||break;sleep .1;done;kill -0 -- -"$FIXTURE_PGID" 2>/dev/null&&{ kill -KILL -- -"$FIXTURE_PGID" 2>/dev/null||true;bad=1;};fi
  for pgid in "$CLAUDE_PGID" "$CODEX_PGID";do [[ -n "$pgid" ]]&&kill -0 -- -"$pgid" 2>/dev/null&&{ kill -TERM -- -"$pgid" 2>/dev/null||true;for _ in {1..20};do kill -0 -- -"$pgid" 2>/dev/null||break;sleep .1;done;kill -0 -- -"$pgid" 2>/dev/null&&kill -KILL -- -"$pgid" 2>/dev/null||true;};done
  if [[ -n "$MONITOR_PID" ]]&&kill -0 "$MONITOR_PID" 2>/dev/null;then kill -TERM "$MONITOR_PID"||bad=1;for _ in {1..50};do kill -0 "$MONITOR_PID" 2>/dev/null||break;sleep .1;done;kill -0 "$MONITOR_PID" 2>/dev/null&&{ kill -KILL "$MONITOR_PID" 2>/dev/null||true;bad=1;};wait "$MONITOR_PID" 2>/dev/null||true;fi
  chown -R "$TEST_UID:$TEST_GID" "$WORK"||bad=1;echo "evidence directory: $WORK";((bad))&&exit 1;((PASS))&&echo "PASS continuous_observation=verified existing_sessions=untouched model_requests=0"
}
trap cleanup EXIT;trap 'exit 130' INT;trap 'exit 143' TERM
/usr/bin/python3 "$ROOT/launch_as_user.py" "$TEST_UID" "$WORK" "$FIXTURE" "$GO" "$PARENT_FILE" "$CHILD_FILE" & FIXTURE_PID=$!; FIXTURE_PGID=$FIXTURE_PID
for _ in {1..100};do [[ -s "$PARENT_FILE" ]]&&break;kill -0 "$FIXTURE_PID" 2>/dev/null||exit 1;sleep .05;done
[[ -s "$PARENT_FILE" ]]||{ echo "fixture readiness timeout" >&2;exit 75;}; PARENT_PID=$(<$PARENT_FILE)
"$BUILD/es-continuous-observer" --ready "$READY" --duration 8 "$FIXTURE" "$CLAUDE" "$CODEX" >"$LOG" 2>"$ERR" & MONITOR_PID=$!
for _ in {1..100};do [[ -e "$READY" ]]&&break;kill -0 "$MONITOR_PID" 2>/dev/null||{ cat "$ERR" >&2;exit 77;};sleep .05;done
[[ -e "$READY" ]]||{ echo "observer readiness timeout" >&2;exit 75;}
for _ in {1..100};do grep -q '"event":"snapshot_window"' "$LOG" 2>/dev/null&&break;sleep .05;done
grep -q '"event":"snapshot_window"' "$LOG"||{ echo "snapshot completion timeout" >&2;exit 75;}
touch "$GO"; chown "$TEST_UID:$TEST_GID" "$GO"
for _ in {1..100};do [[ -s "$CHILD_FILE" ]]&&break;sleep .02;done
[[ -s "$CHILD_FILE" ]]||{ echo "child pid timeout" >&2;exit 75;}; CHILD_PID=$(<$CHILD_FILE)
wait "$FIXTURE_PID"; FIXTURE_PID=""
/usr/bin/python3 "$ROOT/launch_as_user.py" "$TEST_UID" "$WORK" "$CLAUDE" --version >"$WORK/claude-version.txt" & CLAUDE_PID=$!; CLAUDE_PGID=$CLAUDE_PID
for _ in {1..100};do kill -0 "$CLAUDE_PID" 2>/dev/null||break;sleep .05;done;kill -0 "$CLAUDE_PID" 2>/dev/null&&{ echo "Claude version timeout" >&2;exit 75;};wait "$CLAUDE_PID";CLAUDE_PGID=""
/usr/bin/python3 "$ROOT/launch_as_user.py" "$TEST_UID" "$WORK" "$CODEX" --version >"$WORK/codex-version.txt" & CODEX_PID=$!; CODEX_PGID=$CODEX_PID
for _ in {1..100};do kill -0 "$CODEX_PID" 2>/dev/null||break;sleep .05;done;kill -0 "$CODEX_PID" 2>/dev/null&&{ echo "Codex version timeout" >&2;exit 75;};wait "$CODEX_PID";CODEX_PGID=""
for _ in {1..100};do kill -0 "$CHILD_PID" 2>/dev/null||break;sleep .05;done
kill -0 "$CHILD_PID" 2>/dev/null&&{ echo "fixture child timeout" >&2;exit 75;}; FIXTURE_PGID=""
for _ in {1..240};do kill -0 "$MONITOR_PID" 2>/dev/null||break;sleep .05;done
kill -0 "$MONITOR_PID" 2>/dev/null&&{ echo "observer timeout" >&2;exit 75;};wait "$MONITOR_PID";MONITOR_PID=""
/usr/bin/python3 "$ROOT/validate_continuous_evidence.py" "$LOG" "$ERR" "$FIXTURE" "$CLAUDE" "$CODEX" "$PARENT_PID" "$CHILD_PID" "$CLAUDE_PID" "$CODEX_PID"
PASS=1
