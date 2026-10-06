#!/usr/bin/env python3
import json, os, shutil, subprocess
from pathlib import Path
def inspect(name):
    fallbacks={"claude":Path.home()/".local/bin/claude","codex":Path.home()/".nvm/versions/node/v22.21.1/bin/codex"}
    entry=shutil.which(name) or (str(fallbacks[name]) if fallbacks[name].exists() else None)
    if not entry: return {"name":name,"available":False}
    canonical=str(Path(entry).resolve())
    version=subprocess.run([entry,"--version"],text=True,capture_output=True,timeout=10)
    return {"name":name,"available":True,"entry":entry,"canonical_entry":canonical,"version":version.stdout.strip() or version.stderr.strip(),"version_status":version.returncode}
print(json.dumps({"uid":os.getuid(),"agents":[inspect("claude"),inspect("codex")]},indent=2))
