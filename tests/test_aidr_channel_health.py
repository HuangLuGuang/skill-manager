"""Policy-aware health must not turn an intentionally disabled channel into failure."""
import json
from datetime import datetime, timedelta

import pytest

from backend import models
from backend.client_governance import RuntimeGovernanceConfig
from backend.runtime_governance import Observation, channel_health
from tests.test_aidr_api import service


@pytest.mark.parametrize('target,observation,stale,expected,severity', [
    (None, None, True, 'policy_unknown', 'info'),
    (False, None, True, 'not_requested', 'info'),
    (False, {'policy_version': 'old', 'enabled': True, 'state': 'failed'}, True, 'not_requested', 'info'),
    (False, {'policy_version': 'old', 'enabled': True, 'state': 'running'}, False, 'awaiting_stop', 'info'),
    (False, {'policy_version': '2', 'enabled': True, 'state': 'running'}, False, 'disable_not_applied', 'warning'),
    (False, {'policy_version': '2', 'enabled': False, 'state': 'running'}, False, 'disable_not_applied', 'warning'),
    (False, {'policy_version': '2', 'enabled': False, 'state': 'disabled'}, False, 'not_requested', 'info'),
    (True, None, True, 'unreported', 'warning'),
    (True, {'policy_version': 'old', 'enabled': True, 'state': 'running'}, False, 'awaiting_application', 'info'),
    (True, {'policy_version': 'old', 'enabled': True, 'state': 'failed'}, True, 'awaiting_application', 'info'),
    (True, {'policy_version': '2', 'enabled': True, 'state': 'running'}, True, 'stale', 'warning'),
    (True, {'policy_version': '2', 'enabled': False, 'state': 'disabled'}, False, 'awaiting_application', 'info'),
    (True, {'policy_version': '2', 'enabled': True, 'state': 'failed'}, False, 'failed', 'warning'),
    (True, {'policy_version': '2', 'enabled': True, 'state': 'running'}, False, 'running', 'info'),
])
def test_health_distinguishes_target_application_and_observation(target, observation, stale, expected, severity):
    assert channel_health(target, '2', observation, stale) == {'state': expected, 'code': 'aidr_channel_' + expected, 'severity': severity}


def set_target(factory, logs, revision=1):
    target = RuntimeGovernanceConfig().model_dump() | {'enabled': True, 'channels': {'logs': logs, 'hooks': True, 'system': False}}
    with factory() as db:
        row = db.get(models.ClientGovernancePolicy, '@default')
        if row is None:
            row = models.ClientGovernancePolicy(scope='@default', revision=revision)
            db.add(row)
        row.revision = revision
        row.runtime_governance_json = json.dumps(target)
        db.commit()


def set_observation(factory, version, *, ago=0, state='running'):
    at = datetime.utcnow() - timedelta(seconds=ago)
    observation = {'state': state, 'code': 'aidr_log_running', 'enabled': True,
                   'policy_version': version, 'reported_at': at.isoformat() + 'Z'}
    with factory() as db:
        row = db.get(Observation, 'one')
        if row is None:
            row = Observation(client_id='one', supports_tasks=True)
            db.add(row)
        row.report_json = json.dumps({'protocol': 3, 'channels': {'logs': observation}})
        row.reported_at = at
        db.commit()


def test_inherited_hook_only_policy_does_not_report_log_failure(service):
    api, factory = service
    set_target(factory, False)
    state = api.get('/api/v1/clients/one/aidr/status').json()
    assert not state['online']
    assert state['log_channel']['target_enabled'] is False
    assert state['log_channel']['health']['state'] == 'not_requested'
    assert state['log_channel']['health']['severity'] == 'info'
    # Old failures cannot override the new explicit disabled target.
    set_observation(factory, '0', ago=300, state='failed')
    assert api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']['state'] == 'not_requested'
    with factory() as db:
        assert json.loads(db.get(models.ClientGovernancePolicy, '@default').runtime_governance_json)['channels']['logs'] is False


def test_new_target_waits_for_its_own_channel_version_then_checks_transport(service):
    api, factory = service
    set_target(factory, True, revision=2)
    set_observation(factory, '1')
    state = api.get('/api/v1/clients/one/aidr/status').json()
    assert state['log_channel']['health']['state'] == 'awaiting_application'
    assert not state['log_channel']['applied']
    set_observation(factory, '2', ago=300)
    assert api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']['state'] == 'stale'
    set_observation(factory, '2')
    assert api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']['state'] == 'transport_offline'
    with factory() as db:
        db.get(models.AidrDevice, 'one').last_seen_at = datetime.utcnow()
        db.commit()
    assert api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']['state'] == 'running'
    with factory() as db:
        db.get(models.AidrDevice, 'one').enabled = False
        db.commit()
    assert api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']['state'] == 'reporting_paused'


def test_default_collection_target_does_not_claim_runtime_health(service):
    api, _ = service
    state = api.get('/api/v1/clients/one/aidr/status').json()
    assert state['log_channel']['target_enabled'] is True
    assert state['log_channel']['health']['state'] == 'unreported'
    assert state['log_channel']['health']['code'] == 'aidr_channel_unreported'


def test_audit_pause_is_intentional_not_a_heartbeat_failure(service, monkeypatch):
    from backend import aidr_policy
    api, factory = service
    set_target(factory, True)
    with factory() as db:
        policy = aidr_policy.current(db)
    monkeypatch.setattr(aidr_policy, 'current', lambda db, client_id=None: policy | {'lifecycle': {'enabled': False, 'retention_days': 7}})
    state = api.get('/api/v1/clients/one/aidr/status').json()
    assert not state['online']
    assert state['log_channel']['health']['state'] == 'audit_paused'
    assert state['log_channel']['health']['severity'] == 'info'


def test_disabled_target_does_not_hide_a_fresh_running_collector(service):
    api, factory = service
    set_target(factory, False, revision=2)
    set_observation(factory, '1')
    health = api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']
    assert health['state'] == 'awaiting_stop'
    set_observation(factory, '2')
    health = api.get('/api/v1/clients/one/aidr/status').json()['log_channel']['health']
    assert health['state'] == 'disable_not_applied' and health['severity'] == 'warning'
