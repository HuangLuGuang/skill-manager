"""Isolated page API reads; synthetic fixtures, no existing server or database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=30)
    args = parser.parse_args()
    if os.environ.get('BENCHMARK_ISOLATED') != 'YES':
        raise SystemExit('BENCHMARK_ISOLATED=YES is required')
    sys.path.insert(0, str(args.source_root.resolve()))
    with tempfile.TemporaryDirectory(prefix='page-benchmark-') as directory:
        os.environ['SQLITE_PATH'] = str(Path(directory) / 'pages.db')
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import event
        import psutil
        from backend import auth, iam, models
        from backend.api_errors import ApiError, api_error_handler
        from backend.config import settings
        from backend.sqlite_db import Base, engine, SessionLocal, get_db
        from backend.routers import clients, agents, dashboard, runtime_traces, security_scans, aidr
        from backend.aidr_migrations import upgrade_aidr_schema
        from backend.aidr_models import AidrEvent, AidrHookEvent
        settings.RUNTIME_TRACE_ENABLED = True
        settings.AGENT_SECURITY_SCANNING_ENABLED = True
        Base.metadata.create_all(engine)
        upgrade_aidr_schema(engine)
        now = datetime.utcnow()
        with SessionLocal() as db:
            iam.initialize(db)
            db.add(models.User(id=1, username='benchmark', hashed_password='unused', role='super_admin'))
            db.add(models.UserGroup(id=1, name='benchmark'))
            for i in range(100):
                cid = f'client-{i:03}'
                db.add(models.ManagedClient(client_id=cid, name=cid, hostname=cid, os='darwin', arch='arm64', client_version='test', registered_by='benchmark'))
                db.add(models.ManagedAgent(agent_id=cid, name=cid, created_by='benchmark', department_group_id=1))
                db.add(models.ClientAgent(client_id=cid, agent_type='codex'))
                db.add(models.AidrDevice(client_id=cid, created_by='benchmark'))
                for j in range(10):
                    db.add(models.ClientSkillInstall(client_id=cid, agent_type='codex', skill_name=f'skill-{j}', skill_path=f'/skills/{j}'))
            db.flush()
            for i in range(100):
                cid = f'client-{i:03}'
                db.execute(models.ClientEvent.__table__.insert(), [dict(client_id=cid, agent_type='codex', skill_name=f'skill-{j%10}', event_type='skill_modified', details_json='{}') for j in range(500)])
                db.execute(AidrEvent.__table__.insert(), [dict(client_id=cid, logical_id=f'{i:04x}{j:060x}', content_hash='a'*64, agent='codex', kind='tool_call', payload_json='{}', received_at=now) for j in range(500)])
                db.execute(AidrHookEvent.__table__.insert(), [dict(client_id=cid, stream_id='b'*32,
                    event_id=f'{i:04x}{j:028x}', source_seq=j+1, content_hash='a'*64, received_at=now,
                    payload_json=json.dumps(dict(user_scope='501', received_at=now.isoformat()+'Z', event=dict(
                        agent='codex', session_id=f'session-{j//10}', turn_id=f'turn-{j}', kind='tool.pre',
                        hook_event='PreToolUse', native_call_id=str(j), tool='Bash',
                        contents=[dict(kind='prompt', text='x'*1024)])))) for j in range(500)])
            db.add(models.RuntimeTraceSession(trace_id='trace', tenant_id='bench', session_id='session', expires_at=now+timedelta(days=1)))
            db.flush()
            db.execute(models.RuntimeTraceEvent.__table__.insert(), [dict(event_id=f'e-{i}', trace_id='trace', seq=i+1, content_fingerprint='a'*64, tenant_id='bench', session_id='session', source='agent_sdk', type='tool.result', event_time=now, payload_id=f'p-{i}') for i in range(1000)])
            db.execute(models.RuntimeTracePayload.__table__.insert(), [dict(payload_id=f'p-{i}', trace_id='trace', event_id=f'e-{i}', raw_payload_encrypted='x'*65536, redacted_json='{"summary":"redacted"}', raw_sha256='a'*64, size_bytes=65536, expires_at=now+timedelta(days=1)) for i in range(1000)])
            db.execute(models.SecurityScanTask.__table__.insert(), [dict(task_id=f't-{i}', target_id='synthetic', policy_id='synthetic', status='succeeded', idempotency_key=f't-{i}', request_fingerprint='a'*64, created_by='benchmark', timeout_at=now+timedelta(days=1)) for i in range(100)])
            db.commit()

        class Manager:
            def dashboard_stats(self):
                return dict(total=0, risk_counts={}, status_counts={}, todos=[])
            def audit(self, **kwargs):
                return []

        app = FastAPI()
        app.add_exception_handler(ApiError, api_error_handler)
        user = models.User(id=1, username='benchmark', role='super_admin', is_active=True)
        app.dependency_overrides[auth.get_current_admin_user] = lambda: user
        app.dependency_overrides[auth.get_current_active_user] = lambda: user
        app.dependency_overrides[dashboard.get_manager] = lambda: Manager()
        for module in (clients, agents, dashboard, runtime_traces, security_scans, aidr):
            app.include_router(module.router, prefix='/api')
        paths = {
            'clients': '/api/v1/clients',
            'agents': '/api/agents',
            'agent_assets': '/api/agents/assets',
            'dashboard': '/api/v1/dashboard/overview',
            'runtime_list': '/api/v1/runtime-traces',
            'runtime_events': '/api/v1/runtime-traces/trace/events',
            'scan_tasks': '/api/v1/agent-security/tasks',
            'aidr_status': '/api/v1/clients/client-000/aidr/status?include_retention=false',
            'aidr_sessions': '/api/v1/clients/client-000/aidr/sessions',
        }
        results = {}
        environment = dict(idle_cpu_percent=psutil.cpu_percent(interval=3),
                           available_gib=psutil.virtual_memory().available / 2**30,
                           load_average=os.getloadavg())
        with TestClient(app) as client:
            for name, path in paths.items():
                samples, counts = [], []
                statements = []
                def observe(_conn, _cursor, sql, *_):
                    statements.append(sql)
                event.listen(engine, 'before_cursor_execute', observe)
                try:
                    for iteration in range(args.iterations + 2):
                        statements.clear()
                        start = time.perf_counter()
                        response = client.get(path)
                        elapsed = (time.perf_counter() - start)*1000
                        if response.status_code != 200:
                            raise RuntimeError(f'{name}: {response.status_code} {response.text[:500]}')
                        body = response.json()
                        if name == 'clients':
                            assert len(body) == 100 and all(row['issue_count'] == 10 for row in body)
                        if name == 'aidr_sessions':
                            assert len(body['items']) == 20 and body['has_more']
                        if name == 'dashboard':
                            assert body['runtime']['aidr']['records'] == 100000
                            assert body['runtime']['aidr']['reporting_clients'] == 100
                        if iteration >= 2:
                            samples.append(elapsed)
                            counts.append(len(statements))
                    results[name] = dict(p50_ms=statistics.median(samples), p95_ms=sorted(samples)[int((len(samples)-1)*.95)],
                                         samples_ms=samples, sql_count=statistics.median(counts), response_bytes=len(response.content))
                    print(name, json.dumps({k:v for k,v in results[name].items() if k != 'samples_ms'}), flush=True)
                finally:
                    event.remove(engine, 'before_cursor_execute', observe)
        engine.dispose()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {str(path.relative_to(args.source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for folder in ('backend', 'agent_manager') for path in (args.source_root / folder).rglob('*.py')}
        args.output.write_text(json.dumps(dict(results=results, iterations=args.iterations, source_manifest=manifest, environment=environment,
            fixture=dict(clients=100, agents=100, skills_per_client=10, client_events=50000, aidr_logs=50000, aidr_hooks=50000,
                         runtime_events=1000, raw_bytes_per_event=65536, scan_tasks=100),
            limitations=['isolated TestClient API timing, not browser/network latency', 'authentication dependency replaced with synthetic admin; route permission checks retained',
                         'empty registry dashboard stub; no upload/audit/cleanup concurrency', 'warm cache; synthetic data']), indent=2))


if __name__ == '__main__':
    main()
