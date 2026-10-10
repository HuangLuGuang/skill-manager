"""Onboarding evidence is scoped, independent, and never inferred from tasks."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import models
from backend.runtime_governance import Observation, view
from backend.aidr_hook_runtime import HookRuntimeRow
from backend.aidr_models import AidrHookEvent
from tests.test_aidr_api import service
from tests.test_aidr_channel_health import set_target
from tests.test_aidr_hooks import hook_batch, send


def state(factory):
    with factory() as db:
        result = view(db, 'one')['onboarding']
    return result, {item['key']: item for item in result['hosts'][0]['steps']} if result['hosts'] else {}


def target(factory):
    set_target(factory, False)
    with factory() as db:
        row=db.get(models.ClientGovernancePolicy,'@default')
        config=json.loads(row.runtime_governance_json); config['hosts']=['codex']
        row.runtime_governance_json=json.dumps(config); db.commit()


def report(factory):
    at = datetime.utcnow()
    with factory() as db:
        db.add(Observation(client_id='one', supports_tasks=True, reported_at=at, report_json=json.dumps({
            'protocol': 3, 'policy_version': '1', 'receiver_code': 'aidr_desktop_running',
            'hosts': [{'agent': 'codex', 'installed': True, 'enabled': True, 'hook_trust': 'trusted', 'reported_at': at.isoformat()+'Z'}],
            'channels': {'hooks': {'reported_at': at.isoformat()+'Z', 'enabled': True, 'policy_version':'1', 'code':'aidr_desktop_running','state':'running'}}})))
        db.commit()


def test_default_and_disabled_targets_do_not_fabricate_acceptance(service):
    _, factory = service
    value, steps = state(factory)
    assert value['target_enabled'] is True
    assert {host['agent'] for host in value['hosts']} == {'claude', 'codex'}
    assert steps['configuration']['status'] == 'confirmed'
    assert all(item['status'] == 'unknown' for key, item in steps.items() if key != 'configuration')
    target(factory)
    with factory() as db:
        row = db.get(models.ClientGovernancePolicy, '@default')
        config = json.loads(row.runtime_governance_json); config['channels']['hooks'] = False
        row.runtime_governance_json = json.dumps(config); db.commit()
    value, steps = state(factory)
    assert value['target_enabled'] is False
    assert steps['configuration']['status'] == 'confirmed'
    assert all(item['status'] == 'not_required' for key,item in steps.items() if key != 'configuration')
    assert value['hosts'][0]['next_step'] is None


def test_configuration_and_client_reports_are_not_host_execution_or_events(service):
    _, factory = service
    target(factory); report(factory)
    _, steps = state(factory)
    assert steps['capabilities']['status'] == 'reported'
    # Default host order may be claude; select codex explicitly below.
    with factory() as db:
        codex = next(item for item in view(db,'one')['onboarding']['hosts'] if item['agent']=='codex')
    steps = {item['key']: item for item in codex['steps']}
    assert steps['installation']['status'] == steps['native_trust']['status'] == steps['receiver']['status'] == 'reported'
    assert all(steps[key]['status']=='unknown' for key in ('host_loading','event_arrival','platform_receipt','client_ack'))


def codex_steps(factory):
    with factory() as db:
        host = next(item for item in view(db,'one')['onboarding']['hosts'] if item['agent']=='codex')
    return {item['key']: item for item in host['steps']}


@pytest.mark.parametrize('scope', ['matching','wrong_stream','wrong_receiver','stale','future'])
def test_platform_receipt_and_client_ack_have_separate_scoped_evidence(service, scope):
    api, factory = service
    target(factory)
    batch = hook_batch(); batch['records'][0]['receiver_instance'] = 'c'*32
    response = send(api,batch)
    assert response.status_code == 200 and response.json()['durable']
    steps = codex_steps(factory)
    assert steps['event_arrival']['status'] == steps['platform_receipt']['status'] == 'confirmed'
    assert steps['client_ack']['status'] == steps['host_loading']['status'] == 'unknown'
    now = datetime.utcnow()
    with factory() as db:
        db.add(HookRuntimeRow(client_id='one', stream_id=('d' if scope=='wrong_stream' else 'b')*32,
            receiver_instance=('d' if scope=='wrong_receiver' else 'c')*32, sequence=1,
            received_at=int((now-timedelta(seconds=100 if scope=='stale' else 0)).replace(tzinfo=timezone.utc).timestamp()),
            payload=json.dumps({'last_event_ack_at': (now+timedelta(seconds=60 if scope=='future' else 0)).isoformat()+'Z'})))
        db.commit()
    steps = codex_steps(factory)
    assert steps['client_ack']['status'] == ('reported' if scope=='matching' else 'unknown')
    assert steps['host_loading']['status'] == 'unknown'


def test_old_events_cannot_verify_new_policy_or_current_collection(service):
    api, factory = service
    target(factory)
    assert send(api).status_code == 200
    with factory() as db:
        row = db.query(AidrHookEvent).one(); row.received_at = datetime.utcnow()-timedelta(minutes=16); db.commit()
    assert codex_steps(factory)['event_arrival']['status']=='unknown'
    with factory() as db:
        db.query(AidrHookEvent).one().received_at=datetime.utcnow()-timedelta(seconds=2)
        db.get(models.ClientGovernancePolicy,'@default').updated_at=datetime.utcnow()
        db.commit()
    assert codex_steps(factory)['event_arrival']['status']=='unknown'


def test_observed_events_do_not_trap_next_action_on_missing_native_loading_receipt(service):
    api, factory = service
    target(factory); report(factory)
    batch = hook_batch(); batch['records'][0]['receiver_instance']='c'*32
    assert send(api,batch).status_code==200
    now=datetime.utcnow()
    with factory() as db:
        db.add(HookRuntimeRow(client_id='one',stream_id='b'*32,receiver_instance='c'*32,sequence=1,
            received_at=int(now.replace(tzinfo=timezone.utc).timestamp()),
            payload=json.dumps({'last_event_ack_at':now.isoformat()+'Z'})))
        db.commit()
        host=view(db,'one')['onboarding']['hosts'][0]
    assert host['next_step'] is None
    loading=next(item for item in host['steps'] if item['key']=='host_loading')
    assert loading['status']=='unknown' and loading['evidence']['hook_event_observed_at']
