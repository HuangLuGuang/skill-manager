#!/bin/sh
set -eu
fail() {
  if [ "${1:-}" = "PreToolUse" ]; then
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"aidr_hook_binary_unavailable"}}'
    exit 0
  fi
  printf '%s\n' 'aidr_hook_binary_unavailable' >&2
  exit 1
}
case "${AIDR_CLIENT_BIN:-}" in
  /*) ;;
  *) fail "${1:-}" ;;
esac
if [ ! -x "$AIDR_CLIENT_BIN" ]; then
  fail "${1:-}"
fi
exec "$AIDR_CLIENT_BIN" aidr-hook --agent codex --event "$1"
