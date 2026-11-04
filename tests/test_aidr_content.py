"""Independent scope, privacy, receipt and body-access expectations."""
import copy
import json

import pytest

from backend import aidr_policy, auth, iam, models
from backend.aidr_behavior import AuditPolicy, Behavior
from backend.aidr_content import Content, metadata_view, validate_contents
from backend.aidr_migrations import upgrade_aidr_schema
from tests.test_aidr_api import batch, service, submit
from tests.test_aidr_hooks import hook_batch, send
from tests.test_aidr_redaction import behavior


SCOPE = dict(prompt=True, tool_output=True, file_body=True)


def issue(client, stream='a' * 32, **body):
    result = client.post('/api/v1/clients/one/aidr/audit-policy',
                        json={'stream_id': stream, 'last_sequence': '0', **body},
                        headers={'authorization': 'Bearer test-one', 'X-AIDR-Policy-Schema': '2'})
    assert result.status_code == 200, result.text
    return result.json()


def fragment(text='SYNTHETIC-BODY-ONLY', kind='tool_output', field='result.text'):
    return dict(kind=kind, source_field=field, block=0, text=text,
                source_bytes=len(text.encode()), redacted=False, truncated=False)


def test_codex_native_patch_command_contract():
    policy = dict(version='2', enabled=True, receipt='a'*32, capture=SCOPE)
    value = behavior(policy, '')
    value.update(version=4, category='patch', contents=[fragment(
        '*** Begin Patch\n*** Add File: audit.txt\n+TOKEN=[REDACTED]\n*** End Patch\n',
        kind='file_body', field='input.command')], content_status='captured')
    value['contents'][0]['redacted'] = True
    value['actions'] = [dict(tool='apply_patch', category='patch', command='', cwd='',
                            targets=[dict(kind='file', value='audit.txt')], source_fields=['command', 'patch.header'])]
    parsed = Behavior.model_validate(value)
    assert parsed.status == 'unknown' and parsed.exit_code is None
    for category in ('command', 'file_write'):
        invalid = copy.deepcopy(value)
        invalid['category'] = category
        with pytest.raises(ValueError, match='behavior_content_source_invalid'):
            Behavior.model_validate(invalid)
    invalid = copy.deepcopy(value)
    invalid['policy']['capture']['file_body'] = False
    with pytest.raises(ValueError):
        Behavior.model_validate(invalid)


def event_batch(policy, text='SYNTHETIC-BODY-ONLY'):
    value = batch()
    event = value['records'][0]['payload']
    event['schema_version'] = 2
    event['kind'] = 'tool_result'
    event['behavior'] = behavior(policy, '')
    event['behavior'].update(version=4, category='unknown', method='result_fields', actions=[],
                             contents=[fragment(text)], content_status='captured')
    return value


def configure(factory, **values):
    with factory() as db:
        row = db.get(models.SystemConfig, aidr_policy.KEY)
        payload = {'enabled': True, 'version': '2', 'capture': SCOPE, **values}
        if row:
            row.value = json.dumps(payload)
        else:
            db.add(models.SystemConfig(key=aidr_policy.KEY, value=json.dumps(payload)))
        db.commit()


def test_scope_defaults_legacy_negotiation_and_forgery(service):
    client, factory = service
    default = issue(client)
    assert default['capture'] == dict(prompt=True, tool_output=False, file_body=True)
    assert submit(client, event_batch(default)).status_code == 422
    configure(factory)
    scoped = issue(client)
    assert scoped['capture'] == SCOPE
    legacy = client.post('/api/v1/clients/one/aidr/audit-policy',
                         json=dict(stream_id='a'*32, last_sequence='0'),
                         headers={'authorization': 'Bearer test-one'}).json()
    assert 'capture' not in legacy and legacy['receipt'] != scoped['receipt']
    forged = copy.deepcopy(event_batch(scoped))
    forged['records'][0]['payload']['behavior']['policy']['capture']['file_body'] = False
    assert submit(client, forged).status_code == 409
    assert submit(client, event_batch(scoped), extra_headers={'x-aidr-stream-id': 'b'*32}).status_code == 409
    assert submit(client, event_batch(scoped), credential='two', target='two').status_code == 409
    assert submit(client, event_batch(scoped, 'TOKEN=SYNTHETIC-CONTENT-SECRET')).status_code == 422


def test_contents_hidden_in_every_view_separate_permission_and_audit(service):
    client, factory = service
    configure(factory)
    policy = issue(client)
    value = event_batch(policy)
    ack = submit(client, value)
    assert ack.status_code == 200, ack.text
    assert submit(client, value).json() == ack.json()
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: actor
    with factory() as db:
        iam.initialize(db)
    for path in ('events', 'operations'):
        response = client.get('/api/v1/clients/one/aidr/' + path)
        assert response.status_code == 200
        assert 'SYNTHETIC-BODY-ONLY' not in response.text
        assert 'stored_bytes' in response.text
    record_id = value['records'][0]['payload']['logical_event_id']
    url = f'/api/v1/clients/one/aidr/content?source=log&record_id={record_id}'
    response = client.get(url)
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['contents'][0]['text'] == 'SYNTHETIC-BODY-ONLY'
    actor.role = 'user'
    assert client.get(url).status_code == 403
    actor.role = 'admin'
    actor.username = 'another-owner'
    assert client.get(url).status_code == 404  # Body permission does not bypass device visibility.
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 1
        audits = db.query(models.OperationLog).filter_by(action='aidr.content_view').all()
        assert len(audits) == 1 and 'SYNTHETIC-BODY-ONLY' not in audits[0].details


def test_parsed_command_content_preserves_permissions_and_original(service):
    from tests.test_aidr_overview import hook, drain, BASE
    from backend.aidr_models import AidrHookEvent

    client, factory = service
    original = "sed -n '1,3p' PRIVATE-PARSED-ARG\nrg one file && rg two file"
    value = behavior(dict(version='2', enabled=True, receipt='a'*32, capture=SCOPE), '')
    value.update(category='command', contents=[fragment(original, 'command_body', 'input.command')])
    record_id = hook(factory, 1, behavior=value)
    drain(factory)
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: actor
    with factory() as db:
        iam.initialize(db)
        stored = db.get(AidrHookEvent, record_id).payload_json
    for path in (BASE, BASE + '/entry?record_id=' + str(record_id), '/api/v1/clients/one/aidr/hooks'):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert 'PRIVATE-PARSED-ARG' not in response.text
    url = f'/api/v1/clients/one/aidr/content?source=hook&record_id={record_id}'
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    content = next(item for item in response.json()['contents'] if item['kind'] == 'command_body')
    assert content['text'] == original
    assert [item['program'] for item in content['command_analysis']['commands']] == ['sed', 'rg', 'rg']
    assert all('status' not in item for item in content['command_analysis']['commands'])
    actor.role = 'user'
    assert client.get(url).status_code == 403
    actor.role = 'admin'
    actor.username = 'another-owner'
    assert client.get(url).status_code == 404
    with factory() as db:
        assert db.get(AidrHookEvent, record_id).payload_json == stored
        assert all('PRIVATE-PARSED-ARG' not in row.details for row in db.query(models.OperationLog).all())


@pytest.mark.parametrize('source', ['hook', 'log'])
@pytest.mark.parametrize('mode', ['legacy', 'captured', 'wrapper'])
def test_view_only_account_cannot_read_commands_or_subcommands(service, source, mode):
    from backend import iam_models
    from backend.aidr_operations import merge_operation
    from tests.test_aidr_overview import hook, drain, BASE
    from tests.test_aidr_operations import event

    client, factory = service
    value = behavior(dict(version='2', enabled=True, receipt='a'*32),
                     'rg PRIVATE-LEGACY-COMMAND file; sed -n 1p file')
    if mode == 'captured':
        value['contents'] = [fragment(value['actions'][0]['command'], 'command_body', 'input.command')]
    elif mode == 'wrapper':
        value['category'] = 'wrapper'
        value['contents'] = [fragment('await tools.exec_command({cmd:"rg PRIVATE-LEGACY-COMMAND file"})', 'command_body', 'input.code')]
    if source == 'hook':
        record_id = hook(factory, 1, behavior=value)
        content_id = str(record_id)
        paths = ['/api/v1/clients/one/aidr/hooks', f'/api/v1/clients/one/aidr/hooks/{record_id}/related']
    else:
        raw = event('tool_call', schema_version=2, behavior=value)
        with factory() as db:
            row = models.AidrEvent(client_id='one', logical_id=raw['logical_event_id'], content_hash='a'*64,
                                   agent='codex', kind='tool_call', payload_json=json.dumps(raw))
            db.add(row); db.flush()
            merge_operation(db.connection(), 'one', raw)
            record_id, content_id = row.id, row.logical_id
            db.commit()
        paths = ['/api/v1/clients/one/aidr/events', '/api/v1/clients/one/aidr/operations']
    drain(factory)
    with factory() as db:
        iam.initialize(db)
        db.add(iam_models.Role(name='command_reader', display_name='Command reader'))
        db.flush()
        db.add(iam_models.RolePermission(role_name='command_reader', permission_code='clients:view'))
        user = db.get(models.User, 1)
        user.role = 'command_reader'
        db.commit()
        assert iam.permission_codes(db, user) == {'clients:view'}
    # Exercise the real token, route-permission and content-permission dependencies.
    client.app.dependency_overrides.pop(auth.get_current_admin_user, None)
    client.headers['authorization'] = 'Bearer ' + auth.create_access_token({'sub': 'owner'})
    paths += [BASE + '?source=' + source + 's', BASE + f'/entry?source={source}s&record_id={record_id}']
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert 'PRIVATE-LEGACY-COMMAND' not in response.text
        assert 'command_analysis' not in response.text
    url = f'/api/v1/clients/one/aidr/content?source={source}&record_id={content_id}'
    response = client.get(url)
    assert response.status_code == 403
    assert 'PRIVATE-LEGACY-COMMAND' not in response.text
    with factory() as db:
        db.add(iam_models.RolePermission(role_name='command_reader', permission_code='clients:read-audit-content'))
        db.commit()
    permitted = client.get(url)
    assert permitted.status_code == 200 and 'PRIVATE-LEGACY-COMMAND' in permitted.text
    analysis = [item['command_analysis'] for item in permitted.json()['contents'] if 'command_analysis' in item]
    assert len(analysis) == 1
    assert [cmd['program'] for cmd in analysis[0]['commands']] == ['rg', 'sed']
    assert client.get(url.replace('/one/', '/two/')).status_code == 404
    with factory() as db:
        grant = db.get(iam_models.RolePermission, ('command_reader', 'clients:read-audit-content'))
        db.delete(grant); db.commit()
    assert client.get(url).status_code == 403  # A prior permitted request must not seed a shared response cache.


def test_prompt_hook_scope_backlog_and_strict_ack(service):
    client, factory = service
    configure(factory)
    policy = issue(client, stream='b'*32)
    value = hook_batch()
    event = value['records'][0]['event']
    event.update(schema_version=2, hook_event='UserPromptSubmit', kind='turn.submit', policy=policy,
                 contents=[fragment('Fictional prompt', 'prompt', 'hook.prompt')], content_status='captured')
    first = send(client, value)
    assert first.status_code == 200, first.text
    configure(factory, version='3', capture=dict.fromkeys(SCOPE, False))
    newer = issue(client, stream='b'*32, last_sequence='1', applied_receipt=policy['receipt'], applied_after='0')
    issue(client, stream='b'*32, last_sequence='1', applied_receipt=newer['receipt'], applied_after='1')
    assert send(client, value).json() == first.json()  # Historical exact frozen bytes remain valid.
    late = copy.deepcopy(value)
    late['records'][0].update(event_id='d'*32, source_seq='2')
    assert send(client, late).status_code == 409
    late['records'][0]['event']['policy'] = newer
    assert send(client, late).status_code == 422  # Scope alone cannot authorize prompt content.
    rows = client.get('/api/v1/clients/one/aidr/hooks').json()['items']
    assert len(rows) == 1 and 'Fictional prompt' not in json.dumps(rows)
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: actor
    with factory() as db:
        iam.initialize(db)
    content = client.get(f"/api/v1/clients/one/aidr/content?source=hook&record_id={rows[0]['id']}")
    assert content.status_code == 200, content.text
    assert content.json()['contents'][0]['text'] == 'Fictional prompt'


def test_content_budgets_secret_policy_and_source_boundaries():
    policy = AuditPolicy.model_validate(dict(version='2', enabled=True, receipt='a'*32, capture=SCOPE))
    for text in ('--password="SYNTHETIC-VALUE"', 'Authorization: Bearer SYNTHETIC-ABC', 'TOKEN=SYNTHETIC-DEF'):
        with pytest.raises(ValueError, match='secret'):
            validate_contents([Content(**fragment(text))], 'captured', policy)
    raw = AuditPolicy.model_validate({**policy.model_dump(), 'enabled': False})
    validate_contents([Content(**fragment('TOKEN=SYNTHETIC-DEF'))], 'captured', raw)
    with pytest.raises(ValueError):
        validate_contents([Content(**fragment('你'*400))], 'captured', raw)
    with pytest.raises(ValueError):
        Content(**fragment('你'*11000))
    with pytest.raises(ValueError, match='limit'):
        validate_contents([Content(**fragment('x'*1024))]*3, 'partial', raw)
    with pytest.raises(ValueError):
        Content(**fragment(kind='tool_output', field='input.unknown'))
    value = behavior(raw.model_dump(), '/bin/true')
    value.update(version=4, contents=[fragment('prompt', 'prompt', 'hook.prompt')], content_status='captured')
    with pytest.raises(ValueError, match='source'):
        Behavior.model_validate(value)
    assert metadata_view({'event': {'contents': [fragment()]}})['event']['contents'][0]['stored_bytes'] == 19


def test_existing_receipts_and_evidence_survive_nullable_scope_migration(service):
    client, factory = service
    legacy = client.post('/api/v1/clients/one/aidr/audit-policy', json=dict(stream_id='a'*32, last_sequence='0'), headers={'authorization': 'Bearer test-one'}).json()
    assert submit(client).status_code == 200
    with factory() as db:
        engine = db.get_bind()
    with engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE aidr_policy_receipts DROP COLUMN capture_json')
        receipt = list(conn.exec_driver_sql('SELECT * FROM aidr_policy_receipts').all())
        evidence = list(conn.exec_driver_sql('SELECT * FROM aidr_events').all())
        batches = list(conn.exec_driver_sql('SELECT * FROM aidr_batches').all())
    upgrade_aidr_schema(engine)
    upgrade_aidr_schema(engine)
    with engine.connect() as conn:
        assert [tuple(row[:-1]) for row in conn.exec_driver_sql('SELECT * FROM aidr_policy_receipts')] == receipt
        assert conn.exec_driver_sql('SELECT capture_json FROM aidr_policy_receipts').scalar() is None
        assert list(conn.exec_driver_sql('SELECT * FROM aidr_events').all()) == evidence
        assert list(conn.exec_driver_sql('SELECT * FROM aidr_batches').all()) == batches
    assert submit(client).status_code == 200
    assert issue(client)['receipt'] != legacy['receipt']
