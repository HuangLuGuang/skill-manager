"""Isolated HTTP + Go collector acceptance; synthetic logs, not a real Agent run.

Requires p1_server.py on 41879 and /tmp/aidr-redaction-client. Never targets a
user database or changes the user's running collector. Credentials stay private.
"""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request

STATE = Path('/tmp/aidr-redaction-20260926').resolve()
SERVER = 'http://127.0.0.1:41879'
COMMAND = 'git commit -m "fix scanner ownership across client credential rotation" && git status --short --branch'
SECRET = 'AIDR_SYNTHETIC_NOT_A_CREDENTIAL_260926'


def request(path, data=None, token=None, method=None, form=False):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(SERVER + path, data=data, headers=headers, method=method), timeout=20) as response:
        return json.load(response)


def main():
    fixture = json.loads((STATE / 'fixture.json').read_text())
    captcha = request('/api/auth/captcha')
    token = request('/api/auth/token', dict(username=fixture['username'], password=fixture['password'], captcha_id=captcha['captcha_id'], captcha_code='aidr'), form=True)['access_token']
    endpoint = f"/api/v1/clients/{fixture['client_id']}/aidr"
    original = request('/api/system/aidr-redaction', token=token)
    run = STATE / ('collection-' + str(time.time_ns()))
    for folder in (run, run/'claude', run/'codex'):
        folder.mkdir(mode=0o700)
    source = run/'claude'/'controlled.jsonl'
    source.touch(mode=0o600)
    env = {**os.environ, 'AGENT_MANAGER_AIDR_TOKEN': (STATE/'device-token').read_text()}
    command = ['/tmp/aidr-redaction-client', 'aidr-sync', '--state-dir', str(run/'store'), '--server', SERVER, '--client-id', fixture['client_id'], '--claude-root', str(run/'claude'), '--codex-root', str(run/'codex')]
    session = 'redaction-' + run.name
    def append(call, command):
        stamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        rows=[dict(type='assistant',timestamp=stamp,sessionId=session,version='2.1.220',message={'content':[dict(type='tool_use',id=call,name='Bash',input={'command':command})]}),dict(type='user',timestamp=stamp,sessionId=session,version='2.1.220',message={'content':[dict(type='tool_result',tool_use_id=call,content='Exit code 0',is_error=False)]},toolUseResult={'exit_code':0})]
        with source.open('a') as f:
            for row in rows:f.write(json.dumps(row)+'\n')
    def wait_for(predicate):
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            value=predicate()
            if value:return value
            time.sleep(.5)
        raise AssertionError('acceptance_timeout')
    def policy_applied(version):
        dbpath=run/'store/state.db'
        if not dbpath.exists():return False
        with sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True) as db:
            row=db.execute("select value from metadata where key='audit_policy'").fetchone()
            return row and json.loads(row[0])['version']==version
    def operations():return request(endpoint+'/operations?session='+session,token=token)['items']
    def switch(enabled):
        before=request('/api/system/aidr-redaction',token=token)
        after=request('/api/system/aidr-redaction',dict(enabled=enabled,version=before['version']),token,'PUT')
        wait_for(lambda:policy_applied(after['version']))
        return after
    process=None
    report={'scope':'isolated synthetic log transport; real HTTP, Go binary and SQLite','session':session,'checks':[]}
    with (run/'collector.log').open('w') as output:
        try:
            process=subprocess.Popen(command,env=env,stdout=output,stderr=output)
            on=switch(True)
            append('on-git',COMMAND);append('on-secret','tool --password "'+SECRET+'" && git status')
            wait_for(lambda:len(operations())==2)
            with sqlite3.connect(f'file:{run}/store/state.db?mode=ro',uri=True) as db:
                values=[row[0] for row in db.execute('select payload from logical_events')]
                assert not any(SECRET in value for value in values)
            report['checks'].append('ON local persistence contains no synthetic secret')
            off=switch(False)
            append('off-git',COMMAND);append('off-secret','tool --password "'+SECRET+'" && git status')
            wait_for(lambda:len(operations())==4)
            resumed=switch(True)
            append('on-again','tool --password "'+SECRET+'" && git status')
            wait_for(lambda:len(operations())==5)
            rows=operations();by_call={row['call']['native_call_id']:row for row in rows}
            for call in ('on-git','off-git'):assert by_call[call]['call']['behavior']['actions'][0]['command']==COMMAND
            for call in ('on-secret','on-again'):assert SECRET not in json.dumps(by_call[call])
            assert SECRET in by_call['off-secret']['call']['behavior']['actions'][0]['command']
            assert by_call['on-secret']['call']['behavior']['policy']['version']==on['version']
            assert by_call['off-secret']['call']['behavior']['policy']['version']==off['version']
            with sqlite3.connect(f'file:{run}/store/state.db?mode=ro',uri=True) as db:
                local=[json.loads(row[0]) for row in db.execute('select payload from logical_events')]
                for event in local:
                    if event['native_call_id'] in ('on-git','off-git') and event['kind']=='tool_call':
                        assert event['behavior']['actions'][0]['command']==COMMAND
            report['checks']+=['live 30-second refresh ON/OFF/ON','exact git command roundtrip','old ON and OFF history unchanged','call/result merge: 10 events -> 5 operations']
            process.send_signal(signal.SIGTERM);process.wait(timeout=15);assert process.returncode==0
            process=subprocess.Popen(command+['--duration','5s'],env=env,stdout=output,stderr=output)
            process.wait(timeout=20);assert process.returncode==0
            assert len(operations())==5
            report['checks'].append('restart retains policy and does not duplicate operations')
            report.update(versions=[on['version'],off['version'],resumed['version']],operations=5,events=10)
        finally:
            if process and process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=15)
            before=request('/api/system/aidr-redaction',token=token)
            if before['enabled']!=original['enabled']:
                request('/api/system/aidr-redaction',dict(enabled=original['enabled'],version=before['version']),token,'PUT')
    (STATE/'redaction-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':main()
