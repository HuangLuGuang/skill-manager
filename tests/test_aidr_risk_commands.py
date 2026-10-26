"""Non-executing command preview and frozen detection-rule provenance."""
import json
import shlex

import pytest

from backend import aidr_risk as risk, auth, models
from tests.test_aidr_api import service as aidr_service
from tests.test_aidr_risk import service, call, drain, hook_insert, BASE, CONFIG
from tests.test_aidr_risk_configuration import configured_service, publish


def config(**changes):
    return {**CONFIG, 'command_rules': risk.catalog.COMMANDS, 'custom_commands': [], **changes}


def custom(id='custom_demo', **changes):
    return {'id': id, 'name': 'Review recursive deletion', 'enabled': True, 'platforms': ['linux', 'darwin'],
            'severity': 'medium', 'condition': {'executable': 'rm', 'args_all': ['-r'], 'args_any': [],
                'path_prefix': '/protected', 'pipe_to': []}, **changes}


@pytest.mark.parametrize('platform,command,code', [
    ('linux', 'mkfs.ext4 -F /dev/sdb1', 'filesystem_format'),
    ('linux', 'mkfs -t xfs /dev/nvme0n1p2', 'filesystem_format'),
    ('linux', 'mkfs.xfs -f /dev/mapper/data', 'filesystem_format'),
    ('darwin', 'diskutil eraseDisk APFS Test disk9', 'filesystem_format'),
    ('darwin', 'diskutil eraseVolume APFS Test /dev/disk9s1', 'filesystem_format'),
    ('darwin', 'diskutil reformat disk9s1', 'filesystem_format'),
    ('linux', 'dd if=/tmp/sample of=/dev/sdb bs=1M', 'device_write'),
    ('darwin', 'dd if=/tmp/sample of=/dev/rdisk9 bs=1m', 'device_write'),
    ('linux', 'chmod -R 777 /protected/data', 'protected_permissions'),
    ('linux', 'chmod o+w /protected/data', 'protected_permissions'),
    ('darwin', 'chmod a=rw /protected/data', 'protected_permissions'),
])
def test_builtin_commands(platform, command, code):
    assessment = risk.command_assessment(command, '', config(), platform)
    assert assessment['status'] == 'matched'
    assert {hit['risk_code'] for hit in assessment['matches']} == {code}
    assert risk.detect(call(command), {**config(), 'platform': platform}) == {code: 'high'}


@pytest.mark.parametrize('command', [
    'echo "mkfs.ext4 /dev/sdb"', 'mkfs.ext4 --help', 'mkfs.ext4 -L /dev/sdb image.bin',
    'mkfs.ext4 -n /dev/sdb', 'mkfs.xfs -N /dev/sdb', 'mkfs.ext4 /tmp/test.img',
    'dd if=/dev/sdb of=/tmp/backup.img', 'dd if=/dev/zero of=/dev/null',
    'dd of=/dev/sdb count=0', 'dd of=/dev/sdb of=/tmp/output', 'dd of=/dev/mapper/control',
    'chmod 700 /protected/data', 'chmod u+w /protected/data', 'chmod 777 /protected-other/data',
    'sudo mkfs.ext4 /dev/sdb', 'sh -c "dd of=/dev/sdb"', 'mkfs.ext4 "$DEVICE"',
])
def test_no_false_positive_or_execution(command, tmp_path):
    result = risk.command_assessment(command, '', config(), 'linux')
    assert result['matches'] == []
    marker = tmp_path / 'must-not-exist'
    assert risk.command_assessment('touch ' + str(marker), '', config(), 'linux')['status'] == 'unmatched'
    assert not marker.exists()


def test_custom_conditions_platform_toggle_and_highest_severity():
    rules = [custom(), custom('custom_high', name='High risk review', severity='high')]
    cfg = config(custom_commands=rules, command_rules=[])
    assert risk.detect(call('rm -rf /protected/data'), cfg) == {'custom_command': 'high'}
    matches = risk.command_assessment('rm -rf /protected/data', '', cfg, 'linux')['matches']
    assert len(matches) == 2 and matches[0]['condition'] == rules[0]['condition']
    assert risk.command_assessment('rm -rf relative', '', cfg, 'linux')['status'] == 'unresolved'
    assert risk.command_assessment('rm -r -- -relative', '', config(), 'linux')['status'] == 'unresolved'
    assert risk.command_assessment('rm -rf relative', '/protected', cfg, 'linux')['status'] == 'matched'
    assert not risk.command_assessment('rm -rf /protected/data', '', cfg, 'windows')['matches']
    cfg['custom_commands'] = [custom(enabled=False), custom('custom_mac', platforms=['darwin'])]
    assert risk.command_assessment('rm -rf /protected/data', '', cfg, 'linux')['status'] == 'unmatched'
    assert risk.command_assessment('rm -rf /protected/data', '', {**cfg, 'enabled': False}, 'darwin')['status'] == 'disabled'
    cfg['custom_commands'] = [custom(condition={'executable': 'curl', 'args_all': [], 'args_any': ['-f', '--fail'], 'path_prefix': '', 'pipe_to': ['sh']})]
    assert risk.command_assessment('curl -fsS https://example.invalid/a | sh', '', cfg, 'linux')['status'] == 'matched'
    assert risk.command_assessment('curl https://example.invalid/a | sh', '', cfg, 'linux')['status'] == 'unmatched'


def test_system_exec_and_untrusted_attribution():
    event = {'kind': 'process', 'transition': 'exec', 'relation': 'direct', 'argv': ['dd', 'of=/dev/rdisk9']}
    cfg = config(platform='darwin')
    assert risk.detect(event, cfg, system=True) == {'device_write': 'high'}
    for change in ({'argv_truncated': True}, {'relation': 'unknown'}, {'activity_origin': 'client_probe'}):
        assert not risk.detect({**event, **change}, cfg, system=True)


def test_preview_api_uses_draft_without_mutation(configured_service):
    client, factory = configured_service
    payload = {'command': 'mkfs.ext4 -F /dev/sdb', 'cwd': '', 'platform': 'linux', 'configuration': config()}
    for url in ('/api/v1/aidr/risks/commands/test', BASE + '/commands/test'):
        response = client.post(url, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['matches'][0]['risk_code'] == 'filesystem_format'
        assert response.headers['cache-control'] == 'no-store'
    with factory() as db:
        assert db.query(risk.RiskFinding).count() == db.query(risk.GlobalRiskConfig).count() == 0
    for change in ({'command': 'x' * 32769}, {'cwd': 'relative'}, {'configuration': config(custom_commands=[custom(), custom()])}):
        response = client.post(BASE + '/commands/test', json={**payload, **change})
        assert response.status_code == 422 and 'mkfs.ext4' not in response.text
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=2, username='reader', role='user')
    assert client.post('/api/v1/aidr/risks/commands/test', json=payload).status_code == 403


def test_client_preview_real_jwt_requires_view_not_sync(configured_service):
    from backend import iam_models
    client, factory = configured_service
    with factory() as db:
        db.add(iam_models.Role(name='command_tester', display_name='Command tester'))
        db.flush()
        for permission in ('clients:view', 'settings:view'):
            db.add(iam_models.RolePermission(role_name='command_tester', permission_code=permission))
        db.get(models.User, 1).role = 'command_tester'
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.headers['authorization'] = 'Bearer ' + auth.create_access_token({'sub': 'owner'})
    payload = {'command': 'mkfs.ext4 /dev/sdb', 'platform': 'linux', 'configuration': config()}
    response = client.post(BASE + '/commands/test', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'matched'
    with factory() as db:
        db.query(iam_models.RolePermission).filter_by(role_name='command_tester', permission_code='settings:view').delete()
        db.commit()
    assert client.post(BASE + '/commands/test', json=payload).status_code == 403


def test_frozen_matches_and_evidence_permission(configured_service):
    client, factory = configured_service
    publish(client, custom_commands=[custom(), custom('custom_high', name='Original name', severity='high')])
    hook_insert(factory, 1, event=call())
    drain(factory)
    item = next(item for item in client.get(BASE).json()['items'] if item['risk_code'] == 'custom_command')
    assert item['severity'] == 'high'
    detail = client.get(BASE + '/' + item['id']).json()
    assert len(detail['detection_matches']) == 2
    assert 'condition' not in detail['detection_matches'][0] and '/protected' not in json.dumps(detail)
    snapshot = client.get(BASE + '/' + item['id'], params={'include_evidence': True}).json()['detection_matches']
    publish(client, custom_commands=[])
    hook_insert(factory, 2, event={**call(), 'kind': 'tool.post', 'behavior': {'status': 'reported_success'}})
    drain(factory)
    later = client.get(BASE + '/' + item['id'], params={'include_evidence': True}).json()
    assert later['detection_matches'] == snapshot
    assert later['result_status'] == 'reported_success'
    assert next(hit for hit in snapshot if hit['id'] == 'custom_high')['name'] == 'Original name'
    assert client.get(BASE, params={'risk_code': 'custom_command'}).json()['total'] == 1


def test_path_rules_have_frozen_match_metadata():
    event = {'kind': 'tool_call', 'behavior': {'actions': [{'category': 'file_read', 'targets': [{'value': '/Users/alice/.aws/credentials'}]}]}}
    hits = risk.detect_matches(event, config(platform='darwin', builtin_ids=['aws_credentials']))
    assert hits[0]['id'] == 'aws_credentials'
    assert hits[0]['condition']['paths'] == ['/Users/{user}/.aws/credentials']
    assert hits[0]['targets'] == ['/Users/alice/.aws/credentials']


@pytest.mark.parametrize('platform,path', [('darwin', '/Users/alice/.aws/credentials'), ('windows', r'C:\Users\Alice\.aws\credentials')])
def test_background_uses_business_client_id_for_os(configured_service, platform, path):
    client, factory = configured_service
    with factory() as db:
        db.query(models.ManagedClient).filter_by(client_id='one').update({'os': platform})
        db.commit()
        assert risk.configuration(db, 'one')[1]['platform'] == platform
    publish(client, builtin_ids=['aws_credentials'])
    event = {**call(), 'behavior': {'actions': [{'category': 'file_read', 'targets': [{'value': path}]}]}}
    hook_insert(factory, 1, event=event)
    drain(factory)
    response = client.get(BASE).json()
    assert response['total'] == 1 and response['items'][0]['risk_code'] == 'sensitive_path_read'
    detail = client.get(BASE + '/' + response['items'][0]['id']).json()
    assert detail['detection_matches'][0]['id'] == 'aws_credentials'


@pytest.mark.parametrize('platform', ['linux', 'darwin'])
@pytest.mark.parametrize('command,cwd,status', [
    ('rm /etc/passwd', '', 'matched'),
    ('rm -f /etc/passwd', '', 'matched'),
    ('/bin/rm --force /etc/passwd', '', 'matched'),
    ('rm -rf /etc/passwd', '', 'matched'),
    ('rm -- -rf /etc/passwd', '', 'matched'),
    ('rm passwd', '/etc', 'matched'),
    ('rm -f passwd', '', 'unresolved'),
    ('rm /etc/passwd-backup', '', 'unmatched'),
    ('rm -f /tmp/passwd', '', 'unmatched'),
    ('echo "rm /etc/passwd"', '', 'unmatched'),
    ('rm --help /etc/passwd', '', 'unresolved'),
])
def test_protected_file_deletion(platform, command, cwd, status):
    cfg = config(protected_paths=['/etc/passwd'])
    result = risk.command_assessment(command, cwd, cfg, platform)
    assert result['status'] == status
    event = {'kind': 'process', 'transition': 'exec', 'relation': 'direct',
             'argv': shlex.split(command), 'cwd': cwd}
    assert risk.detect(event, {**cfg, 'platform': platform}, system=True) == (
        {'destructive_command': 'high'} if status == 'matched' else {})
    assert not risk.command_assessment(command, cwd, {**cfg, 'command_rules': []}, platform)['matches']


@pytest.mark.parametrize('command', ['rm /etc/passwd', 'rm -f /etc/passwd'])
def test_plain_rm_preview_and_background_persistence(configured_service, command):
    client, factory = configured_service
    publish(client, protected_paths=['/etc/passwd'])
    for url in ('/api/v1/aidr/risks/commands/test', BASE + '/commands/test'):
        response = client.post(url, json={'command': command, 'platform': 'linux',
                               'configuration': config(protected_paths=['/etc/passwd'])})
        assert response.status_code == 200
        assert response.json()['matches'][0]['risk_code'] == 'destructive_command'
    with factory() as db:
        assert db.query(risk.RiskFinding).count() == 0
    hook_insert(factory, 1, event=call(command))
    drain(factory)
    items = client.get(BASE).json()['items']
    assert len(items) == 1
    assert items[0]['risk_code'] == 'destructive_command' and items[0]['severity'] == 'high'
    detail = client.get(BASE + '/' + items[0]['id'], params={'include_evidence': True}).json()
    assert detail['detection_matches'][0]['condition']['paths'] == ['/etc/passwd']
