"""Conversation capture contracts, source timelines and protected content access."""
import copy
import json
from datetime import datetime

from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload, operations
from tests.test_aidr_content import configure, fragment
from tests.test_aidr_sessions import get
from backend import models, auth, iam, iam_models


def message_event(role='assistant', phase='final', **changes):
    policy = dict(message_schema=1, version='2', enabled=True, receipt='a'*32, capture=dict(prompt=True, tool_output=False, file_body=False, model_response=True))
    return event(role+'_message', call='message:'+role+phase, schema_version=3,
        message=dict(role=role, phase=phase, policy=policy, content_status='captured',
            contents=[fragment('SYNTHETIC-QUESTION' if role=='user' else 'SYNTHETIC-REPLY',
                'prompt' if role=='user' else 'model_response', 'message.input' if role=='user' else 'message.output')]), **changes)


def issued_policy(client, factory):
    configure(factory, capture=dict(prompt=True, tool_output=False, file_body=False, model_response=True))
    return client.post('/api/v1/clients/one/aidr/audit-policy', json=dict(stream_id='a'*32,last_sequence='0'),
        headers={'authorization':'Bearer test-one','X-AIDR-Policy-Schema':'2','X-AIDR-Message-Capture':'1'}).json()


def test_message_upload_timeline_permissions_and_expiry(service):
    client, factory = service
    events = [message_event('user', 'unspecified'), message_event(phase='commentary'), message_event()]
    policy = issued_policy(client, factory)
    for e in events: e['message']['policy'] = policy
    with factory() as db:
        iam.initialize(db)
        if not db.query(iam_models.RolePermission).filter_by(role_name='admin',permission_code='clients:read-audit-content').first():
            db.add(iam_models.RolePermission(role_name='admin',permission_code='clients:read-audit-content'));db.commit()
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1,username='owner',role='admin',is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(id=1,username='owner',role='admin',is_active=True)
    response = upload(client, *events)
    assert response.status_code == 200, response.text
    assert upload(client, *events).status_code == 200
    assert operations(client)['items'] == []
    session = get(client, '/sessions')['items'][0]
    assert session['message_count'] == 3 and session['log_count'] == 0
    assert 'SYNTHETIC-' not in json.dumps(session)
    assert get(client, '/sessions', include_questions=True)['items'][0]['question_preview'] == 'SYNTHETIC-QUESTION'
    turns = get(client, '/session-turns', agent='codex', session_id='session-a', include_questions=True)['items']
    assert turns[0]['question']['text'] == 'SYNTHETIC-QUESTION'
    params = dict(source='logs', agent='codex', session_id='session-a', turn_key='turn:turn-a', limit=1)
    page = get(client, '/session-timeline', **params)
    items = page['items'][:]
    while page['has_more']:
        page = get(client, '/session-timeline', **params, cursor=page['next_cursor'])
        items.extend(page['items'])
    assert len(items)==3 and {r['message']['message']['phase'] for r in items} == {'unspecified', 'commentary', 'final'}
    assert 'SYNTHETIC-' not in json.dumps(items)
    url='/api/v1/clients/one/aidr/content'
    content=client.get(url,params=dict(source='log',record_id=events[2]['logical_event_id']))
    assert content.status_code==200 and content.json()['contents'][0]['text']=='SYNTHETIC-REPLY'
    assert content.headers['cache-control']=='no-store'
    client.app.dependency_overrides[auth.get_current_active_user]=lambda: models.User(id=2, username='reader',role='user',is_active=True)
    assert client.get(url,params=dict(source='log',record_id=events[2]['logical_event_id'])).status_code==403
    client.app.dependency_overrides[auth.get_current_active_user]=lambda: models.User(id=1, username='owner',role='admin',is_active=True)
    with factory() as db:
        row=db.query(models.AidrEvent).filter_by(logical_id=events[2]['logical_event_id']).one()
        row.expired_at=datetime.utcnow();row.payload_json='{}';db.commit()
    assert client.get(url,params=dict(source='log',record_id=events[2]['logical_event_id'])).status_code==410
    assert get(client,'/sessions')['items'][0]['message_count']==2


def test_message_scope_and_phase_rejected(service):
    client,factory=service
    policy=issued_policy(client,factory)
    for change in ('scope','phase','source','secret'):
        value=message_event();value['message']['policy']=copy.deepcopy(policy)
        if change=='scope':value['message']['policy']['capture']['model_response']=False
        if change=='phase':value['message']['phase']='guessed_final'
        if change=='source':value['message']['contents'][0]['source_field']='result.text'
        if change=='secret':value['message']['contents'][0]['text']='TOKEN=DO-NOT-STORE'
        assert upload(client,value).status_code==422


def test_enabling_messages_preserves_existing_tools_and_mixed_pagination(service):
    client, factory = service
    call = event('tool_call')
    assert upload(client, call).status_code == 200
    original_id = operations(client)['items'][0]['id']

    policy = issued_policy(client, factory)
    messages = [message_event('user', 'unspecified'), message_event(phase='commentary'), message_event()]
    for message in messages:
        message['message']['policy'] = policy
    result = event('tool_result')
    assert upload(client, *messages, result).status_code == 200
    assert upload(client, *messages, result).status_code == 200

    operation = operations(client)['items'][0]
    assert operation['id'] == original_id
    assert operation['call']['logical_event_id'] == call['logical_event_id']
    assert operation['result']['logical_event_id'] == result['logical_event_id']
    session = get(client, '/sessions')['items'][0]
    assert (session['log_count'], session['message_count']) == (1, 3)
    turns = get(client, '/session-turns', agent='codex', session_id='session-a')['items']
    assert (turns[0]['log_count'], turns[0]['message_count']) == (1, 3)

    params = dict(source='logs', agent='codex', session_id='session-a', turn_key='turn:turn-a', limit=1)
    page = get(client, '/session-timeline', **params)
    items = page['items'][:]
    while page['has_more']:
        page = get(client, '/session-timeline', **params, cursor=page['next_cursor'])
        items.extend(page['items'])
    assert len(items) == len({item['key'] for item in items}) == 4
    assert sum('operation' in item for item in items) == 1
    assert {item['message']['message']['phase'] for item in items if 'message' in item} == {'unspecified', 'commentary', 'final'}


def test_response_scope_negotiation_and_receipt(service):
    client,factory=service
    configure(factory,capture=dict(prompt=True,tool_output=False,file_body=False,model_response=True))
    headers={'authorization':'Bearer test-one','X-AIDR-Policy-Schema':'2'}
    url='/api/v1/clients/one/aidr/audit-policy'
    legacy=client.post(url,json=dict(stream_id='a'*32,last_sequence='0'),headers=headers).json()
    assert 'model_response' not in legacy['capture']
    invalid=client.post(url,json=dict(stream_id='a'*32,last_sequence='0'),headers={**headers,'X-AIDR-Message-Capture':'2'})
    assert invalid.status_code==422
    current=client.post(url,json=dict(stream_id='a'*32,last_sequence='0'),headers={**headers,'X-AIDR-Message-Capture':'1'}).json()
    value=message_event();value['message']['policy']=current
    assert upload(client,value).status_code==200
    forged=message_event(phase='commentary');forged['message']['policy']={**legacy,'message_schema':1,'capture':current['capture']}
    assert upload(client,forged).status_code==409
