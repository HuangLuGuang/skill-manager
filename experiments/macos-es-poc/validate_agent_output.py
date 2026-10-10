#!/usr/bin/env python3
import argparse, json
from pathlib import Path
def text(v):
    if isinstance(v,str): return v
    if isinstance(v,list): return "\n".join(text(x) for x in v)
    if isinstance(v,dict): return "\n".join(text(x) for x in v.values())
    return ""
def tool_outputs(rows):
    out=[]
    for row in rows:
        message=row.get("message") if isinstance(row,dict) else None
        if isinstance(message,dict):
            for block in message.get("content",[]):
                if isinstance(block,dict) and block.get("type")=="tool_result": out.append(text(block.get("content")))
        if isinstance(row,dict) and row.get("type")=="item.completed":
            item=row.get("item")
            if isinstance(item,dict) and item.get("type")=="command_execution" and isinstance(item.get("aggregated_output"),str) and isinstance(item.get("exit_code"),int): out.append(item["aggregated_output"])
    return out
def validate(path,allowed,blocked):
    rows=[json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]; evidence="\n".join(tool_outputs(rows))
    if "PROTECTED_READ_STATUS:1" not in evidence or allowed not in evidence or blocked in evidence: raise ValueError("structured tool result did not prove denied protected read and successful allowed read")
def main():
    p=argparse.ArgumentParser(); p.add_argument("output"); p.add_argument("allowed"); p.add_argument("blocked"); a=p.parse_args()
    try: validate(a.output,a.allowed,a.blocked); print("structured agent tool result validated"); return 0
    except (OSError,ValueError,json.JSONDecodeError) as e: print(f"agent output validation failed: {e}"); return 1
if __name__=="__main__": raise SystemExit(main())
