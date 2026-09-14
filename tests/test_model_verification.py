import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.model_verification import probe_evidence, record_probe
from backend.routers.clients import _issue_agent_runtime_credential, _create_model_operation
from backend.sqlite_db import Base

MARKER = 'AM_VERIFY_12345678-1234-1234-1234-123456789abc'


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "probe.db"}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def setup_identity(db):
    client = models.ManagedClient(client_id='probe-client', name='Probe', hostname='test', os='darwin', arch='arm64', client_version='test')
    parent = models.AccessToken(name='Client', token_type='client', token_hash='parent', token_prefix='parent', bound_client_id='probe-client', scopes_json='[]')
    agent = models.ManagedAgent(agent_id='probe-agent', name='Probe', channel='claude-code')
    db.add_all([client, parent, agent])
    db.commit()
    return parent, agent


def test_credential_rotation_retains_latest_recovery_and_retry_does_not_revoke_it(database):
    db = database
    parent, agent = setup_identity(db)
    tasks = [models.ClientTask(client_id='probe-client', task_type='apply_model_config', payload_json='{}') for _ in range(3)]
    db.add_all(tasks)
    db.commit()
    def issue(task, model):
        return _issue_agent_runtime_credential(db, client_token=parent, client_id='probe-client', agent=agent, model_name=model, task=task)[1]
    first = issue(tasks[0], 'A')
    second = issue(tasks[1], 'B')
    db.refresh(first)
    assert first.status == 'active'
    retried = issue(tasks[1], 'B')
    db.refresh(first)
    db.refresh(second)
    assert first.status == 'active'
    assert second.status == 'revoked'
    third = issue(tasks[2], 'C')
    db.refresh(first)
    db.refresh(retried)
    assert first.status == 'revoked'
    assert retried.status == third.status == 'active'
    assert db.query(models.AccessToken).filter_by(token_type='agent_runtime', status='active').count() == 2
    assert json.loads(tasks[2].payload_json)['previous_credential_id'] == retried.id


def test_gateway_evidence_requires_matching_audit_and_never_contains_prompt(database):
    db = database
    parent, agent = setup_identity(db)
    key = models.AccessToken(name='Agent', token_type='agent_runtime', token_hash='runtime', token_prefix='runtime', bound_agent_id=agent.agent_id, issued_by_client_token_id=parent.id)
    db.add(key)
    db.commit()
    payload = schemas.ChatCompletionRequest(model='A', messages=[{'role':'user','content':'Private text. Reply with ' + MARKER}], stream=True, max_tokens=123)
    record_probe(db, key, payload, 'req_probe')
    event = db.query(models.ClientEvent).one()
    assert 'Private text' not in event.details_json
    assert key.token_hash not in event.details_json
    assert probe_evidence(db, 'other-client', agent.agent_id, MARKER) == []
    assert probe_evidence(db, 'probe-client', 'other-agent', MARKER) == []
    assert probe_evidence(db, 'probe-client', agent.agent_id, MARKER)[0]['status'] == 'pending'
    db.add(models.LlmRequestAudit(request_id='req_probe', tenant_id='test', conversation_id='test', user_ref='test', api_key_id=key.id, credential_type='agent_runtime', agent_id=agent.agent_id, model='A', status='success', created_at=datetime.utcnow()))
    db.commit()
    evidence = probe_evidence(db, 'probe-client', agent.agent_id, MARKER)
    assert evidence == [{'request_id':'req_probe','model':'A','status':'success','parameters':{'stream':True,'max_tokens':123}}]


def test_switch_after_restore_retains_the_credential_in_native_configuration(database):
    db = database
    parent, agent = setup_identity(db)
    tasks = [models.ClientTask(client_id='probe-client', task_type='apply_model_config', payload_json='{}') for _ in range(3)]
    db.add_all(tasks)
    db.commit()
    def issue(task, model, previous=None):
        return _issue_agent_runtime_credential(db, client_token=parent, client_id='probe-client', agent=agent,
            model_name=model, task=task, previous_credential_hash=previous)[1]
    first = issue(tasks[0], 'A')
    second = issue(tasks[1], 'B', first.token_hash)
    third = issue(tasks[2], 'C', first.token_hash)
    db.refresh(first)
    db.refresh(second)
    assert first.status == third.status == 'active'
    assert second.status == 'revoked'
    assert json.loads(tasks[2].payload_json)['previous_credential_id'] == first.id


def test_concurrent_model_operation_creation_returns_one_task(database):
    db = database
    setup_identity(db)
    state = {'change_id':'change', 'revision':'a'*64, 'model':'A', 'can_restore':True}
    db.add(models.ClientAgent(client_id='probe-client', local_agent_id='codex', agent_type='codex',
        capabilities_json=json.dumps({'model_config_state':state, 'model_config_verification':True})))
    db.commit()
    engine = db.get_bind()
    payload = {'agent_type':'codex', 'local_agent_id':'codex', 'change_id':'change', 'expected_revision':'a'*64}
    def create(_):
        with Session(engine) as worker:
            return _create_model_operation(worker, 'probe-client', 'verify_model_config', payload, 'test').id
    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(create, range(2)))
    assert ids[0] == ids[1]
    assert db.query(models.ClientTask).count() == 1


def test_ordinary_request_does_not_create_probe_event(database):
    parent, agent = setup_identity(database)
    payload = schemas.ChatCompletionRequest(model='A', messages=[{'role':'user','content':'hello'}])
    record_probe(database, parent, payload, 'req_ordinary')
    assert database.query(models.ClientEvent).count() == 0
