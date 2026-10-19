"""Batch SQL retains durable ACKs, atomic conflicts and ordered projections."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import event as sql_event

from backend import aidr_hooks, aidr_models as models
from backend.aidr_skill_usage import merge_many
from backend.routers import aidr
from tests.test_aidr_api import service, submit
from tests.test_aidr_hooks import hook_batch, send
from tests.test_aidr_operations import event


def log_batch(count):
    events = [event('tool_call', call=f'batch-{i}') for i in range(count)]
    return {'schema_version': 1, 'records': [dict(sequence=str(i + 1), kind='event',
        record_id=value['logical_event_id'], payload=value) for i, value in enumerate(events)]}


def hooks(count):
    value = hook_batch()
    value['records'] = [hook_batch(i + 1)['records'][0] for i in range(count)]
    return value


def persist(db, channel, value):
    raw = json.dumps(value, separators=(',', ':')).encode()
    device = SimpleNamespace(client_id='one')
    if channel == 'logs':
        return aidr.save_batch(db, device, 'a' * 32, hashlib.sha256(raw).hexdigest(), raw)
    return aidr_hooks.save(db, device, raw)


@pytest.mark.parametrize('channel,count', [('logs', 10), ('logs', 500), ('hooks', 10), ('hooks', 100)])
def test_sql_round_trips_bounded_and_single_durable_commit(service, channel, count):
    _, factory = service
    engine = factory.kw['bind']
    statements, commits = [], []
    def statement(_conn, _cursor, sql, _parameters, _context, many):
        statements.append((sql, many))
    def committed(_conn):
        commits.append(True)
    sql_event.listen(engine, 'before_cursor_execute', statement)
    sql_event.listen(engine, 'commit', committed)
    try:
        with factory() as db:
            ack = persist(db, channel, log_batch(count) if channel == 'logs' else hooks(count))
    finally:
        sql_event.remove(engine, 'before_cursor_execute', statement)
        sql_event.remove(engine, 'commit', committed)
    assert ack['durable'] and ack['accepted'] == count
    assert len(commits) == 1
    assert len(statements) <= 8
    assert any(many and sql.startswith('INSERT') for sql, many in statements)
    with factory() as db:
        model = models.AidrEvent if channel == 'logs' else models.AidrHookEvent
        assert db.query(model).count() == count


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_reused_insert_sql_keeps_fresh_batch_parameters_and_defaults(service, channel):
    _, factory = service
    engine = factory.kw['bind']
    receipt = models.AidrBatch if channel == 'logs' else models.AidrHookBatch
    evidence = models.AidrEvent if channel == 'logs' else models.AidrHookEvent
    tables = [receipt.__tablename__, evidence.__tablename__]
    if channel == 'logs':
        tables.append(models.AidrOperation.__tablename__)
    hits = {name: [] for name in tables}
    def statement(_conn, _cursor, sql, _parameters, context, _many):
        for name in tables:
            if sql.startswith(f'INSERT INTO {name} '):
                hits[name].append(context.cache_hit.name)
    engine.clear_compiled_cache()
    sql_event.listen(engine, 'before_cursor_execute', statement)
    first, second = [log_batch(n) if channel == 'logs' else hooks(n) for n in (2, 4)]
    try:
        acks = []
        for value in (first, second, first):
            with factory() as db:
                acks.append(persist(db, channel, value))
    finally:
        sql_event.remove(engine, 'before_cursor_execute', statement)
    assert [ack['accepted'] for ack in acks] == [2, 4, 2]
    assert all(ack['durable'] for ack in acks)
    assert acks[0]['digest'] == acks[2]['digest'] != acks[1]['digest']
    for calls in hits.values():
        assert len(calls) >= 2 and calls[0] == 'CACHE_MISS'
        assert set(calls[1:]) == {'CACHE_HIT'}
    with factory() as db:
        receipts = db.query(receipt).order_by(receipt.id).all()
        assert [row.record_count for row in receipts] == [2, 4]
        assert receipts[1].received_at > receipts[0].received_at
        rows = db.query(evidence).order_by(evidence.id).all()
        assert len(rows) == 4
        assert min(row.received_at for row in rows[2:]) > max(row.received_at for row in rows[:2])


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_mid_batch_conflict_rolls_back_new_evidence_and_batch_receipt(service, channel):
    client, factory = service
    value = log_batch(3) if channel == 'logs' else hooks(3)
    single = {**value, 'records': [copy.deepcopy(value['records'][1])]}
    upload = submit if channel == 'logs' else send
    assert upload(client, single).status_code == 200
    if channel == 'logs':
        value['records'][1]['payload']['tool'] = 'different-tool'
    else:
        value['records'][1]['event']['session_id'] = 'different-session'
    assert upload(client, value).status_code == 409
    with factory() as db:
        model = models.AidrEvent if channel == 'logs' else models.AidrHookEvent
        receipt = models.AidrBatch if channel == 'logs' else models.AidrHookBatch
        assert db.query(model).count() == db.query(receipt).count() == 1
        if channel == 'logs':
            assert db.query(models.AidrOperation).count() == 1


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_failed_commit_never_acknowledges_or_retains_batch(service, monkeypatch, channel):
    _, factory = service
    with factory() as db:
        def fail_commit():
            raise OSError('simulated durable commit failure')
        monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises(OSError, match='durable commit failure'):
            persist(db, channel, log_batch(10) if channel == 'logs' else hooks(10))
    with factory() as db:
        assert db.query(models.AidrEvent).count() == db.query(models.AidrHookEvent).count() == 0
        assert db.query(models.AidrBatch).count() == db.query(models.AidrHookBatch).count() == 0
        assert db.query(models.AidrOperation).count() == 0


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_concurrent_retries_persist_one_complete_batch(service, channel):
    client, factory = service
    value = log_batch(30) if channel == 'logs' else hooks(30)
    upload = submit if channel == 'logs' else send
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: upload(client, value), range(8)))
    assert all(r.status_code == 200 and r.json()['durable'] for r in responses)
    with factory() as db:
        model = models.AidrEvent if channel == 'logs' else models.AidrHookEvent
        receipt = models.AidrBatch if channel == 'logs' else models.AidrHookBatch
        assert db.query(model).count() == 30
        assert db.query(receipt).count() == 1


def test_hook_sequence_collision_rolls_back_other_new_events(service):
    client, factory = service
    assert send(client, hook_batch(2)).status_code == 200
    value = hooks(3)
    value['records'][1]['event_id'] = 'f' * 32
    assert send(client, value).status_code == 409
    with factory() as db:
        assert db.query(models.AidrHookEvent).count() == db.query(models.AidrHookBatch).count() == 1


def test_policy_receipt_loaded_once_but_each_sequence_still_checked(service):
    _, factory = service
    value = hooks(10)
    policy = {'version': '1', 'enabled': True, 'receipt': 'c' * 32}
    for record in value['records']:
        record['event']['policy'] = policy
    with factory() as db:
        db.add(models.AidrPolicyReceipt(id=policy['receipt'], client_id='one', stream_id=value['stream_id'],
            version='1', enabled=True, start_sequence=1, end_sequence=9))
        db.commit()
    with factory() as db:
        from backend.api_errors import ApiError
        with pytest.raises(ApiError):
            persist(db, 'hooks', value)
    with factory() as db:
        assert db.query(models.AidrHookEvent).count() == db.query(models.AidrHookBatch).count() == 0
        db.get(models.AidrPolicyReceipt, policy['receipt']).end_sequence = 10
        db.commit()
    reads = []
    engine = factory.kw['bind']
    def observe(_conn, _cursor, sql, *_args):
        if sql.startswith('SELECT') and 'aidr_policy_receipts' in sql:
            reads.append(sql)
    sql_event.listen(engine, 'before_cursor_execute', observe)
    try:
        with factory() as db:
            assert persist(db, 'hooks', value)['durable']
    finally:
        sql_event.remove(engine, 'before_cursor_execute', observe)
    assert len(reads) == 1


def test_bulk_skill_projection_does_not_skip_later_conflicting_skill(service):
    _, factory = service
    with factory() as db:
        records = []
        for i, name in enumerate(('first', 'different')):
            payload = dict(agent='workbuddy', session_id='session', native_call_id='same',
                user_scope='501', kind='tool_call', tool='Skill',
                skill_use={'behavior':'invocation', 'name':name, 'basis':'tool_input.skill'})
            row = models.AidrEvent(client_id='one', logical_id=f'{i:064x}', content_hash='b'*64,
                agent='workbuddy', kind='tool_call', payload_json=json.dumps(payload))
            db.add(row)
            records.append(row)
        db.flush()
        merge_many(db, 'log', records)
        db.commit()
        data = json.loads(db.query(models.AidrSkillUse).one().payload_json)
        assert data['identity_ambiguous'] is True
        assert len(data['evidence']) == 2
