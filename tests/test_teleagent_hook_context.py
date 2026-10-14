import json
from datetime import datetime
import pytest
from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload, behavior
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_sessions import get
from backend.aidr_models import AidrHookEvent, AidrOperation
from backend.aidr_sessions import turn_hook_contexts


def call(client, **changes):
    e = event('tool_call', agent='teleagent', session='s', turn='t', call='c',
              tool='bash', user_scope='501', schema_version=2, behavior=behavior(), **changes)
    assert upload(client, e).status_code == 200


def hook(factory, number=1, **changes):
    return insert(factory, number, event=dict(agent='teleagent', session_id='s', turn_id='t',
        native_call_id='c', tool='bash', kind='tool.pre', context={'cwd': '/'}, **changes))


def records(client):
    return get(client, '/session-timeline', agent='teleagent', session_id='s', source='hooks')['items']


def test_late_log_corrects_legacy_worktree_without_rewriting_raw_hooks(service):
    client, factory = service
    hid = hook(factory)
    with factory() as db:
        original = db.get(AidrHookEvent, hid).payload_json
    assert not records(client)[0]['records'][0]['record']['event']['context'].get('cwd')
    call(client)
    view = records(client)[0]['records'][0]['record']['event']['context']
    assert view['cwd'] == '/tmp/audit' and view['cwd_source'] == 'agent_log'
    context = get(client, '/session-turns', agent='teleagent', session_id='s')['items'][0]['hook_context']['cwd'][0]
    assert context['value'] == '/tmp/audit' and context['source'] == 'agent_log'
    with factory() as db:
        assert db.get(AidrHookEvent, hid).payload_json == original
        assert 'cwd' not in turn_hook_contexts(db, 'one', 'teleagent', 's', hid, ['turn:t'], 0).get('turn:t', {})


def test_new_hook_without_context_can_resolve_exact_log_directory(service):
    client, factory = service
    insert(factory, 1, event=dict(agent='teleagent', session_id='s', turn_id='t',
        native_call_id='c', tool='bash', kind='tool.pre', context=None))
    call(client)
    assert records(client)[0]['records'][0]['record']['event']['context']['cwd'] == '/tmp/audit'
    assert get(client, '/session-turns', agent='teleagent', session_id='s')['items'][0]['hook_context']['cwd'][0]['value'] == '/tmp/audit'


@pytest.mark.parametrize('boundary', ['user', 'client', 'session', 'tool', 'call', 'expired', 'conflict', 'truncated', 'ambiguous', 'ambiguous_empty', 'ambiguous_conflict', 'missing_cwd'])
def test_directory_requires_unique_exact_retained_call(service, boundary):
    client, factory = service
    hook(factory)
    call(client)
    if boundary.startswith('ambiguous'):
        call(client, source='c'*64)
        if boundary != 'ambiguous':
            with factory() as db:
                row = db.query(AidrOperation).order_by(AidrOperation.id.desc()).first()
                p = json.loads(row.payload_json)
                if boundary == 'ambiguous_empty': p['call']['behavior']['actions'] = []
                if boundary == 'ambiguous_conflict': p['conflicting_evidence'] = True
                row.payload_json = json.dumps(p)
                db.commit()
    else:
        with factory() as db:
            row = db.query(AidrOperation).one()
            p = json.loads(row.payload_json)
            if boundary == 'client': row.client_id = 'two'
            if boundary == 'session': row.session_id = 'other'
            if boundary == 'user': p['call']['user_scope'] = '502'
            if boundary == 'tool': p['call']['tool'] = 'write'
            if boundary == 'call': p['call']['native_call_id'] = 'other'
            if boundary == 'expired': row.expired_at = datetime.utcnow()
            if boundary == 'conflict': p['conflicting_evidence'] = True
            if boundary == 'truncated': p['evidence_truncated'] = True
            if boundary == 'missing_cwd': p['call']['behavior']['actions'][0]['cwd'] = ''
            row.payload_json = json.dumps(p)
            db.commit()
    assert not records(client)[0]['records'][0]['record']['event']['context'].get('cwd')


def test_other_product_keeps_native_hook_directory(service):
    client, factory = service
    insert(factory, 1, event=dict(agent='codex', session_id='s', turn_id='t',
        native_call_id='c', tool='bash', kind='tool.pre', context={'cwd': '/native'}))
    result = get(client, '/session-timeline', agent='codex', session_id='s', source='hooks')
    assert result['items'][0]['records'][0]['record']['event']['context']['cwd'] == '/native'
