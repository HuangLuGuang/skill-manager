"""Lifecycle authorization, bounded expiry and immutable replay expectations."""
import copy
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from backend import auth, iam, models
from backend.aidr_enforcement import AidrRuntimeRecord
from backend.aidr_models import AidrHookEvent
from backend.aidr_retention import expire_once
from backend.routers import aidr_enforcement, system
from tests.test_aidr_api import service, submit
from tests.test_aidr_content import configure, event_batch
from tests.test_aidr_enforcement import event as runtime_event
from tests.test_aidr_hooks import hook_batch, send
from tests.test_aidr_operations import event as operation_event, upload, operations


def test_background_expiry_releases_connection_between_tables(service, monkeypatch):
    from backend import aidr_retention, sqlite_db
    from backend.aidr_models import AidrOperation
    from backend.services.gateway_db import run_sync
    client, factory = service
    configure(factory, lifecycle={'enabled': True, 'retention_days': 1})
    assert upload(client, operation_event('tool_call')).status_code == 200
    with factory() as db:
        for model in (models.AidrEvent, AidrOperation):
            db.query(model).update({'received_at': datetime.utcnow() - timedelta(days=2)})
        db.commit()
    engine = factory.kw['bind']
    interleaved = []

    async def step(function, *args):
        result = await run_sync(function, *args)
        assert engine.pool.checkedout() == 0
        await run_sync(interleaved.append, True)
        return result

    monkeypatch.setattr(sqlite_db, 'SessionLocal', factory)
    monkeypatch.setattr(aidr_retention, 'run_sync', step)
    async def scenario():
        assert await asyncio.wait_for(aidr_retention.cleanup_once(), 3) is False
    asyncio.run(scenario())
    assert len(interleaved) >= 2
    with factory() as db:
        row = db.query(models.AidrEvent).one()
        assert row.expired_at and row.payload_json == '{}'


def lifecycle_policy(client, sequence='0', **applied):
    response = client.post('/api/v1/clients/one/aidr/audit-policy',
        json=dict(stream_id='a'*32, last_sequence=sequence, **applied),
        headers={'authorization':'Bearer test-one', 'X-AIDR-Policy-Schema':'2', 'X-AIDR-Audit-Lifecycle':'1'})
    assert response.status_code == 200, response.text
    return response.json()


def test_expired_call_is_not_resurrected_by_replay_or_late_result(service):
    client, factory = service
    configure(factory, lifecycle={'enabled':True,'retention_days':1})
    call = operation_event('tool_call')
    assert upload(client, call).status_code == 200
    with factory() as db:
        expire_once(db, datetime.utcnow()+timedelta(days=2))
    assert not operations(client)['items']
    assert upload(client, call).status_code == 200
    assert not operations(client)['items']
    result = operation_event('tool_result')
    assert upload(client, result).status_code == 200
    row = operations(client)['items'][0]
    assert row['history_expired'] is True
    assert row['call'] is None and row['result']['logical_event_id'] == result['logical_event_id']
    assert row['status'] == 'missing_call' and row['process_relation'] == 'unknown'
    assert upload(client, call, result).status_code == 200
    assert len(operations(client)['items']) == 1 and operations(client)['items'][0]['call'] is None


def test_platform_expiry_does_not_exceed_per_table_budget(service):
    _, factory = service
    from backend.aidr_models import AidrOperation
    now = datetime.utcnow()
    with factory() as db:
        db.add_all([AidrOperation(client_id='one', operation_key=f'{i:064x}', agent='codex', session_id='synthetic-session', tool='exec', result_status='unknown', latest_at='2026-09-24T00:00:00+00:00', payload_json='{"call":null,"result":null}', received_at=now-timedelta(days=8)) for i in range(501)])
        db.commit()
        counts = expire_once(db, now)
        assert counts['aidr_operations'] == 500
        assert db.query(AidrOperation).filter(AidrOperation.expired_at.is_(None)).count() == 1
        assert expire_once(db, now)['aidr_operations'] == 1


def test_retention_commits_completed_tables_and_resumes_after_failure(service, monkeypatch):
    from backend import aidr_overview
    _, factory = service
    now = datetime.utcnow()
    with factory() as db:
        db.add(models.AidrEvent(client_id='one', logical_id='a' * 64, content_hash='original-log-hash',
            agent='codex', kind='tool_call', payload_json='{"body":"old"}', received_at=now-timedelta(days=8)))
        db.add(AidrHookEvent(client_id='one', stream_id='a' * 32, event_id='b' * 32, source_seq=1,
            content_hash='original-hook-hash', payload_json='{"body":"old"}', received_at=now-timedelta(days=8)))
        db.commit()
    original_remove = aidr_overview.remove_evidence

    def fail_hooks(db, source, ids):
        if source == 'hooks':
            raise RuntimeError('injected maintenance failure')
        return original_remove(db, source, ids)

    monkeypatch.setattr(aidr_overview, 'remove_evidence', fail_hooks)
    with factory() as db:
        with pytest.raises(RuntimeError):
            expire_once(db, now)
        db.rollback()
    with factory() as db:
        assert db.query(models.AidrEvent).one().payload_json == '{}'
        assert db.query(AidrHookEvent).one().expired_at is None
    monkeypatch.setattr(aidr_overview, 'remove_evidence', original_remove)
    with factory() as db:
        counts = expire_once(db, now)
        assert counts['aidr_events'] == 0 and counts['aidr_hook_events'] == 1
        assert db.query(AidrHookEvent).one().payload_json == '{}'
        assert db.query(models.AidrEvent).one().content_hash == 'original-log-hash'
        assert db.query(AidrHookEvent).one().content_hash == 'original-hook-hash'


def test_lifecycle_defaults_negotiation_forgery_and_backlog(service):
    client, factory = service
    policy = lifecycle_policy(client)
    assert policy['lifecycle'] == {'enabled':True,'retention_days':7}
    legacy = client.post('/api/v1/clients/one/aidr/audit-policy', json={'stream_id':'a'*32,'last_sequence':'0'}, headers={'authorization':'Bearer test-one'}).json()
    assert 'capture' not in legacy and 'lifecycle' not in legacy
    configure(factory, lifecycle={'enabled':True,'retention_days':2})
    policy = lifecycle_policy(client)
    pending = event_batch(policy)
    pending['records'][0]['payload']['behavior']['version'] = 5
    configure(factory, version='3', lifecycle={'enabled':False,'retention_days':2})
    off = lifecycle_policy(client, '1', applied_receipt=policy['receipt'], applied_after='0')
    assert off['lifecycle']['enabled'] is False
    assert submit(client, pending).status_code == 200  # legitimate pre-switch backlog
    forged = copy.deepcopy(pending)
    forged['records'][0]['payload']['behavior']['policy'] = {**off,'lifecycle':{'enabled':True,'retention_days':2}}
    forged['records'][0]['sequence'] = '2'
    assert submit(client, forged).status_code == 409
    forbidden = copy.deepcopy(pending)
    forbidden['records'][0]['payload']['behavior']['policy'] = off
    assert submit(client, forbidden).status_code == 422
    assert submit(client, pending).status_code == 200


def test_retention_bounded_expiry_preserves_hashes_ack_and_pending_identity(service):
    client, factory = service
    configure(factory, lifecycle={'enabled':True,'retention_days':1})
    policy = lifecycle_policy(client)
    value = event_batch(policy)
    value['records'][0]['payload']['behavior']['version'] = 5
    ack = submit(client,value).json()
    hook = hook_batch()
    hook['stream_id'] = 'a'*32
    hook['records'][0]['event'].update(schema_version=3, policy=policy, content_status='not_requested')
    hook_ack = send(client,hook)
    assert hook_ack.status_code == 200, hook_ack.text
    client.app.include_router(aidr_enforcement.router,prefix='/api')
    runtime = {'records':[runtime_event()]}
    url = '/api/v1/clients/one/aidr/enforcement/records'
    runtime_ack = client.post(url,json=runtime,headers={'authorization':'Bearer test-one'})
    assert runtime_ack.status_code == 200, runtime_ack.text
    with factory() as db:
        log_hash = db.query(models.AidrEvent).one().content_hash
        hook_hash = db.query(AidrHookEvent).one().content_hash
        future = datetime.utcnow()+timedelta(days=2)
        first = expire_once(db,future,limit=1)
        assert first['aidr_events'] == first['aidr_hook_events'] == first['aidr_runtime_records'] == 1
        assert db.query(models.AidrEvent).one().payload_json == '{}'
        assert db.query(AidrHookEvent).one().payload_json == '{}'
        assert db.query(models.AidrEvent).one().content_hash == log_hash
        assert db.query(AidrHookEvent).one().content_hash == hook_hash
        assert db.query(AidrRuntimeRecord).one().content_hash
        assert not any(expire_once(db,future).values())
    assert submit(client,value).json() == ack
    assert send(client,hook).json() == hook_ack.json()
    assert client.post(url,json=runtime,headers={'authorization':'Bearer test-one'}).json() == runtime_ack.json()
    changed = copy.deepcopy(runtime); changed['records'][0]['transition']='exit'
    assert client.post(url,json=changed,headers={'authorization':'Bearer test-one'}).status_code == 409
    for suffix in ('events','hooks','operations'):
        assert client.get('/api/v1/clients/one/aidr/'+suffix).json()['items'] == []
    assert client.get(url).json()['items'] == []
    state = client.get('/api/v1/clients/one/aidr/status').json()
    assert state['retention']['expired_logs'] == state['retention']['expired_hooks'] == state['retention']['expired_runtime'] == 1
    actor = models.User(id=1,username='owner',role='admin',is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda:actor
    with factory() as db: iam.initialize(db)
    logical = value['records'][0]['payload']['logical_event_id']
    assert client.get('/api/v1/clients/one/aidr/content',params={'source':'log','record_id':logical}).status_code == 410


def test_lifecycle_settings_permissions_preservation_and_cas(service):
    client,factory=service
    client.app.include_router(system.router,prefix='/api')
    actor=models.User(id=1,username='owner',role='admin',is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user]=lambda:actor
    with factory() as db: iam.initialize(db)
    url='/api/system/aidr-redaction'
    body={'version':'1','enabled':True,'lifecycle':{'enabled':False,'retention_days':30}}
    saved=client.put(url,json=body);assert saved.status_code==200,saved.text
    assert saved.json()['lifecycle']==body['lifecycle']
    assert client.put(url,json=body).status_code==409
    # An older redaction-only editor cannot silently enable collection or reset TTL.
    old=client.put(url,json={'version':'2','enabled':False})
    assert old.status_code==200 and old.json()['lifecycle']==body['lifecycle']
    actor.role='user'
    assert client.put(url,json={**body,'version':'3'}).status_code==403
    actor.role='admin'
    assert client.put(url,json={**body,'version':'3','lifecycle':{'enabled':True,'retention_days':0}}).status_code==422
    assert client.put(url,json={**body,'version':'3','lifecycle':{'enabled':True,'retention_days':366}}).status_code==422
