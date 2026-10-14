"""Event semantics, evidence-time pagination, and device visibility contracts."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from backend import auth, client_event_records as records, models
from backend.aidr_models import AidrSkillUse
from backend.sqlite_db import get_db
from tests.test_clients_api import _client


@pytest.mark.parametrize('kind,details,title,state', [
    ('aidr_skill_alert', {'active':True, 'stage':'host_confirmed', 'behavior':'invocation'}, 'audit_loaded', 'alert_active'),
    ('aidr_skill_alert', {'active':False, 'stage':'attempted', 'behavior':'file_access'}, 'audit_file_attempted', 'alert_inactive'),
    ('aidr_skill_alert', {}, 'audit_check', 'unknown'),
    ('skill_governance_recorded', {'action':'record_only','trigger':'unverified'}, 'discovery_unverified', 'recorded'),
    ('skill_governance_action', {'action':'quarantine','status':'completed'}, 'action_quarantine', 'succeeded'),
    ('skill_governance_action', {'action':'restore_trusted','status':'failed','error_code':'skill_action_failed'}, 'action_restore_trusted', 'failed'),
    ('skill_governance_action', {'action':'quarantine'}, 'action_quarantine', 'unknown'),
    ('skill_quarantined', {'status':'pending'}, 'action_quarantine', 'pending'),
    ('future_event', {}, 'unknown_event', 'unknown'),
])
def test_known_facts_do_not_imply_unrecorded_action_success(tmp_path, kind, details, title, state):
    client = _client(tmp_path)
    with next(client.app.dependency_overrides[get_db]()) as db:
        event = models.ClientEvent(client_id='one', event_type=kind, details_json=json.dumps(details))
        db.add(event); db.flush()
        value = records.present(event, details)
        assert (value['title'], value['state']) == (title, state)
        category, status, _ = records.expressions()
        assert db.query(category, status).filter(models.ClientEvent.id == event.id).one() == (value['category'], value['state'])


def test_history_uses_evidence_time_and_filters_consistently_for_both_apis(tmp_path):
    client = _client(tmp_path)
    token = client.post('/api/v1/access/tokens', json={'name':'events', 'token_type':'client'}).json()['token']
    headers = {'Authorization':'Bearer ' + token}
    registration = client.post('/api/v1/clients/register', headers=headers, json={'client_id':'one','name':'one','hostname':'one','os':'linux','arch':'amd64','client_version':'dev','agents':[]})
    assert registration.status_code == 200, registration.text
    now, old = datetime.utcnow(), datetime.utcnow() - timedelta(days=20)
    with next(client.app.dependency_overrides[get_db]()) as db:
        usage = AidrSkillUse(client_id='one', call_key='call', agent='codex', session_id='session', behavior='invocation', payload_json=json.dumps({
            'first_at':now.isoformat()+'Z', 'skill':{'path':'/skills/sample'}, 'evidence':[
                {'source':'hook','id':'2','at':(old+timedelta(seconds=1)).isoformat()+'Z','stage':'host_confirmed'},
                {'source':'hook','id':'1','at':old.isoformat()+'Z','stage':'attempted'},
            ]}))
        db.add(usage); db.flush()
        alert = models.ClientEvent(client_id='one', event_type='aidr_skill_alert', skill_name='old-alert', created_at=old,
            last_seen_at=now, observation_count=99, details_json=json.dumps({'usage_id':str(usage.id),'active':True,'stage':'host_confirmed','behavior':'invocation'}))
        finding = models.ClientEvent(client_id='one', event_type='skill_governance_recorded', skill_name='current-finding', last_seen_at=now,
            observation_count=12, details_json=json.dumps({'action':'record_only','trigger':'unverified'}))
        db.add_all([alert, finding]); db.commit()
        usage_id = usage.id
    runtime = client.get('/api/v1/clients/one/history', headers=headers)
    admin = client.get('/api/v1/clients/one/event-records')
    assert runtime.status_code == admin.status_code == 200
    assert runtime.json() == admin.json()
    assert [event['skill_name'] for event in admin.json()['items']] == ['current-finding','old-alert']
    alert = admin.json()['items'][1]['presentation']
    assert datetime.fromisoformat(alert['occurred_at'].replace('Z','+00:00')) == old.replace(tzinfo=timezone.utc)
    assert alert['time_kind'] == 'behavior' and alert['count_kind'] == '' and alert['file_action'] == 'unrecorded'
    for path, auth_headers in [('event-records', {}), ('history',headers)]:
        url = '/api/v1/clients/one/' + path
        assert client.get(url, headers=auth_headers, params={'days':7}).json()['total'] == 1
        assert client.get(url, headers=auth_headers, params={'category':'audit', 'status':'alert_active'}).json()['total'] == 1
        assert client.get(url, headers=auth_headers, params={'category':'audit', 'status':'succeeded'}).json()['total'] == 0
    # Expired evidence and evidence belonging to another device cannot supply a timestamp or navigation target.
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.get(AidrSkillUse, usage_id).client_id = 'other'; db.commit()
    fallback = client.get('/api/v1/clients/one/event-records', params={'category':'audit'}).json()['items'][0]['presentation']
    assert fallback['time_kind'] == 'recorded' and fallback['usage_id'] is None
    with next(client.app.dependency_overrides[get_db]()) as db:
        usage = db.get(AidrSkillUse, usage_id); usage.client_id = 'one'; usage.expired_at = now; db.commit()
    assert client.get('/api/v1/clients/one/event-records', params={'category':'audit'}).json()['items'][0]['presentation']['time_kind'] == 'recorded'
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=22,username='other',role='admin',hashed_password='x')
    assert client.get('/api/v1/clients/one/event-records').status_code == 404


def test_received_time_is_not_labeled_behavior_time():
    now = datetime.utcnow()
    event = SimpleNamespace(event_type='aidr_skill_alert', last_seen_at=now, created_at=now)
    usage = {'first_at':now.isoformat()+'Z', 'evidence':[{'received_at':now.isoformat()+'Z'}]}
    value = records.present(event, {'usage_id':'1'}, usage)
    assert value['time_kind'] == 'recorded'
    assert value['timeline'][0]['arrival'] is True
