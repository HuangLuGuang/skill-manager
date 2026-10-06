"""Bounded, root-only P2 native acceptance in a fresh synthetic directory.

Starts only its own sensor; never installs a service or controls existing Agents.
The signing key is generated per run, stays in memory and is never printed.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT=Path(__file__).resolve().parents[2]


def main():
    if os.geteuid()!=0:
        raise SystemExit('Run the bounded native acceptance with sudo.')
    os.umask(0o077)
    base=Path(tempfile.mkdtemp(prefix='aidr-p2-native.',dir='/private/tmp'))
    print('Native test evidence: '+str(base),flush=True)
    state=base/'state';state.mkdir()
    protected=base/'protected';protected.write_text('synthetic protected fixture\n')
    allowed=base/'allowed';allowed.write_text('synthetic allowed fixture\n')
    alias=base/'hard-link';os.link(protected,alias)
    symlink=base/'symbolic-link';symlink.symlink_to(protected)
    probe=base/'file-probe';shutil.copyfile(ROOT/'experiments/macos-es-poc/build/file-probe',probe);probe.chmod(0o700)
    lifecycle=base/'lifecycle-probe';shutil.copyfile(ROOT/'client/macos-enforcer/build/lifecycle-probe',lifecycle);lifecycle.chmod(0o700)
    universal=base/'universal-sleep';shutil.copyfile('/bin/sleep',universal);universal.chmod(0o700)
    key=ec.generate_private_key(ec.SECP256R1())
    pub=base/'public-key';pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))
    events=[];condition=threading.Condition();process=None
    consume=threading.Event();consume.set()
    def sign(value):
        raw=json.dumps(value,separators=(',',':'),sort_keys=True).encode()
        return dict(payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw,ec.ECDSA(hashes.SHA256()))).decode())
    def send(kind,envelope):
        process.stdin.write(json.dumps(dict(type=kind,envelope=envelope))+'\n');process.stdin.flush()
    def wait(predicate,seconds=10):
        until=time.monotonic()+seconds
        with condition:
            while time.monotonic()<until:
                found=predicate(events)
                if found:return found
                if process.poll() is not None:raise AssertionError('native sensor exited: '+str(process.returncode))
                condition.wait(min(.1,max(0,until-time.monotonic())))
        raise AssertionError('native acceptance timed out')
    def snapshot(revision,decision='deny'):
        now=int(time.time())
        return dict(schema=1,device='p2-native-test',revision=str(revision),issued_at=str(now),expires_at=str(now+600),unknown_actor_action='allow',expired_action='deny',agent_executables=[str(probe),str(lifecycle),str(universal)],rules=[dict(id='protected',path=str(protected),actor='agent',decision=decision)])
    def read(path,expected):
        run=subprocess.run([str(probe),'--read-once',str(path)],capture_output=True,text=True,timeout=10)
        result=json.loads(run.stdout)
        assert result['read_success']==expected,(path.name,result)
        return result
    def collect():
        for line in process.stdout:
            consume.wait(timeout=30)
            try:value=json.loads(line)
            except ValueError:continue
            with condition:events.append(value);condition.notify_all()
    report={'scope':'isolated signed native ES process and AUTH_OPEN test','directory':str(base),'checks':[]}
    with (base/'sensor.stderr').open('w') as error:
        try:
            process=subprocess.Popen([str(ROOT/'client/macos-enforcer/build/aidr-enforcer'),str(pub),'p2-native-test',str(state),'120'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error,text=True)
            reader=threading.Thread(target=collect,daemon=True);reader.start()
            wait(lambda rows:any(r['kind']=='health' for r in rows))
            signed=sign(snapshot(1));send('policy',signed)
            wait(lambda rows:any(r['kind']=='policy' and r['revision']=='1' for r in rows))
            universal_child=subprocess.Popen([str(universal),'1'])
            try:
                direct=wait(lambda rows:next((r for r in rows if r['kind']=='process' and r['transition']=='exec' and r['process']['pid']==str(universal_child.pid)),None))
                assert direct['relation']=='direct' and direct['root']==direct['process'],direct['reason_code']
                universal_child.wait(timeout=5)
            finally:
                if universal_child.poll() is None:universal_child.terminate();universal_child.wait(timeout=5)
            report['checks'].append('universal system binary copy recognized by validated architecture-specific signing digest')
            denied=[]
            for _ in range(100):denied.append(read(protected,False))
            for _ in range(100):read(allowed,True)
            read(alias,False);read(symlink,False)
            subprocess.run(['/bin/cat',str(protected)],stdout=subprocess.DEVNULL,check=True,timeout=10)
            report['checks'].append('100 denied and 100 allowed opens; hard-link and symlink denied; non-target cat allowed')
            with ThreadPoolExecutor(max_workers=16) as workers:
                list(workers.map(lambda _:read(protected,False),range(100)))
                list(workers.map(lambda _:read(allowed,True),range(100)))
            report['checks'].append('16 concurrent workers: another 100 protected reads denied and 100 allowed reads succeed')
            # Signature failure leaves the current policy active.
            forged=sign(snapshot(2,'allow'));forged['signature']=base64.b64encode(b'invalid').decode();send('policy',forged)
            wait(lambda rows:any(r['reason_code']=='aidr_enforcement_signature_invalid' for r in rows));read(protected,False)
            send('policy',sign(snapshot(2,'allow')));wait(lambda rows:any(r['kind']=='policy' and r['revision']=='2' for r in rows));read(protected,True)
            send('policy',signed);wait(lambda rows:any(r['reason_code']=='aidr_enforcement_revision_conflict' for r in rows));read(protected,True)
            send('policy',sign(snapshot(3)));wait(lambda rows:any(r['kind']=='policy' and r['revision']=='3' for r in rows));read(protected,False)
            report['checks'].append('invalid signature and stale revision rejected; revoke and new-revision rollback applied')
            workload=subprocess.run([str(lifecycle),'--thousand'],capture_output=True,text=True,check=True,timeout=30)
            expected=[int(x) for x in workload.stdout.splitlines()];assert len(expected)==1000 and len(set(expected))==1000
            expected_set=set(expected)
            wait(lambda rows:len([r for r in rows if r['kind']=='process' and r['transition']=='exit' and int(r['process']['pid']) in expected_set])==1000,20)
            for pid in expected:
                chain=[r for r in events if r['kind']=='process' and int(r['process']['pid'])==pid]
                assert [r['transition'] for r in chain]==['fork','exec','exit'],pid
                assert all(r['relation']=='inherited' and r['root']==chain[0]['root'] for r in chain),pid
                assert chain[1]['process']==chain[2]['process'],pid
            orphan=subprocess.run([str(lifecycle),'--orphan'],capture_output=True,text=True,check=True,timeout=5)
            orphan_pid=orphan.stdout.strip()
            wait(lambda rows:any(r['kind']=='process' and r['transition']=='exit' and r['process']['pid']==orphan_pid for r in rows))
            chain=[r for r in events if r['kind']=='process' and r['process']['pid']==orphan_pid]
            assert [r['transition'] for r in chain]==['fork','exec','exit'] and all(r['relation']=='inherited' for r in chain)
            report['checks'].append('1000 real concurrent children: fork/exec/exit identities match; descendant survives parent exit')
            child=subprocess.Popen([str(lifecycle),'--sleep'])
            try:
                root=wait(lambda rows:next((r for r in rows if r['kind']=='process' and r['transition']=='exec' and r['process']['pid']==str(child.pid) and r['path']=='/bin/sleep'),None))
                import uuid
                command_id=str(uuid.uuid4());now=int(time.time())
                target={k:root[k] for k in ('boot_id','monitor_id','process')}
                # Rule updates must preserve the same already-running root,
                # even when the root selector order changes.
                updated=snapshot(4);updated['agent_executables'].reverse();send('policy',sign(updated))
                wait(lambda rows:any(r['kind']=='policy' and r['revision']=='4' for r in rows))
                request=dict(schema=1,device='p2-native-test',command_id=command_id,action='terminate',issued_at=str(now),expires_at=str(now+60),**target)
                forged_target=json.loads(json.dumps(request));forged_target['command_id']=str(uuid.uuid4());forged_target['process']['pidversion']=str(int(target['process']['pidversion'])+1)
                send('terminate',sign(forged_target))
                wait(lambda rows:any(r.get('command_id')==forged_target['command_id'] and r.get('result')=='rejected' for r in rows));assert child.poll() is None
                signed_command=sign(request);send('terminate',signed_command)
                wait(lambda rows:any(r.get('command_id')==command_id and r.get('result')=='verified' for r in rows))
                assert child.wait(timeout=5)==-signal.SIGTERM
                send('terminate',signed_command)
                wait(lambda rows:len([r for r in rows if r.get('command_id')==command_id])>=3)
                assert len([r for r in events if r.get('command_id')==command_id and r['reason_code']=='aidr_response_signal_sent'])==1
                conflict=json.loads(json.dumps(request));conflict['process']['pidversion']=str(int(target['process']['pidversion'])+1)
                send('terminate',sign(conflict));wait(lambda rows:any(r.get('command_id')==command_id and r['reason_code']=='aidr_response_command_conflict' for r in rows))
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
            report['checks'].append('wrong PID version rejected without signaling; exact audit-token termination verified by ES exit; duplicate does not repeat signal')
            auth=[r for r in events if r['kind']=='authorization']
            assert auth and all(r['result']=='responded' and int(r['deadline_remaining_us'])>0 for r in auth)
            latencies=sorted(int(r['latency_us']) for r in auth)
            report.update(authorizations=len(auth),children=1000,latency_p95_us=latencies[int((len(latencies)-1)*.95)],latency_p99_us=latencies[int((len(latencies)-1)*.99)],latency_max_us=max(latencies))
            assert report['latency_p95_us']<=5000
            assert not any(int(r.get('gaps','0')) for r in events)
            report['checks'].append('root selector reorder preserves exact attribution of a running descendant')
            unknown=snapshot(5);unknown['unknown_actor_action']='deny';send('policy',sign(unknown))
            wait(lambda rows:any(r['kind']=='policy' and r['revision']=='5' for r in rows))
            unregistered=subprocess.run(['/bin/cat',str(protected)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            assert unregistered.returncode!=0
            wait(lambda rows:any(r['kind']=='authorization' and r['process']['pid'] and r['relation']=='unknown' and r['reason_code']=='aidr_enforcement_unknown_actor' and r['decision']=='deny' for r in rows))
            report['checks'].append('unregistered caller has no inferred Agent identity and obeys explicit unknown-actor deny')
            expiring=snapshot(6);expiring['expires_at']=str(int(time.time())+2)
            send('policy',sign(expiring));wait(lambda rows:any(r['kind']=='policy' and r['revision']=='6' for r in rows))
            wait(lambda rows:any(r['reason_code']=='aidr_enforcement_policy_expired' and r['kind']=='health' for r in rows),5)
            read(protected,False)
            report['checks'].append('expired policy reports degradation and applies configured deny to matching resource')
            # A stalled audit consumer must not stall ES authorization. Force
            # more than 1024 queued records, then require an explicit audit gap.
            consume.clear()
            workload=subprocess.run([str(lifecycle),'--thousand'],capture_output=True,text=True,check=True,timeout=30)
            assert len(workload.stdout.splitlines())==1000
            read(protected,False)
            usage=subprocess.run(['/bin/ps','-o','rss=','-p',str(process.pid)],capture_output=True,text=True,check=True)
            report['stalled_consumer_rss_kib']=int(usage.stdout.strip())
            consume.set()
            gap=wait(lambda rows:next((r for r in rows if r['kind']=='health' and r['reason_code']=='aidr_enforcement_audit_gap' and int(r['gaps'])>0),None),10)
            report['audit_gap_count']=int(gap['gaps'])
            report['checks'].append('stalled audit reader exceeds bounded queue: authorization stays responsive, audit loss explicitly reported after recovery')
        finally:
            consume.set()
            if process and process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            if process:
                if process.stdin:process.stdin.close()
                reader.join(timeout=3)
            (base/'events.json').write_text(json.dumps(events,indent=2))
            if os.environ.get('SUDO_UID'):
                uid,gid=int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID'])
                for path in base.rglob('*'):
                    if not path.is_symlink():os.chown(path,uid,gid)
                os.chown(base,uid,gid)
    read_after=subprocess.run([str(probe),'--read-once',str(protected)],capture_output=True,text=True,timeout=10)
    assert json.loads(read_after.stdout)['read_success']
    report['checks'].append('sensor shutdown removes enforcement; protected test file readable')
    (base/'report.json').write_text(json.dumps(report,indent=2))
    if os.environ.get('SUDO_UID'):
        uid,gid=int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID'])
        for path in base.rglob('*'):
            if not path.is_symlink():os.chown(path,uid,gid)
        os.chown(base,uid,gid)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
