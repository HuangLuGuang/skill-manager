"""Bounded real executor for manual browser acceptance on the isolated fixture.

Run with sudo in a terminal. Commands: probe, sleep, hold, release, status, crash, finish.
Only owned synthetic files and child processes are touched. No fixture replies
stand in for policy, authorization, termination, or expiry evidence.
"""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from run_p2_platform import ROOT, PLATFORM, request


def main():
    if os.geteuid() != 0 or not os.environ.get('SUDO_UID'):
        raise SystemExit('Run with sudo from the test user.')
    os.umask(0o077)
    uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
    base = Path(tempfile.mkdtemp(prefix='aidr-p2-browser.', dir='/private/tmp'))
    work = Path(tempfile.mkdtemp(prefix='aidr-p2-browser-work.', dir='/private/tmp'))
    protected = work / ('long-path-' + 'a' * 80) / ('evidence-' + 'b' * 80) / 'protected.txt'
    protected.parent.mkdir(parents=True)
    protected.write_text('synthetic browser acceptance\n')
    allowed = work / 'allowed.txt'
    allowed.write_text('synthetic browser acceptance\n')
    for parent, dirs, files in os.walk(work):
        for name in dirs + files:
            os.chown(Path(parent) / name, uid, gid)
    os.chown(work, uid, gid)
    for name, source in [('client', Path('/tmp/aidr-p2-client')), ('enforcer', ROOT/'client/macos-enforcer/build/aidr-enforcer'), ('probe', ROOT/'experiments/macos-es-poc/build/file-probe'), ('sleep', Path('/bin/sleep')), ('public-key', PLATFORM/'runtime-public-key')]:
        shutil.copyfile(source, base/name)
        (base/name).chmod(0o700 if name != 'public-key' else 0o600)
    state = base/'state'
    state.mkdir()
    fixture = json.loads((PLATFORM/'fixture.json').read_text())
    captcha = request('/api/auth/captcha')
    token = request('/api/auth/token', dict(username=fixture['username'], password=fixture['password'], captcha_id=captcha['captcha_id'], captcha_code='aidr'), form=True)['access_token']
    endpoint = '/api/v1/clients/' + fixture['client_id'] + '/aidr/enforcement'
    previous = request(endpoint+'/policy', token=token)
    (base/'previous-policy.json').write_text(json.dumps(previous))
    policy = dict(expected_revision=previous['revision'], lifetime_seconds=3600,
                  unknown_actor_action='allow', expired_action='deny',
                  agent_executables=[str(base/'probe'), str(base/'sleep')],
                  rules=[dict(id='browser-protected', path=str(protected), actor='agent', decision='deny')])
    published = request(endpoint+'/policy', policy, token)
    token = None  # Browser login may now replace this session; no further admin requests.
    blocked = base/'blocked-route'
    report = dict(directory=str(base), workspace=str(work), protected=str(protected), allowed=str(allowed),
                  roots=policy['agent_executables'], initial_revision=published['revision'], observations=[])
    proxy = worker = None
    children = []
    with (base/'worker.log').open('w') as log:
        try:
            proxy = subprocess.Popen([str(ROOT/'backend/.venv/bin/python'), str(ROOT/'experiments/aidr-agentlog/p1_network_proxy.py'), '--port', '41880', '--upstream-port', '41879', '--offline-marker', str(base/'offline'), '--blocked-route-marker', str(blocked)], stdout=log, stderr=log)
            time.sleep(.3)
            if proxy.poll() is not None:
                raise RuntimeError('isolated proxy could not start')
            env = {**os.environ, 'AGENT_MANAGER_AIDR_TOKEN': (PLATFORM/'device-token').read_text()}
            worker = subprocess.Popen([str(base/'client'), 'aidr-enforce', '--state-dir', str(state), '--native', str(base/'enforcer'), '--public-key', str(base/'public-key'), '--server', 'http://127.0.0.1:41880', '--client-id', fixture['client_id'], '--duration', '15m'], env=env, stdout=log, stderr=log)
            print(json.dumps(report), flush=True)
            print('Commands: probe | sleep | hold | release | status | crash | finish. Stops automatically after 15 minutes.', flush=True)
            end = time.monotonic() + 900
            while time.monotonic() < end:
                if worker.poll() is not None:
                    raise RuntimeError('executor exited before acceptance completed')
                if not select.select([sys.stdin], [], [], .25)[0]:
                    continue
                line = sys.stdin.readline()
                if not line:
                    break
                command = line.strip()
                if command == 'finish':
                    break
                observation = dict(command=command, at=time.time())
                if command == 'probe':
                    for name, path in [('protected', protected), ('allowed', allowed)]:
                        result = subprocess.run([str(base/'probe'), '--read-once', str(path)], capture_output=True, text=True, timeout=5)
                        observation[name] = json.loads(result.stdout)
                    independent = subprocess.run(['/bin/cat', str(protected)], user=uid, group=gid, capture_output=True, timeout=5)
                    observation['independent_user_read'] = independent.returncode == 0 and independent.stdout == b'synthetic browser acceptance\n'
                elif command == 'sleep':
                    child = subprocess.Popen([str(base/'sleep'), '600'], stdout=log, stderr=log)
                    children.append(child)
                    observation.update(pid=child.pid, executable=str(base/'sleep'))
                elif command == 'hold':
                    blocked.write_text(endpoint+'/commands')
                elif command == 'release':
                    blocked.unlink(missing_ok=True)
                elif command == 'status':
                    observation['children'] = [dict(pid=c.pid, exit=c.poll()) for c in children]
                elif command == 'crash':
                    processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,comm='], text=True)
                    owned = []
                    for process in processes.splitlines():
                        fields = process.strip().split(None, 2)
                        if len(fields) == 3 and fields[1] == str(worker.pid) and fields[2] == str(base/'enforcer'):
                            owned.append(int(fields[0]))
                    if len(owned) != 1:
                        raise RuntimeError('could not uniquely confirm owned native child')
                    os.kill(owned[0], signal.SIGKILL)
                    observation.update(native_pid=owned[0], supervisor_exit=worker.wait(timeout=12))
                else:
                    print('Unknown command', flush=True)
                    continue
                report['observations'].append(observation)
                print(json.dumps(observation), flush=True)
                if command == 'crash':
                    break
        finally:
            report['children_before_cleanup'] = [dict(pid=c.pid, exit=c.poll()) for c in children]
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
            if worker and worker.poll() is None:
                worker.send_signal(signal.SIGTERM)
                worker.wait(timeout=12)
            if proxy and proxy.poll() is None:
                proxy.terminate()
                proxy.wait(timeout=5)
            report['children_reaped'] = all(c.poll() is not None for c in children)
            report['executor_reaped'] = worker is None or worker.poll() is not None
            (base/'report.json').write_text(json.dumps(report, indent=2))
            for parent, dirs, files in os.walk(base):
                for name in dirs + files:
                    os.chown(Path(parent)/name, uid, gid)
            os.chown(base, uid, gid)
            print('Evidence: ' + str(base/'report.json'), flush=True)


if __name__ == '__main__':
    main()
