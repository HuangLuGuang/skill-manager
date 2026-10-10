"""Bounded, independent expected cases for readable P1 audit acceptance.

Run against p1_server.py on 41877. Real-session paths refer only to this test's
owned temporary Agent sessions. Raw fixtures/credentials remain in evidence/.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import urllib.request
import urllib.parse

BASE=Path(__file__).resolve().parent/'evidence/p1-readable'
ROOT=Path(__file__).resolve().parents[2]
PORT=int(os.environ.get('AIDR_ACCEPTANCE_PORT','41877'))
RUN=BASE/'verified'


def request(path, data=None, token=None, method=None, form=False):
    headers={'Authorization':'Bearer '+token} if token else {}
    if data is not None:
        headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        data=urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{PORT}'+path,data=data,headers=headers,method=method),timeout=20) as response:
        return json.load(response)


def main():
    state=RUN/'platform'
    fixture=json.loads((state/'fixture.json').read_text())
    captcha=request('/api/auth/captcha')
    token=request('/api/auth/token',dict(username=fixture['username'],password=fixture['password'],captcha_id=captcha['captcha_id'],captcha_code='aidr'),form=True)['access_token']
    cid=fixture['client_id'];endpoint=f'/api/v1/clients/{cid}/aidr'
    logs=BASE/'logs'
    for agent in ('claude','codex'):(logs/agent).mkdir(parents=True,exist_ok=True,mode=0o700)
    for name in ('claude','claude-result','claude-exit','codex','codex-exit'):
        path=Path((BASE/(name+'-source-path.txt')).read_text())
        target=logs/('claude' if name.startswith('claude') else 'codex')/(name+'.jsonl')
        shutil.copyfile(path,target);target.chmod(0o600)
    secret='SyntheticSensitive'+('Z'*43)
    expected={}
    records=[]
    def record(kind,call,tool='',args=None,result=None,error=None,session='controlled-a',stamp='2026-09-24T12:00:00Z',meta=None):
        block={'type':'tool_use','id':call,'name':tool,'input':args} if kind=='call' else {'type':'tool_result','tool_use_id':call,'content':result if result is not None else ''}
        if error is not None:block['is_error']=error
        row={'type':'assistant' if kind=='call' else 'user','timestamp':stamp,'sessionId':session,'version':'2.1.220','cwd':'/tmp/aidr-controlled','message':{'content':[block]}}
        if meta is not None:row['toolUseResult']=meta
        records.append(row)
    # Independent expectations are specified before parsing, not derived from it.
    cases=[('ok','Bash',{'command':'/usr/bin/true'},False,None,'command','reported_complete'),
           ('nonzero','Bash',{'command':'/bin/sh -c "exit 7"'},True,'Exit code 7','command','reported_error'),
           ('missing','Read',{'file_path':'/tmp/input.txt'},None,None,'file_read','missing_result'),
           ('cancel','Bash',{'command':'/bin/sleep 30'},True,'cancelled','command','reported_cancelled'),
           ('edit','Edit',{'file_path':'/tmp/input.txt','old_string':secret,'new_string':secret},None,'updated','file_edit','unknown'),
           ('rename','rename_file',{'old_path':'/tmp/input.txt','new_path':'/tmp/renamed.txt'},None,'done','file_rename','unknown'),
           ('private','Bash',{'command':'TOKEN='+secret+' /usr/bin/true; curl -H "Authorization: Bearer '+secret+'" https://example.invalid','password':secret},False,None,'command','reported_complete'),
           ('long','Bash',{'command':'/usr/bin/stat '+('/long-readable-path'*80),'cwd':'/tmp/'+('long-directory-'*34)},False,None,'command','reported_complete')]
    for call,tool,args,error,result,category,status in cases:
        record('call',call,tool,args)
        expected[('controlled-a',call)]={'category':category,'status':status}
        if call!='missing':record('result',call,result=result,error=error,stamp='2026-09-24T12:00:01Z',meta={'interrupted':True} if call=='cancel' else None)
    record('result','late',result='read result',session='controlled-a')
    record('call','late','Read',{'file_path':'/tmp/late.txt'},stamp='2026-09-24T11:59:58Z')
    expected[('controlled-a','late')]={'category':'file_read','status':'unknown'}
    for session in ('controlled-a','controlled-b'):
        record('call','same-id','Read',{'file_path':'/tmp/'+session},session=session)
        expected[(session,'same-id')]={'category':'file_read','status':'missing_result'}
    for i in range(24):
        call='parallel-'+str(i);record('call',call,'Read',{'file_path':f'/tmp/file-{i}'})
        expected[('controlled-a',call)]={'category':'file_read','status':'missing_result'}
    # Raw unknown fields and bodies must never become projected parameters.
    path=logs/'claude/controlled.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in records));path.chmod(0o600)
    late_rows=[{'type':'session_meta','payload':{'id':'late-turn-fixture','cli_version':'0.155.0-alpha.9.2'}},
               {'type':'turn_context','payload':{'turn_id':'first'}},
               {'type':'response_item','payload':{'type':'function_call','name':'exec_command','call_id':'late-code','arguments':'{"cmd":"/usr/bin/true"}'}},
               {'type':'turn_context','payload':{'turn_id':'second'}},
               {'type':'response_item','payload':{'type':'function_call_output','call_id':'late-code','output':[{'type':'input_text','text':'{"exit_code":0}'}]}}]
    for i,row in enumerate(late_rows):row['timestamp']=f'2026-09-24T12:01:0{i}Z'
    path=logs/'codex/late-turn.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in late_rows));path.chmod(0o600)
    request(endpoint+'/configuration',{'enabled':True},token,'PUT')
    cmd=[str(BASE/'agent-manager-client'),'aidr-sync','--state-dir',str(RUN/'local'),'--server',f'http://127.0.0.1:{PORT}','--client-id',cid,'--claude-root',str(logs/'claude'),'--codex-root',str(logs/'codex'),'--since','2026-09-24T00:00:00Z','--duration','8s']
    with (BASE/'sync.json').open('w') as out,(BASE/'sync.log').open('w') as err:
        run=subprocess.run(cmd,env=dict(os.environ,AGENT_MANAGER_AIDR_TOKEN=(state/'device-token').read_text()),stdout=out,stderr=err,timeout=30)
    assert run.returncode==0,'sync failed; inspect private status code'
    rows=[];cursor=''
    while True:
        page=request(endpoint+'/operations?'+urllib.parse.urlencode({'limit':20,'cursor':cursor}),token=token)
        rows+=page['items']
        if not page['has_more']:break
        cursor=page['next_cursor']
    lookup={(r['session_id'],(r['call'] or r['result'])['native_call_id']):r for r in rows}
    for key,value in expected.items():
        row=lookup[key]
        assert row['call']['behavior']['category']==value['category'],key
        assert row['status']==value['status'],(key,row['status'],value['status'])
    assert lookup[('controlled-a','nonzero')]['result']['behavior']['exit_code']==7
    assert lookup[('controlled-a','ok')]['result']['behavior'].get('exit_code') is None
    assert lookup[('controlled-a','private')]['call']['behavior']['redacted']
    late=lookup[('late-turn-fixture','late-code')]
    assert late['call']['turn_id']==late['result']['turn_id']=='first'
    assert late['result']['behavior']['exit_code']==0
    for path in [*(RUN/'local').glob('state.db*'),*(state).glob('platform.db*')]:
        assert secret.encode() not in path.read_bytes(),str(path)
    assert secret not in json.dumps(rows)
    with sqlite3.connect(RUN/'local/state.db') as db:
        assert db.execute('select count(*) from outbox').fetchone()[0]==0
    (BASE/'operations.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    report={'controlled_expected_operations':len(expected),'total_operations':len(rows),'controlled_passed':True,'secret_absent_local_platform_response':True,'outbox':0,'agents':{}}
    for agent in ('claude','codex'):
        real=[r for r in rows if r['agent']==agent and not r['session_id'].startswith('controlled-') and r['session_id']!='late-turn-fixture']
        report['agents'][agent]={'operations':len(real),'readable':sum(bool(r['call'] and r['call'].get('behavior',{}).get('actions')) for r in real),'statuses':{s:sum(r['status']==s for r in real) for s in set(r['status'] for r in real)}}
    (BASE/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
