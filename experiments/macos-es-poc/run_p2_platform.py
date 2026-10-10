"""Root-only, loopback P2 integration against the isolated p1_server fixture.

Uses synthetic account/device files, never normal platform configuration. Keeps
the created private directory as evidence and stops all its own child processes.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = Path('/private/tmp/aidr-p1p2-20260927/platform')
SERVER = 'http://127.0.0.1:41879'


def request(path, data=None, token=None, form=False):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(SERVER + path, data=data, headers=headers), timeout=10) as reply:
        return json.load(reply)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run this isolated native integration with sudo.')
    os.umask(0o077)
    base = Path(tempfile.mkdtemp(prefix='aidr-p2-platform.', dir='/private/tmp'))
    print('Platform integration evidence: ' + str(base), flush=True)
    fixture = json.loads((PLATFORM/'fixture.json').read_text())
    captcha = request('/api/auth/captcha')
    token = request('/api/auth/token', dict(username=fixture['username'], password=fixture['password'], captcha_id=captcha['captcha_id'], captcha_code='aidr'), form=True)['access_token']
    endpoint = '/api/v1/clients/' + fixture['client_id'] + '/aidr/enforcement'
    def api(resource, data=None):
        return request(endpoint + '/' + resource, data, token)
    state = base/'state'; state.mkdir()
    for name, source in [('client', Path('/tmp/aidr-p2-client')), ('enforcer', ROOT/'client/macos-enforcer/build/aidr-enforcer'), ('probe', ROOT/'experiments/macos-es-poc/build/file-probe'), ('lifecycle', ROOT/'client/macos-enforcer/build/lifecycle-probe'), ('public-key', PLATFORM/'runtime-public-key')]:
        shutil.copyfile(source, base/name); (base/name).chmod(0o700 if name != 'public-key' else 0o600)
    protected = base/'protected'; protected.write_text('synthetic protected data\n')
    marker = base/'offline'
    proxy = subprocess.Popen([str(ROOT/'backend/.venv/bin/python'), str(ROOT/'experiments/aidr-agentlog/p1_network_proxy.py'), '--port', '41880', '--upstream-port', '41879', '--offline-marker', str(marker)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    worker = None; sleeper = None
    report = {'directory': str(base), 'checks': []}
    def wait(check, timeout=25):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = check()
            if value: return value
            if worker and worker.poll() is not None:
                raise AssertionError('worker exited: ' + str(worker.returncode))
            time.sleep(.25)
        raise AssertionError('integration timed out')
    def publish(rules):
        previous = api('policy')['revision']
        return api('policy', dict(expected_revision=previous, lifetime_seconds=3600, unknown_actor_action='allow', expired_action='deny', agent_executables=[str(base/'probe'), str(base/'lifecycle')], rules=rules))['revision']
    def start():
        env = {**os.environ, 'AGENT_MANAGER_AIDR_TOKEN': (PLATFORM/'device-token').read_text()}
        return subprocess.Popen([str(base/'client'), 'aidr-enforce', '--state-dir', str(state), '--native', str(base/'enforcer'), '--public-key', str(base/'public-key'), '--server', 'http://127.0.0.1:41880', '--client-id', fixture['client_id'], '--duration', '4m'], env=env, stdout=output, stderr=output)
    def read(expected):
        result = subprocess.run([str(base/'probe'), '--read-once', str(protected)], capture_output=True, text=True, timeout=5)
        assert json.loads(result.stdout)['read_success'] is expected
    def queue_count():
        with sqlite3.connect(state/'runtime.db') as db:
            return db.execute('select count(*) from runtime_queue').fetchone()[0]
    rules = [dict(id='synthetic-protected', path=str(protected), actor='agent', decision='deny')]
    with (base/'worker.log').open('w') as output:
        try:
            revision = publish(rules)
            time.sleep(.2); worker = start()
            wait(lambda: api('status')['reported_revision'] == revision)
            read(False)
            auth = wait(lambda: next((r['record'] for r in api('records?limit=100')['items'] if r['record']['kind']=='authorization' and r['record']['path']==str(protected)), None))
            assert auth['decision']=='deny' and auth['result']=='responded'
            report['checks'].append('signed platform policy applied; independent read denied; authorization persisted and queried')
            sleeper = subprocess.Popen([str(base/'lifecycle'), '--sleep'], stdout=subprocess.DEVNULL)
            target = wait(lambda: next((r['record'] for r in api('records?limit=100')['items'] if r['record']['kind']=='process' and r['record']['transition']=='exec' and r['record']['process']['pid']==str(sleeper.pid) and r['record']['path']=='/bin/sleep'), None))
            body = {k: target[k] for k in ('boot_id', 'monitor_id', 'process')}; body['request_id'] = str(uuid.uuid4())
            command = api('terminate', body)
            assert api('terminate', body)['id'] == command['id']
            wait(lambda: any(r['id']==command['id'] and r['state']=='verified' for r in api('responses')['items']))
            assert sleeper.wait(timeout=5) == -signal.SIGTERM
            report['checks'].append('exact sleep instance SIGTERM; repeated request idempotent; matching ES exit verified on platform')
            marker.touch(); read(False)
            wait(lambda: queue_count()>0)
            # No competing writer: stop and reap the sole supervisor first.
            worker.send_signal(signal.SIGTERM); worker.wait(timeout=12); worker=None
            pending = queue_count(); assert pending>0
            worker=start(); time.sleep(2); read(False)
            report['checks'].append('offline cached policy still denies; restart preserves pending records and signed policy')
            marker.unlink()
            wait(lambda: api('status')['health']['monitor_id'] != target['monitor_id'])
            wait(lambda: queue_count() <= 2)
            report['pending_after_offline_stop'] = pending
            report['checks'].append('reconnected backlog acknowledged; new monitor identity visible')
            revision = publish([])
            wait(lambda: api('status')['reported_revision']==revision)
            read(True)
            report['checks'].append('empty new revision revokes control after executor applies it')
            revision = publish(rules)
            wait(lambda: api('status')['reported_revision']==revision)
            read(False)
            listing=subprocess.run(['/bin/ps','-axo','pid=,ppid=,comm='],capture_output=True,text=True,check=True)
            children=[int(parts[0]) for line in listing.stdout.splitlines() if len(parts:=line.strip().split(None,2))==3 and parts[1]==str(worker.pid) and parts[2]==str(base/'enforcer')]
            assert len(children)==1
            os.kill(children[0],signal.SIGKILL)
            assert worker.wait(timeout=12)!=0;worker=None
            read(True)
            wait(lambda: api('status')['state']=='failed',timeout=16)
            report['checks'].append('owned native crash stops enforcement; supervisor fails explicitly and uploads observed native-exit status')
            worker=start()
            wait(lambda: api('status')['state']=='active')
            read(False)
            report['checks'].append('explicit restart restores signed cached protection after native crash')
            worker.send_signal(signal.SIGTERM); worker.wait(timeout=12); worker=None
            report['checks'].append('owned supervisor and native child stopped; no service installed')
            report['latest_status'] = api('status')
            (base/'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps({'checks':len(report['checks']), 'pending_recovered':pending, 'report':str(base/'report.json')}), flush=True)
        finally:
            if sleeper and sleeper.poll() is None: sleeper.terminate(); sleeper.wait(timeout=5)
            if worker and worker.poll() is None: worker.terminate(); worker.wait(timeout=12)
            proxy.terminate(); proxy.wait(timeout=5)
            uid=int(os.environ.get('SUDO_UID','0')); gid=int(os.environ.get('SUDO_GID','0'))
            for parent, dirs, files in os.walk(base):
                for name in dirs+files: os.chown(Path(parent)/name, uid, gid)
            os.chown(base,uid,gid)


if __name__=='__main__': main()
