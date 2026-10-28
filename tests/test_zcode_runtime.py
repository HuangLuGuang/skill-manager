"""Opt-in installed ZCode runtime with a loopback model and isolated AIDR backend."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control
from tests.test_aidr_content import configure
from backend import models


@pytest.mark.skipif(not os.environ.get('ZCODE_ACCEPTANCE_ROOT'), reason='requires installed ZCode and owned local model')
def test_native_runtime(control):
    client, factory, key = control
    repo = Path(__file__).resolve().parents[1]
    evidence = repo/'outputs/zcode-acceptance/evidence'
    root = Path(os.environ['ZCODE_ACCEPTANCE_ROOT']).resolve()
    assert root.is_dir() and (root/'isolate.cjs').is_file()
    configure(factory, capture={'prompt': True, 'tool_output': True, 'file_body': True, 'model_response': True})
    api = '/api/v1/clients/one/aidr'
    policy = {'expected_revision':'0', 'lifetime_seconds':3600, 'approval_wait_seconds':30, 'default_action':'allow', 'rules':[
        {'id':'review-bash', 'agent':'zcode', 'tool':'Bash', 'decision':'ask'},
        {'id':'deny-write', 'agent':'zcode', 'tool':'Write', 'decision':'deny'},
    ]}
    binary = root/'agent-manager-client'
    subprocess.run(['go','build','-o',str(binary),'./cmd/agent-manager-client'],cwd=repo/'scanner',check=True,timeout=120)
    public = root/'public.x963'
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))
    listener=socket.socket();listener.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(client.app,log_level='critical',access_log=False,lifespan='off'))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    common=['--server',f'http://127.0.0.1:{listener.getsockname()[1]}','--client-id','one','--token-env','AIDR_TEST_TOKEN']
    env={**os.environ,'AIDR_TEST_TOKEN':'test-one'}
    native_env={**os.environ,'ZCODE_BUILTIN_PROVIDER_CONFIG_FILE':'/Applications/ZCode.app/Contents/Resources/config/provider/zcode-builtin.json','ZCODE_PERSONAL_PROVIDER_CONFIG_FILE':str(root/'home/.zcode/v2/provider_config.json')}
    config_path=root/'home/.zcode/cli/config.json'
    original=config_path.read_text()
    processes=[];logs=[];native=None
    result=[]
    state_root=root/f'aidr-{time.time_ns()}'
    state_root.mkdir(mode=0o700)
    try:
        commands=[['aidr-hook-serve','--state-dir',str(state_root/'state'),'--socket',str(root/'h.sock'),'--public-key',str(public)],
                  ['aidr-sync','--state-dir',str(state_root/'log-state'),'--source','zcode='+str(root/'home/.zcode/cli/db')]]
        for index,command in enumerate(commands):
            log=(evidence/f'service-{index}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen([str(binary),*command,*common],env=env,stdout=log,stderr=log))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            response=client.put(api+'/hook-policy',json=policy)
            if response.status_code==200:break
            assert response.status_code==409,response.text
            time.sleep(.2)
        else:pytest.fail('client capability report missing: '+response.text)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            health=subprocess.run([str(binary),'aidr-hook','--socket',str(root/'h.sock'),'--health'],capture_output=True,timeout=3)
            if health.returncode==0 and json.loads(health.stdout)['state']['control_code']=='aidr_hook_policy_ready':break
            time.sleep(.2)
        else:pytest.fail('receiver not ready')
        connection=root/'bridge.json'
        connection.write_text(json.dumps({'socket':str(root/'h.sock'),'active':True,'agents':['zcode'],'control_mode':'plugin_pre_tool'}))
        connection.chmod(0o600)
        config=json.loads(original)
        events=['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','Stop']
        config['hooks']={'enabled':True,'events':{event:[{'hooks':[{'type':'process','command':str(binary),'args':['aidr-hook','--agent','zcode','--event',event,'--connection-file',str(connection)],'timeoutMs':315000}]}] for event in events}}
        config_path.write_text(json.dumps(config))
        seen=set()
        actions=['allow','deny','timeout','allow']
        first_session=None
        for index,action in enumerate(actions):
            marker=root/'project'/f'{state_root.name}-marker-{0 if index==3 else index}'
            previous=marker.read_text() if marker.exists() else ''
            plan={'tool':'Bash','input':{'command':f'printf x >> {marker}','description':'Create isolated test marker'}}
            (repo/'outputs/zcode-acceptance/plan.json').write_text(json.dumps(plan))
            log=(evidence/f'native-{index}-{action}.txt').open('w');logs.append(log)
            started=time.monotonic()
            native_command=['node','--require',str(root/'isolate.cjs'),'/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs','--cwd',str(root/'project'),'-p',f'AIDR_REQUEST_{index}: Run the single harmless test command.','--json']
            if index==3:native_command+=['--resume',first_session]
            native=subprocess.Popen(native_command,env=native_env,stdout=log,stderr=log)
            deadline=time.monotonic()+30;row=None
            while time.monotonic()<deadline:
                rows=client.get(api+'/hook-approvals').json()['items']
                row=next((r for r in rows if r['id'] not in seen),None)
                if row:break
                assert native.poll() is None, f'native exited before approval: {action}'
                time.sleep(.2)
            assert row and row['state']=='pending'
            seen.add(row['id'])
            assert row['scope']['native_call_id']=='call_aidr_probe' and row['scope']['turn_id']
            assert (marker.read_text() if marker.exists() else '')==previous, 'tool executed before approval'
            if action!='timeout':
                reply=client.post(api+f"/hook-approvals/{row['id']}/decision",json={'request_id':f'{index+1:032x}','expected_revision':row['revision'],'decision':action})
                assert reply.status_code==200,reply.text
            native.wait(timeout=75);native=None
            assert (marker.read_text() if marker.exists() else '')==previous+('x' if action=='allow' else '')
            if index==0:first_session=json.loads((evidence/f'native-{index}-{action}.txt').read_text())['sessionId']
            result.append({'action':action,'marker_exists':marker.exists(),'elapsed_seconds':round(time.monotonic()-started,2),'approval_id':row['id']})
        skill=root/'home/.zcode/skills/aidr-probe/SKILL.md'
        skill.parent.mkdir(parents=True,exist_ok=True)
        skill.write_text('---\nname: aidr-probe\ndescription: Test-only AIDR Skill\n---\nReturn AIDR_SKILL_LOADED. Do not access files or network.\n')
        mcp=root/'mcp.py'
        mcp_marker=root/'project'/f'{state_root.name}-mcp-called'
        mcp.write_text('import sys,json,pathlib\nfor line in sys.stdin:\n r=json.loads(line);m=r.get("method");result={}\n if m=="initialize":result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"aidr-probe","version":"1"}}\n elif m=="tools/list":result={"tools":[{"name":"ping","description":"Harmless AIDR test","inputSchema":{"type":"object","properties":{}}}]}\n elif m=="tools/call":\n  pathlib.Path('+repr(str(mcp_marker))+').write_text("called");result={"content":[{"type":"text","text":"AIDR_MCP_CALLED"}]}\n if "id" in r:print(json.dumps({"jsonrpc":"2.0","id":r["id"],"result":result}),flush=True)\n')
        import sys
        config['mcp']={'servers':{'aidr_probe':{'command':sys.executable,'args':[str(mcp)],'alwaysLoad':True}}}
        config_path.write_text(json.dumps(config))
        cases=[('deny-rule',{'tool':'Write','input':{'file_path':str(root/'project'/f'{state_root.name}-denied-write'),'content':'must not exist'}}),
               ('skill',{'tool':'Skill','input':{'skill':'aidr-probe'}}),
               ('mcp',{'tool':'mcp__aidr_probe__ping','input':{}})]
        for label,plan in cases:
            (repo/'outputs/zcode-acceptance/plan.json').write_text(json.dumps(plan))
            command=['node','--require',str(root/'isolate.cjs'),'/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs','--cwd',str(root/'project'),'-p',f'AIDR_REQUEST_{label}: Run only the requested test tool.','--json']
            run=subprocess.run(command,env=native_env,capture_output=True,timeout=45)
            (evidence/f'native-{label}.txt').write_bytes(run.stdout+run.stderr)
            assert run.returncode==0,run.stderr.decode()
        assert not (root/'project'/f'{state_root.name}-denied-write').exists()
        assert mcp_marker.exists()
        subprocess.run(['go','test','./internal/managedclient','-run','^TestZcodeNativeInventory$','-count=1'],cwd=repo/'scanner',env={**os.environ,'ZCODE_TEST_HOME':str(root/'home'),'ZCODE_INVENTORY_EVIDENCE':str(evidence/'native-inventory.json')},check=True,timeout=30)
        # Rescan after restart and with a new stream: retained logical events deduplicate.
        time.sleep(3)
        processes[1].terminate();processes[1].wait(timeout=10)
        def count():
            with factory() as db:return db.query(models.AidrEvent).count()
        before=count()
        for state in ['log-state','replay-state']:
            replay=subprocess.run([str(binary),'aidr-sync','--state-dir',str(state_root/state),'--source','zcode='+str(root/'home/.zcode/cli/db'),*common,'--duration','5s'],env=env,capture_output=True,timeout=20)
            assert replay.returncode==0,replay.stderr.decode()
            assert count()==before
        events=client.get(api+'/events?limit=100').json()
        approvals=client.get(api+'/hook-approvals').json()
        hooks=client.get(api+'/hooks?limit=100').json()
        assert hooks['items']
        (evidence/'platform-hooks.json').write_text(json.dumps(hooks,ensure_ascii=False,indent=2))
        (evidence/'platform-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
        (evidence/'platform-approvals.json').write_text(json.dumps(approvals,ensure_ascii=False,indent=2))
        (evidence/'acceptance-results.json').write_text(json.dumps({'native':result,'events_before_restart':before,'events_after_replay':count()},indent=2))
        assert before>0 and len(approvals['items'])==len(actions)
    finally:
        config_path.write_text(original)
        for process in [native,*processes]:
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for log in logs:log.close()
        server.should_exit=True;thread.join(timeout=10);listener.close()
