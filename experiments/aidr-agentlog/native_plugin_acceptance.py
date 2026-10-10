#!/usr/bin/env python3
"""Bounded native Codex smoke run in a new private profile and workspace.

Uses a one-invocation hook trust override for our freshly built local package.
It does not establish persisted native hook trust or prove enforcement.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time


def audit_checks(report, completed_commands):
    """Independent expectations for the two requested calls, not host success alone."""
    return {
        "native_exited": report.get("native_exit") == 0,
        "receiver_exited": report.get("receiver_exit") == 0,
        "two_commands_exit_0_7": [c.get("exit_code") for c in completed_commands] == [0, 7],
        "eight_lifecycle_receipts": report.get("received_hooks") == 8,
        "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
        "two_log_calls_and_results": [e["type"] for e in report.get("native_tool_records", [])]
        == ["custom_tool_call", "custom_tool_call_output"] * 2,
    }


def run(options):
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-native-codex-", dir="/private/tmp")).resolve()
    home, work = root/"codex", root/"work"
    home.mkdir(mode=0o700); work.mkdir(mode=0o700)
    binary, market, sock = root/"agent-manager-client", root/"market", root/"hook.sock"
    report = {"root": str(root), "scope": "native_codex_audit", "persisted_hook_trust": "not_verified", "trust_mode": "vetted_package_invocation_override"}
    env = {**os.environ, "CODEX_HOME": str(home), "AIDR_CLIENT_BIN": str(binary), "AIDR_HOOK_SOCKET": str(sock)}
    receiver = native = None
    handles = []
    try:
        subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"], cwd=repo/"scanner", check=True, capture_output=True, timeout=120)
        subprocess.run([str(binary), "aidr-plugin-package", "--source-dir", str(repo/"client/aidr-plugins"), "--destination", str(market)], check=True, capture_output=True, timeout=30)
        install = subprocess.run([str(binary), "aidr-plugin-install", "--agent", "codex", "--host-bin", options.codex, "--host-config-dir", str(home), "--marketplace-path", str(market)], check=True, capture_output=True, timeout=60)
        installed = json.loads(install.stdout)
        report["native_version"] = installed.get("host_version", installed.get("version"))
        # Test-only observer records field names/types and explicit numeric exit
        # codes. It never writes prompt, argument or result bodies.
        observer=root/"observe-hook"
        observer.write_text("#!"+sys.executable+"\n"+'''import json,os,re,subprocess,sys
raw=sys.stdin.buffer.read(262145)
try:
 e=json.loads(raw)
 def shape(v,depth=0):
  if isinstance(v,str):
   try:
    nested=json.loads(v)
    if isinstance(nested,(dict,list)) and depth<3:return {'encoded_json':shape(nested,depth+1)}
   except ValueError:pass
   # Only record fixed protocol markers and numeric exit codes, never output.
   return {'type':'str','length':len(v),'exit_headers':re.findall(r'(?m)^(?:Process exited with code|Exit code:?) (-?[0-9]+)$',v)[:8],'controlled_stdout':v=="aidr-native-hook-check\\n",'empty':not v}
  if isinstance(v,dict) and depth<3:
   return {k:(x if k in ('exit_code','exitCode','exit_status') and isinstance(x,int) else shape(x,depth+1)) for k,x in list(v.items())[:40] if isinstance(k,str) and k.isidentifier() and len(k)<64}
  return type(v).__name__
 row={'event':e.get('hook_event_name'),'response_shape':shape(e.get('tool_response')),'top_fields':sorted(k for k in e if k.isidentifier() and len(k)<64)}
 fd=os.open(os.environ['AIDR_TEST_SHAPES'],os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
 with os.fdopen(fd,'a') as f:f.write(json.dumps(row)+'\\n')
except (ValueError,TypeError):pass
r=subprocess.run([os.environ['AIDR_TEST_CLIENT'],*sys.argv[1:]],input=raw)
sys.exit(r.returncode)
''')
        observer.chmod(0o700)
        env.update(AIDR_CLIENT_BIN=str(observer),AIDR_TEST_CLIENT=str(binary),AIDR_TEST_SHAPES=str(root/"hook-shapes.jsonl"))
        source_auth = Path.home()/".codex/auth.json"
        shutil.copyfile(source_auth, home/"auth.json"); (home/"auth.json").chmod(0o600)
        if options.model:
            config = home/"config.toml"
            config.write_text("model = "+json.dumps(options.model)+"\n"+config.read_text())
        receiver_env = {**env, "AIDR_NATIVE_TEST_TOKEN": Path(options.token_file).read_text().strip()}
        def private_output(name):
            path=root/name
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            handle=os.fdopen(fd,"wb");handles.append(handle);return handle
        receiver_command = [str(binary), "aidr-hook-serve", "--state-dir", str(root/"state"), "--socket", str(sock), "--server", options.server, "--client-id", options.client_id, "--token-env", "AIDR_NATIVE_TEST_TOKEN"]
        if options.public_key: receiver_command += ["--public-key", options.public_key]
        receiver = subprocess.Popen(receiver_command, env=receiver_env, stdout=private_output("receiver.json"), stderr=private_output("receiver.stderr"))
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if receiver.poll() is not None: raise RuntimeError("receiver_start_failed")
            result=subprocess.run([str(binary),"aidr-hook","--socket",str(sock),"--health"],env=env,capture_output=True,timeout=5)
            if result.returncode==0:
                report["receiver_health"]=json.loads(result.stdout)["state"]
                if not options.public_key or report["receiver_health"].get("control_code") == "aidr_hook_policy_ready": break
            time.sleep(.1)
        else: raise RuntimeError("receiver_readiness_timeout")
        prompt="This is an isolated AIDR native hook acceptance test. Execute exactly two separate shell tool calls in this working directory: first /usr/bin/printf 'aidr-native-hook-check\\n'; second exit 7. Do not combine the calls, inspect other files, read environment variables, or retry failed commands. Then briefly report the two observed exit codes. Do not modify files."
        marker=work/"approval-probe"
        sandbox="read-only"
        if options.expected_decision:
            if not options.public_key: raise ValueError("control_probe_requires_public_key")
            sandbox="workspace-write"
            prompt="Isolated AIDR approval test. Make exactly one shell tool call: /usr/bin/touch "+str(marker)+". Do not retry if denied, inspect files or environment, call other tools or spawn agents. Then report only the tool outcome."
        native=subprocess.Popen([options.codex,"exec","--skip-git-repo-check","--sandbox",sandbox,"--dangerously-bypass-hook-trust","--json","-C",str(work),prompt],env=env,cwd=work,stdout=private_output("native.jsonl"),stderr=private_output("native.stderr"))
        try: report["native_exit"]=native.wait(timeout=120)
        except subprocess.TimeoutExpired:
            native.terminate()
            try: native.wait(timeout=10)
            except subprocess.TimeoutExpired: native.kill();native.wait(timeout=5)
            report["native_exit"]=124
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            result=subprocess.run([str(binary),"aidr-hook","--socket",str(sock),"--health"],env=env,capture_output=True,timeout=5)
            if result.returncode==0:
                report["final_health"]=json.loads(result.stdout)["state"]
                ready=True
                if options.expected_decision:
                    with sqlite3.connect(root/"state/hooks.db") as db:
                        ready=db.execute("SELECT count(*) FROM hook_attempt_reports WHERE acked=1").fetchone()[0]==1
                if report["final_health"]["queued_records"]==0 and ready:break
            time.sleep(.2)
        receiver.send_signal(signal.SIGTERM);receiver.wait(timeout=10)
        report["receiver_exit"]=receiver.returncode
        with sqlite3.connect(root/"state/hooks.db") as db:
            report["received_hooks"]=db.execute("SELECT count(*) FROM hook_receipts").fetchone()[0]
            report["terminal_reports_acked"]=db.execute("SELECT count(*) FROM hook_attempt_reports WHERE acked=1").fetchone()[0]
        events=[]
        denial_recorded=False
        for path in (home/"sessions").rglob("*.jsonl"):
            for line in path.read_text().splitlines():
                try: item=json.loads(line)
                except ValueError: continue
                payload=item.get("payload",{})
                if payload.get("type") in ("function_call","function_call_output","custom_tool_call","custom_tool_call_output"):
                    events.append({"type":payload["type"],"name":payload.get("name"),"call_id":payload.get("call_id")})
                    if payload["type"].endswith("_output") and "aidr_hook_grant_deny" in json.dumps(payload.get("output")):
                        denial_recorded=True
        report["native_tool_records"]=events
        completed=[]
        for line in (root/"native.jsonl").read_text().splitlines():
            try: row=json.loads(line)
            except ValueError: continue
            item=row.get("item",{})
            if row.get("type")=="item.completed" and item.get("type")=="command_execution":
                completed.append({"id":item.get("id"),"exit_code":item.get("exit_code"),"status":item.get("status")})
        report["command_execution_evidence"]=completed
        report["audit_checks"]=audit_checks(report,completed)
        report["status"]="native_audit_smoke_passed" if all(report["audit_checks"].values()) else "native_audit_smoke_incomplete"
        if options.expected_decision:
            report["marker_exists"]=marker.exists()
            report["expected_decision"]=options.expected_decision
            report["denial_recorded"]=denial_recorded
            report["checks"]={
                "native_exited":report["native_exit"]==0,
                "one_call_and_result":len(events)==2 and events[0]["type"]=="custom_tool_call" and events[1]["type"]=="custom_tool_call_output" and events[0]["call_id"]==events[1]["call_id"],
                "marker_matches_decision":marker.exists()==(options.expected_decision=="allow"),
                "host_outcome":(len(completed)==1 and completed[0]["exit_code"]==0) if options.expected_decision=="allow" else denial_recorded,
                "control_enabled":report["receiver_health"].get("control_mode")=="plugin_pre_tool",
                "terminal_report_acked":report["terminal_reports_acked"]==1,
                "receiver_reclaimed":report["receiver_exit"]==0 and not sock.exists(),
                "outbox_drained":report["final_health"]["queued_records"]==0,
            }
            report["status"]="native_control_probe_passed" if all(report["checks"].values()) else "native_control_probe_incomplete"
    except Exception as exc:
        report["status"]="failed";report["error_type"]=type(exc).__name__
    finally:
        for process in (native,receiver):
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for handle in handles:handle.close()
        (home/"auth.json").unlink(missing_ok=True)
        (root/"report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({"report":str(root/"report.json"),"status":report["status"],"native_exit":report.get("native_exit"),"received_hooks":report.get("received_hooks")}))


if __name__=="__main__":
    def cancelled(_signum, _frame):
        raise InterruptedError("acceptance_cancelled")
    signal.signal(signal.SIGTERM,cancelled)
    parser=argparse.ArgumentParser()
    parser.add_argument("--codex",required=True)
    parser.add_argument("--server",required=True)
    parser.add_argument("--client-id",required=True)
    parser.add_argument("--token-file",required=True)
    parser.add_argument("--model")
    parser.add_argument("--public-key")
    parser.add_argument("--expected-decision",choices=("allow","deny"))
    run(parser.parse_args())
