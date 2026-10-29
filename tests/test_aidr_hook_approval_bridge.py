"""Owned Go processes and real HTTP approval APIs; synthetic native hook input."""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time

from cryptography.hazmat.primitives import serialization
import uvicorn
import pytest

from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control as base_control
from tests.test_aidr_hook_control import control


@pytest.mark.parametrize('agent', ['codex', 'codebuddy'])
def test_owned_bridge_waits_for_exact_signed_approval(control, tmp_path, agent):
    client, _, key = control
    api = "/api/v1/clients/one/aidr"
    response = client.put(api+"/hook-policy", json={"expected_revision":"0", "lifetime_seconds":3600, "approval_wait_seconds":30, "default_action":"deny", "rules":[{"id":"review", "agent":agent, "tool":"Bash", "decision":"ask"}]})
    assert response.status_code == 200, response.text
    repository = Path(__file__).resolve().parents[1]
    binary = tmp_path/"agent-manager-client"
    subprocess.run(["go","build","-o",str(binary),"./cmd/agent-manager-client"], cwd=repository/"scanner", check=True, capture_output=True, timeout=120)
    public = tmp_path/"public.x963"
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    listener = socket.socket()
    listener.bind(("127.0.0.1",0))
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="critical", access_log=False, lifespan="off"))
    thread = threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    thread.start()
    receiver = bridge = None
    with tempfile.TemporaryDirectory(prefix="aidr-p3-approval-") as directory:
        root = Path(directory).resolve()
        sock = root/"h.sock"
        try:
            receiver = subprocess.Popen([str(binary),"aidr-hook-serve","--state-dir",str(root/"state"),"--socket",str(sock),"--server",f"http://127.0.0.1:{listener.getsockname()[1]}","--client-id","one","--token-env","AIDR_TEST_TOKEN","--public-key",str(public)], env={**os.environ,"AIDR_TEST_TOKEN":"test-one"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic()+15
            ready = False
            while time.monotonic()<deadline:
                assert receiver.poll() is None
                result = subprocess.run([str(binary),"aidr-hook","--socket",str(sock),"--health"], capture_output=True,timeout=5)
                if result.returncode==0:
                    state=json.loads(result.stdout)["state"]
                    if state["control_code"]=="aidr_hook_policy_ready":
                        assert state["control_mode"]=="plugin_pre_tool" and state["control_revision"]=="1"
                        ready=True
                        break
                time.sleep(.1)
            assert ready
            actions = ("allow", "deny", "timeout") if agent == 'codebuddy' else ("allow", "deny")
            seen = set()
            for number, action in enumerate(actions,1):
                event={"hook_event_name":"PreToolUse","session_id":"synthetic-approval-session","turn_id":"turn", "tool_use_id":f"call-{number}","tool_name":"Bash","cwd":str(root),"tool_input":{"command":"/bin/sleep 1"}}
                if agent == 'codebuddy':
                    event.pop('tool_use_id')
                    event['generation_id'] = event.pop('turn_id')
                    event['cwd'] = '/'
                bridge=subprocess.Popen([str(binary),"aidr-hook","--socket",str(sock),"--agent",agent,"--event","PreToolUse"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                bridge.stdin.write(json.dumps(event).encode());bridge.stdin.close();bridge.stdin=None
                deadline=time.monotonic()+15
                row=None
                while time.monotonic()<deadline:
                    assert bridge.poll() is None, "hook returned before platform decision"
                    response=client.get(api+"/hook-approvals")
                    assert response.status_code==200
                    row=next((r for r in response.json()["items"] if r['id'] not in seen),None)
                    if row: break
                    time.sleep(.1)
                assert row and row["state"]=="pending"
                seen.add(row['id'])
                assert row['scope']['agent'] == agent
                assert row['scope']['native_call_id'] == ('' if agent == 'codebuddy' else f'call-{number}')
                assert row['scope']['turn_id'] == 'turn'
                assert row["scope"]["receiver_instance"]==state["receiver_instance"]
                assert row["scope"]["user_scope"]==str(os.geteuid())
                assert row["scope"]["execution_point"]=="plugin_pre_tool"
                if action != 'timeout':
                    reply=client.post(api+f"/hook-approvals/{row['id']}/decision",json={"request_id":f"{number:032x}","expected_revision":row["revision"],"decision":action})
                    assert reply.status_code==200
                out,err=bridge.communicate(timeout=55 if action == 'timeout' else 15)
                assert bridge.returncode==0, err.decode()
                output=json.loads(out)
                if action=="allow": assert output=={}
                else:
                    assert output["hookSpecificOutput"]["permissionDecision"]=="deny"
                    assert output["hookSpecificOutput"]["permissionDecisionReason"]==("aidr_hook_approval_timeout" if action == 'timeout' else "aidr_hook_grant_deny")
                    if agent == 'codebuddy': assert output['continue'] is False
                bridge=None
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                items=client.get(api+"/hook-approvals").json()["items"]
                reports=[client.get(api+f"/hook-approvals/{item['id']}").json()["client_report"] for item in items]
                if len(reports)==len(actions) and all(reports): break
                time.sleep(.2)
            assert sorted(report["record"]["state"] for report in reports)==["consumed"] + ["denied"] * (len(actions)-1)
            assert all(report["evidence_type"]=="client_report" for report in reports)
            with sqlite3.connect(root/"state"/"hooks.db") as db:
                assert dict(db.execute("SELECT state,count(*) FROM hook_attempts GROUP BY state"))=={"consumed":1,"denied":len(actions)-1}
                assert db.execute("SELECT count(*) FROM hook_grants WHERE consumed=1").fetchone()[0]==1
                assert db.execute("SELECT count(*) FROM hook_attempt_reports WHERE acked=1").fetchone()[0]==len(actions)
            if agent == 'codebuddy':
                timed = next(r for r in items if r['state'] == 'timed_out')
                late = client.post(api+f"/hook-approvals/{timed['id']}/decision",json={"request_id":"f"*32,"expected_revision":timed['revision'],"decision":"allow"})
                assert late.status_code == 409
            receiver.send_signal(signal.SIGTERM)
            receiver.communicate(timeout=10)
            assert receiver.returncode==0 and not sock.exists()
        finally:
            for process in (bridge,receiver):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill();process.communicate(timeout=5)
            server.should_exit=True
            thread.join(timeout=10)
            listener.close()
