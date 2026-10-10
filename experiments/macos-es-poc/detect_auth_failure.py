#!/usr/bin/env python3
import json, sys
def contains(value):
    if isinstance(value,str): return value == "authentication_failed" or "authentication_failed" in value
    if isinstance(value,dict): return any(contains(v) for v in value.values())
    if isinstance(value,list): return any(contains(v) for v in value)
    return False
try:
    raw=open(sys.argv[1]).read()
    lines=raw.splitlines()
    for line in lines:
        if line.strip() and contains(json.loads(line)):
            raise SystemExit(0)
    stderr=open(sys.argv[2]).read()
    raise SystemExit(0 if "authentication_failed" in stderr else 1)
except (OSError,json.JSONDecodeError):
    raise SystemExit(2)
