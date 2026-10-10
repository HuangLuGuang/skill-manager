"""Device-only HTTP/CLI acceptance, including a real legacy frozen queue.

Uses isolated p1_server instances on 41873/41875 and private evidence fixtures.
Reads actual Claude JSONL; never prints or embeds credentials.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import urllib.request
import urllib.parse

root = Path(__file__).resolve().parents[2]
base = root / 'experiments/aidr-agentlog/evidence/p1-full'
upgrade, fresh = base/'device-auth-upgrade', base/'device-auth-fresh'
source = Path((base/'claude-retest-source-path.txt').read_text().strip())
report = {}


def request(port, path, data=None, token=None, method=None, form=False):
    headers = {'Authorization': 'Bearer '+token} if token else {}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)


def login(port, state):
    f=json.loads((state/'fixture.json').read_text())
    captcha=request(port,'/api/auth/captcha')
    reply=request(port,'/api/auth/token',{'username':f['username'],'password':f['password'],'captcha_id':captcha['captcha_id'],'captcha_code':'aidr'},form=True)
    return reply['access_token']


def sync(binary, state, port, cid, token, old=False):
    empty=state.parent/'empty-codex';empty.mkdir(exist_ok=True)
    cmd=[str(binary),'aidr-sync','--state-dir',str(state),'--server',f'http://127.0.0.1:{port}','--client-id',cid,'--claude-root',str(source.parent),'--claude-file',str(source),'--codex-root',str(empty),'--since','2026-09-23T00:00:00Z','--duration','5s']
    if old:cmd+=['--department-id','1'] # Preserved old binary interface, migration fixture only.
    result=subprocess.run(cmd,env=dict(os.environ,AGENT_MANAGER_AIDR_TOKEN=token),capture_output=True,text=True,timeout=25)
    (state.parent/(state.name+'-stdout.json')).write_text(result.stdout)
    (state.parent/(state.name+'-stderr.log')).write_text(result.stderr)
    assert result.returncode==0, (result.returncode, result.stderr)


def snapshot(path):
    with sqlite3.connect('file:'+str(path/'state.db')+'?mode=ro',uri=True) as db:
        return {'metadata':dict(db.execute("SELECT key,value FROM metadata WHERE key IN ('destination','destination_version','stream_id')")),
                'frozen':db.execute('SELECT id,digest,payload,through_seq FROM active_batch').fetchall(),
                'sources':db.execute('SELECT id,cursor,coverage,revision FROM sources ORDER BY id').fetchall(),
                'queued':db.execute('SELECT count(*) FROM outbox').fetchone()[0]}

admin=login(41873,upgrade)
cid='aidr-p1-claude'
new=request(41873,'/api/access/tokens',{'name':'AIDR device upgrade acceptance','token_type':'client','bound_client_id':cid,'scopes':['aidr:heartbeat','aidr:report-events']},admin)
assert new['record']['group_id'] is None
legacy=upgrade/'legacy-local'
sync(base/'agent-manager-client-next',legacy,41873,cid,new['token'],old=True)
before=snapshot(legacy)
assert before['frozen'] and before['queued']>0 and 'destination_version' not in before['metadata']
# Snapshot remains available as evidence; do not modify its batch body/digest.
with sqlite3.connect(legacy/'state.db') as db,sqlite3.connect(upgrade/'legacy-before.db') as backup:db.backup(backup)
page=request(41873,f'/api/v1/clients/{cid}/aidr/events?limit=500',token=admin)
count=len(page['items'])
sync(upgrade/'agent-manager-client',legacy,41873,cid,new['token'])
after=snapshot(legacy)
assert after['queued']==0 and not after['frozen']
assert before['metadata']['stream_id']==after['metadata']['stream_id']
# Source revisions may increase on no-op reads; initial offsets/generation must stay stable.
assert [json.loads(x[1])['offset'] for x in before['sources']]==[json.loads(x[1])['offset'] for x in after['sources']]
assert len(request(41873,f'/api/v1/clients/{cid}/aidr/events?limit=500',token=admin)['items'])==count
with sqlite3.connect(upgrade/'platform.db') as db:
    for bid,digest,raw,seq in before['frozen']:
        row=db.execute('SELECT digest FROM aidr_batches WHERE client_id=? AND stream_id=? AND batch_id=?',(cid,before['metadata']['stream_id'],bid)).fetchone()
        assert row==(digest,) and hashlib.sha256(raw).hexdigest()==digest
report['legacy']={'queued_before':before['queued'],'queued_after':after['queued'],'frozen_digest_preserved':True,'events_before_and_after':count,'stream_and_cursor_preserved':True,'destination_version':after['metadata']['destination_version']}

admin=login(41875,fresh)
cid=json.loads((fresh/'fixture.json').read_text())['client_id']
with sqlite3.connect(fresh/'platform.db') as db:
    assert db.execute('select count(*) from user_groups').fetchone()[0]==0
    assert db.execute('select group_id from access_tokens').fetchone()[0] is None
request(41875,f'/api/v1/clients/{cid}/aidr/configuration',{'enabled':True},admin,'PUT')
sync(upgrade/'agent-manager-client',fresh/'actual-local',41875,cid,(fresh/'device-token').read_text())
events=request(41875,f'/api/v1/clients/{cid}/aidr/events?limit=500',token=admin)['items']
expected=json.loads((base/'claude-retest-expected.json').read_text())
calls={v['event']['native_call_id'] for v in events if v['event']['kind']=='tool_call'}
results={v['event']['native_call_id'] for v in events if v['event']['kind']=='tool_result'}
assert calls==results=={v['id'] for v in expected['calls']}
assert snapshot(fresh/'actual-local')['queued']==0
report['fresh']={'groups':0,'credential_group_id':None,'tool_calls':len(calls),'tool_results':len(results),'outbox':0,'actual_source':'Claude 2.1.220 real session'}
(fresh/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
