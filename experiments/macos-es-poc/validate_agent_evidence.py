#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path

def records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

def validate(path, protected, agent_entry, stderr=None):
    data=records(path)
    direct=[r for r in data if r.get("event")=="attribution" and r.get("kind")=="direct"]
    roots={r.get("root_id") for r in direct}
    if len(roots)!=1 or None in roots: raise ValueError(f"expected one registered root id, got {roots}")
    root=next(iter(roots))
    attributed=[r for r in data if r.get("event")=="attribution" and r.get("root_id")==root]
    if not any(r.get("kind")=="inherited" for r in attributed): raise ValueError("no inherited descendant evidence")
    if not any(r.get("transition")=="exec" and r.get("path")==agent_entry and r.get("agent_entry_match") is True for r in attributed): raise ValueError(f"no attributed exec matched agent entry {agent_entry}")
    instances={(r.get("pid"),r.get("pidversion")) for r in attributed if r.get("kind") in ("direct","inherited")}
    denies=[r for r in data if r.get("event")=="auth_open" and r.get("path")==protected]
    if not denies: raise ValueError("no protected-file denial")
    for r in denies:
        if r.get("root_id")!=root or r.get("attribution") not in ("direct","inherited"): raise ValueError("denial not tied to trusted root")
        if (r.get("pid"),r.get("pidversion")) not in instances: raise ValueError("denial actor is not an attributed process instance")
        if r.get("response")!=0 or r.get("deadline_remaining_ticks",0)<=0 or r.get("cache") is not False: raise ValueError("invalid denial response evidence")
    unknown_denies=[r for r in data if r.get("event")=="auth_open" and r.get("attribution")=="unknown"]
    if unknown_denies: raise ValueError("unknown process was denied")
    if stderr is not None:
        summary=Path(stderr).read_text()
        if "ATTRIBUTION gaps=0 registration_consumed=true" not in summary: raise ValueError("attribution summary reports gaps or missing registration")
        if "SUMMARY response_errors=0 dropped_logs=0 log_drain=complete" not in summary: raise ValueError("monitor summary reports response or logging failure")

def main():
    p=argparse.ArgumentParser(); p.add_argument("log"); p.add_argument("protected"); p.add_argument("agent_entry"); p.add_argument("stderr"); a=p.parse_args()
    try: validate(a.log,a.protected,a.agent_entry,a.stderr); print("agent evidence validation passed"); return 0
    except (ValueError,OSError,json.JSONDecodeError) as e: print(f"agent evidence validation failed: {e}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
