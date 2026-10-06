#!/bin/zsh
set -euo pipefail
ROOT=${0:A:h}
run_case() {
  local signal_name=${1:-}
  /bin/zsh -c '
    set -euo pipefail
    source "$1"
    marker=$2
    cleaned=0
    cleanup(){ (( cleaned )) && return 0; cleaned=1; print cleanup >>"$marker"; set +e; false; }
    if [[ -n "$3" ]]; then kill -"$3" $$; else fail(){ false; print BAD >>"$marker"; }; fail; fi
    print PASS >>"$marker"
  ' runner "$ROOT/fault_traps.sh" "$2" "$signal_name"
}
work=$(mktemp -d "${TMPDIR:-/tmp}/fault-traps.XXXXXX")
set +e
run_case "" "$work/error"
error_code=$?
run_case INT "$work/int"
int_code=$?
set -e
[[ $error_code == 1 && $int_code == 130 ]]
[[ "$(<"$work/error")" == cleanup && "$(<"$work/int")" == cleanup ]]
print 'fault runner trap tests passed'
