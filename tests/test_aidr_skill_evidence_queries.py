"""Indexed evidence lookup preserves source order and durable batch semantics."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import event as sql_event

from backend import aidr_skill_usage as usage
from backend.aidr_models import AidrEvent, AidrHookEvent, AidrSkillUse, SKILL_EVIDENCE_INDEXES
from tests.test_aidr_api import service, submit
from tests.test_aidr_hooks import hook_batch, send
from tests.test_aidr_batch_sql import log_batch, persist


def record(db, source, number, *, skill=False, client='one', expired=False, **changes):
    event = dict(agent='codex', session_id='session', native_call_id='call', turn_id='turn',
                 user_scope='501', tool='Read', kind='tool_result', outcome='success')
    event.update(changes)
    if skill:
        event['skill_use'] = dict(behavior='file_access', path='/skills/sample/SKILL.md', basis='tool_input.path')
    common = dict(client_id=client, content_hash='b'*64, expired_at=datetime.utcnow() if expired else None)
    if source == 'log':
        row = AidrEvent(**common, logical_id=f'{number:064x}', agent=event['agent'], kind=event['kind'],
                        payload_json=json.dumps(event))
    else:
        row = AidrHookEvent(**common, stream_id='a'*32, event_id=f'{number:032x}', source_seq=number,
                            payload_json=json.dumps({'event':event, 'user_scope':event['user_scope']}))
    db.add(row)
    return row


@pytest.mark.parametrize('source', ['log', 'hook'])
def test_late_skill_joins_only_exact_live_identity(service, source):
    _, factory = service
    opposite = 'hook' if source == 'log' else 'log'
    with factory() as db:
        matching = record(db, opposite, 1)
        for number, change in enumerate(({'client':'two'}, {'user_scope':'502'}, {'native_agent_id':'other'},
                                        {'turn_id':'other'}, {'session_id':'other'}, {'agent':'workbuddy'},
                                        {'native_call_id':'other'}, {'expired':True}), 2):
            record(db, opposite, number, **change)
        previous = record(db, source, 20)
        incoming = record(db, source, 21, skill=True, kind='tool_call', outcome='unknown')
        db.flush()
        usage.merge_many(db, source, [previous, incoming])
        db.commit()
        data = json.loads(db.query(AidrSkillUse).one().payload_json)
        expected = {(source,str(previous.id)), (source,str(incoming.id)), (opposite,str(matching.id))}
        assert {(r['source'],r['id']) for r in data['evidence']} == expected
        assert data['stage'] == 'host_confirmed' and not data['identity_ambiguous']
        usage.merge_many(db, source, [previous, incoming])
        db.commit()
        assert json.loads(db.query(AidrSkillUse).one().payload_json) == data


@pytest.mark.parametrize('source', ['log', 'hook'])
def test_later_conflicting_observation_across_lookup_chunks_is_not_swallowed(service, source):
    _, factory = service
    with factory() as db:
        rows = [record(db, source, i, skill=True, native_call_id=f'call-{i}') for i in range(32)]
        last = record(db, source, 32, skill=True, native_call_id='call-0')
        raw = json.loads(last.payload_json)
        event = raw if source == 'log' else raw['event']
        event['skill_use']['path'] = '/skills/changed/SKILL.md'
        last.payload_json = json.dumps(raw)
        rows.append(last)
        db.flush()
        usage.merge_many(db, source, rows)
        db.commit()
        data = [json.loads(r.payload_json) for r in db.query(AidrSkillUse)]
        assert len(data) == 32
        changed = next(d for d in data if d['native_call_id']=='call-0')
        assert changed['identity_ambiguous'] and len(changed['evidence']) == 2


def test_each_call_has_its_own_evidence_limit(service):
    _, factory = service
    with factory() as db:
        for i in range(70):
            record(db, 'hook', i, native_call_id='crowded')
        record(db, 'hook', 71, native_call_id='small')
        rows = [record(db, 'log', i, skill=True, native_call_id=call) for i,call in enumerate(('crowded','small'))]
        db.flush()
        usage.merge_many(db, 'log', rows)
        db.commit()
        data = {json.loads(r.payload_json)['native_call_id']:json.loads(r.payload_json) for r in db.query(AidrSkillUse)}
        assert len(data['crowded']['evidence']) == 64
        assert len(data['small']['evidence']) == 2


@pytest.mark.parametrize('source', ['log', 'hook'])
def test_batched_queries_use_identity_index_and_bounded_round_trips(service, source):
    _, factory = service
    engine = factory.kw['bind']
    queries = []
    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if statement.startswith('SELECT') and 'lookup_slot' in statement:
            queries.append((statement,parameters))
    with factory() as db:
        for i in range(1000):
            record(db, 'log', i, native_call_id=f'history-{i}')
            record(db, 'hook', i, native_call_id=f'history-{i}')
        rows = [record(db, source, i+1000, skill=True, native_call_id=f'new-{i}') for i in range(65)]
        db.flush()
        sql_event.listen(engine, 'before_cursor_execute', capture)
        try:
            usage.merge_many(db, source, rows)
        finally:
            sql_event.remove(engine, 'before_cursor_execute', capture)
        db.commit()
        assert len(queries) == 6  # Two source lookups per group of at most 32 calls.
        assert db.query(AidrSkillUse).count() == 65
        for statement, parameters in queries:
            plan = ' '.join(r[3] for r in db.connection().exec_driver_sql('EXPLAIN QUERY PLAN '+statement, parameters))
            assert any(index.name in plan for index in SKILL_EVIDENCE_INDEXES)
            assert '<expr>=? AND <expr>=? AND <expr>=?' in plan
            assert 'TEMP B-TREE' not in plan


def skill_batch(channel):
    if channel == 'logs':
        batch = log_batch(3)
        events = [r['payload'] for r in batch['records']]
    else:
        batch = hook_batch()
        batch['records'] = [hook_batch(i+2)['records'][0] for i in range(3)]
        events = [r['event'] for r in batch['records']]
        for i,event in enumerate(events):
            event.update(kind='tool.pre', hook_event='PreToolUse', native_call_id=f'call-{i}', tool='Read', turn_id='turn')
            event['behavior'] = dict(version=3, policy=event['policy'], body_omitted=False,
                category='file_read', method='direct_fields', actions=[], status='unknown',
                result_basis=[], redacted=False, truncated=False, uncertainty=[])
    for event in events:
        event['skill_use'] = dict(behavior='file_access', path='/skills/sample/SKILL.md', basis='tool_input.path')
    return batch


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_real_upload_retries_keep_single_skill_projection_and_conflicts_rollback(service, channel):
    client, factory = service
    value = skill_batch(channel)
    upload = submit if channel == 'logs' else send
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _:upload(client,value),range(8)))
    assert all(r.status_code==200 and r.json()['durable'] for r in responses), [r.text for r in responses]
    with factory() as db:
        assert db.query(AidrSkillUse).count() == 3
        assert all(len(json.loads(r.payload_json)['evidence'])==1 for r in db.query(AidrSkillUse))
    conflict = copy.deepcopy(value)
    first = conflict['records'][0]
    if channel == 'logs':
        first['record_id'] = first['payload']['logical_event_id'] = 'c'*64
        first['payload']['native_call_id'] = 'new-call'
    else:
        first['event_id'] = 'c'*32
        first['source_seq'] = '1'
        first['event']['native_call_id'] = 'new-call'
    event = conflict['records'][1]['payload' if channel=='logs' else 'event']
    event['skill_use']['path']='/skills/conflicting/SKILL.md'
    event['tool']='different-tool'
    assert upload(client,conflict).status_code == 409
    with factory() as db:
        assert db.query(AidrSkillUse).count() == 3
        assert all(json.loads(r.payload_json)['skill']['path']=='/skills/sample/SKILL.md' for r in db.query(AidrSkillUse))


@pytest.mark.parametrize('channel', ['logs', 'hooks'])
def test_failed_commit_rolls_back_skill_evidence_before_ack(service, monkeypatch, channel):
    _, factory = service
    with factory() as db:
        def fail():
            assert db.query(AidrSkillUse).count() == 3
            raise OSError('durable commit failed')
        monkeypatch.setattr(db,'commit',fail)
        with pytest.raises(OSError,match='durable commit failed'):
            persist(db,channel,skill_batch(channel))
    with factory() as db:
        assert db.query(AidrSkillUse).count() == 0
        assert db.query(AidrEvent).count() == db.query(AidrHookEvent).count() == 0
