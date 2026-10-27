"""Windows detection uses command text only; these tests never run a Windows command."""
import pytest
from pydantic import ValidationError

from backend import aidr_risk as risk, models
from backend import aidr_risk_windows as win
from backend.aidr_command_rules import CommandCondition
from tests.test_aidr_api import service as aidr_service
from tests.test_aidr_risk import service, call, hook_insert, drain, BASE
from tests.test_aidr_risk_configuration import configured_service, publish
from tests.test_aidr_risk_commands import config, custom


def cfg(**changes):
    return config(protected_paths=[r'C:\Protected'], platform='windows', **changes)


@pytest.mark.parametrize('command,code', [
    ('format D: /FS:NTFS /Q', 'filesystem_format'),
    (r'"C:\Windows\System32\format.exe" D: /q', 'filesystem_format'),
    ('Format-Volume -DriveLetter D -FileSystem NTFS -Confirm:$false', 'filesystem_format'),
    ('powershell.exe -NoProfile -Command "Format-Volume -DriveLetter D -Force"', 'filesystem_format'),
    ('Clear-Disk -Number 2 -RemoveData -Confirm:$false', 'device_write'),
    (r'dd.exe if=image.bin of=\\.\PhysicalDrive2 bs=1M', 'device_write'),
    (r'del /s /q C:\Protected\*', 'destructive_command'),
    (r'cmd.exe /d /c "rd /s /q C:\Protected"', 'destructive_command'),
    (r'RD /S C:\PROTECTED\child', 'destructive_command'),
    (r'Remove-Item -LiteralPath "C:\Protected\some folder" -Recurse -Force', 'destructive_command'),
    (r'pwsh -Command "rm -Path C:\Protected -Recurse"', 'destructive_command'),
    (r'rm C:\Protected -Recurse', 'destructive_command'),
    (r'icacls C:\Protected /grant Everyone:F /t', 'protected_permissions'),
    (r'icacls C:\Protected /grant "*S-1-1-0:(OI)(CI)F"', 'protected_permissions'),
    (r'takeown /f C:\Protected /a /r /d Y', 'protected_permissions'),
])
def test_matches(command, code):
    result = risk.command_assessment(command, '', cfg(), 'windows')
    assert result['status'] == 'matched', result
    assert {h['risk_code'] for h in result['matches']} == {code}
    assert result['matches'][0]['targets']
    assert risk.detect(call(command), cfg(), windows=True) == {code: 'high'}


@pytest.mark.parametrize('command,status', [
    ('format /?', 'unmatched'),
    ('Format-Volume -DriveLetter D -WhatIf', 'unmatched'),
    ('Clear-Disk -Number 2 -WhatIf:$true', 'unmatched'),
    (r'Remove-Item C:\Protected -WhatIf', 'unmatched'),
    (r'del C:\Protected -WhatIf', 'unmatched'),
    (r'del C:\Protected-other\a', 'unmatched'),
    (r'dd.exe if=\\.\PhysicalDrive2 of=backup.img', 'unmatched'),
    (r'dd.exe of=\\.\PhysicalDrive2 count=0', 'unmatched'),
    (r'icacls C:\Protected', 'unmatched'),
    (r'icacls C:\Protected /grant Everyone:R', 'unmatched'),
    (r'icacls C:\Protected /grant Admin:F', 'unmatched'),
    (r'echo "format D: /Q"', 'unmatched'),
    (r'Format-Volume -DriveLetter D -Unknown', 'unresolved'),
    (r'Remove-Item $target -Recurse', 'unresolved'),
    (r'cmd /c del %TEMP%\a', 'unresolved'),
    (r'cmd /c "del C:\Protected > nul"', 'unresolved'),
    (r'pwsh -EncodedCommand abcdef', 'unresolved'),
    (r'.\cleanup.ps1', 'unresolved'),
    (r'del C:\Protected\!name!', 'unresolved'),
    (r'diskpart /s cleanup.txt', 'unresolved'),
    (r'Set-Acl C:\Protected $acl', 'unresolved'),
    (r'del relative', 'unresolved'),
    (r'del C:relative', 'unresolved'),
    (r'del \Protected', 'unresolved'),
    (r'del C:\Pro*\file', 'unresolved'),
    (r'Remove-Item -LiteralPath C:\Protected\*', 'unresolved'),
    (r'takeown /s remote /f C:\Protected', 'unresolved'),
    ('Remove-Item ""', 'unresolved'),
    ("Remove-Item 'C:\\Protected''Other'", 'unresolved'),
])
def test_negative_and_unresolved(command, status):
    result = risk.command_assessment(command, '', cfg(), 'windows')
    assert result['status'] == status, result
    assert not result['matches']


def test_windows_paths_and_custom_contract():
    rule = custom(platforms=['windows'], condition={'executable': r'C:\Program Files\Tool\wipe.exe',
                  'args_all': ['/erase'], 'args_any': [], 'path_prefix': r'C:\Protected', 'pipe_to': []})
    risk.DetectionConfig.model_validate(config(custom_commands=[rule]))
    with pytest.raises(ValidationError):
        CommandCondition.model_validate(rule['condition'])
    command = r'"C:\Program Files\Tool\wipe.exe" /ERASE child'
    result = risk.command_assessment(command, r'C:\Protected', cfg(custom_commands=[rule]), 'windows')
    assert result['matches'][0]['id'] == 'custom_demo'
    assert risk.command_assessment(command, '', cfg(custom_commands=[rule]), 'windows')['status'] == 'unresolved'
    assert risk.command_assessment(command, r'C:\Protected', cfg(custom_commands=[{**rule, 'enabled': False}]), 'windows')['status'] == 'unmatched'
    assert win.target_path(r'\\server\share\protected\*', '') == r'\\server\share\protected'
    assert risk.command_assessment('del child', r'C:\Protected', cfg(), 'windows')['status'] == 'matched'
    assert risk.command_assessment('format D:', '', {**cfg(), 'enabled': False}, 'windows')['status'] == 'disabled'
    assert risk.command_assessment('format D:', '', cfg(command_rules=[]), 'windows')['status'] == 'unmatched'
    assert risk.command_assessment('Format-Volume -DriveLetter D -WhatIf:$false', '', cfg(), 'windows')['status'] == 'matched'
    pipeline_rule = custom(platforms=['windows'], condition={'executable': 'Get-Content', 'pipe_to': ['writer.exe']})
    result = risk.command_assessment('Get-Content file | WRITER.EXE', '', cfg(custom_commands=[pipeline_rule]), 'windows')
    assert result['matches'][0]['id'] == 'custom_demo'
    assert risk.command_assessment('Get-Content file | other.exe', '', cfg(custom_commands=[pipeline_rule]), 'windows')['status'] == 'unmatched'


def test_windows_api_and_frozen_trace(configured_service):
    client, factory = configured_service
    command = r'icacls C:\Protected /grant Everyone:F'
    rule = custom(platforms=['windows'], condition={'executable': 'icacls', 'args_all': ['/grant'], 'path_prefix': r'C:\Protected'})
    draft = cfg(custom_commands=[rule])
    draft.pop('platform')
    for route in ('/api/v1/aidr/risks/commands/test', BASE + '/commands/test'):
        result = client.post(route, json={'command': command, 'cwd': r'C:\Protected', 'platform': 'windows', 'configuration': draft})
        assert result.status_code == 200, result.text
        assert len(result.json()['matches']) == 2
    with factory() as db:
        assert db.query(risk.RiskFinding).count() == 0
        db.query(models.ManagedClient).filter_by(client_id='one').update({'os': 'windows'})
        db.commit()
    assert client.get(BASE + '/configuration').json()['platform'] == 'windows'
    publish(client, protected_paths=[r'C:\Protected'], command_rules=risk.commands.COMMANDS, custom_commands=[rule])
    hook_insert(factory, 1, event=call(command))
    drain(factory)
    items = client.get(BASE).json()['items']
    assert {item['risk_code'] for item in items} == {'protected_permissions', 'custom_command'}
    item = next(i for i in items if i['risk_code'] == 'protected_permissions')
    assert 'targets' not in client.get(BASE + '/' + item['id']).json()['detection_matches'][0]
    detail = client.get(BASE + '/' + item['id'], params={'include_evidence': True}).json()
    assert detail['detection_matches'][0]['targets'] == [r'C:\Protected']
    publish(client, custom_commands=[], command_rules=[])
    assert client.get(BASE + '/' + item['id'], params={'include_evidence': True}).json()['detection_matches'] == detail['detection_matches']


def test_powershell_behavior_contract():
    from backend.aidr_behavior import Action
    action = Action.model_validate({'tool': 'PowerShell', 'category': 'command',
        'command': r'Remove-Item C:\Protected -Recurse', 'cwd': r'C:\Work', 'targets': [], 'source_fields': ['command', 'cwd']})
    event = {'kind': 'tool_call', 'behavior': {'actions': [action.model_dump()]}}
    assert risk.detect(event, cfg(), windows=True) == {'destructive_command': 'high'}
