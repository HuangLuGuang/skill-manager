"""Configurable body budgets and command capture across policy and upload."""
import copy
import pytest

from backend.aidr_behavior import Behavior
from backend.aidr_content import CaptureScope
from tests.test_aidr_api import service, submit, batch
from tests.test_aidr_client_policy import policies, draft, GLOBAL, LOCAL
from tests.test_aidr_content import configure, fragment
from tests.test_aidr_redaction import behavior


def test_command_capture_default_and_explicit_disable_survive_reload(policies):
    client, factory, _ = policies
    initial = client.get(GLOBAL).json()
    assert initial['capture']['command_body'] is True
    disabled = client.put(GLOBAL, json=dict(version=initial['version'], enabled=True,
                          capture={**initial['capture'], 'command_body': False})).json()
    assert disabled['capture']['command_body'] is False
    assert client.get(GLOBAL).json()['capture']['command_body'] is False
    assert client.get(LOCAL).json()['capture']['command_body'] is False
    # Historical receipts without the field continue to mean not captured.
    assert CaptureScope.model_validate({'prompt': True}).command_body is False
    from backend import aidr_policy, models
    import json
    with factory() as db:
        row = db.get(models.SystemConfig, aidr_policy.KEY)
        old = json.loads(row.value)
        old['capture'].pop('command_body')
        row.value = json.dumps(old)
        db.commit()
    assert client.get(GLOBAL).json()['capture'].get('command_body', False) is False


def test_policy_limits_global_override_and_legacy_delivery(policies):
    client, _, _ = policies
    scope = dict(command_body=True, prompt=True, max_fragment_bytes=8192, max_event_bytes=16384)
    response = client.put(GLOBAL, json=dict(version='1', enabled=True, capture=scope))
    assert response.status_code == 200, response.text
    inherited = client.get(LOCAL).json()
    assert inherited['inherit'] and inherited['capture']['max_fragment_bytes'] == 8192
    request = dict(stream_id='a'*32, last_sequence='0')
    headers = {'authorization': 'Bearer test-one', 'X-AIDR-Policy-Schema': '2'}
    old = client.post(LOCAL, json=request, headers=headers).json()
    assert 'command_body' not in old['capture'] and 'max_fragment_bytes' not in old['capture']
    new = client.post(LOCAL, json=request, headers={**headers, 'X-AIDR-Content-Options': '1'}).json()
    assert new['capture']['command_body'] and new['capture']['max_fragment_bytes'] == 8192
    override = client.put(LOCAL, json=draft(inherited, capture={**scope, 'max_fragment_bytes':4096})).json()
    assert not override['inherit'] and override['capture']['max_fragment_bytes'] == 4096
    assert client.get(GLOBAL).json()['capture']['max_fragment_bytes'] == 8192
    for invalid in ({'max_fragment_bytes': 8193, 'max_event_bytes':8192}, {'max_event_bytes':32769}, {'max_fragment_bytes':255}, {'max_fragment_bytes':1.5}):
        assert client.put(LOCAL, json=draft(override, capture=invalid)).status_code == 422
    restored=client.put(LOCAL, json=draft(override, inherit=True)).json()
    assert restored['inherit'] and restored['capture']['max_fragment_bytes'] == 8192
    assert client.post(LOCAL, json=request, headers={**headers, 'X-AIDR-Content-Options':'2'}).status_code == 422


def test_command_body_upload_bounds_redaction_and_receipt(service):
    client, factory = service
    configure(factory, capture=dict(prompt=False, tool_output=False, file_body=False, command_body=True, max_fragment_bytes=8192, max_event_bytes=8192))
    policy = client.post(LOCAL, json=dict(stream_id='a'*32,last_sequence='0'),
        headers={'authorization':'Bearer test-one','X-AIDR-Policy-Schema':'2','X-AIDR-Content-Options':'1'}).json()
    text = "cat <<'EOF'\n" + '正文'*600 + '\nTOKEN=[REDACTED]\nEOF'
    value=batch(); event=value['records'][0]['payload'];event['schema_version']=2
    event['behavior']=behavior(policy, 'cat [HEREDOC OMITTED]')
    event['behavior'].update(version=4,body_omitted=True,contents=[fragment(text,'command_body','input.command')], content_status='captured')
    result=submit(client,value)
    assert result.status_code==200, result.text
    assert submit(client,value).json()==result.json()
    assert text not in client.get('/api/v1/clients/one/aidr/events').text
    for change in ('scope','secret','size','source','receipt'):
        wrong=copy.deepcopy(value);b=wrong['records'][0]['payload']['behavior']
        if change=='scope': b['policy']['capture']['command_body']=False
        if change=='secret': b['contents'][0]['text']='TOKEN=RAW-SECRET'
        if change=='size': b['contents'][0]['text']='你'*3000
        if change=='source': b['contents'][0]['source_field']='input.code'
        if change=='receipt': b['policy']['capture']['max_event_bytes']=16384
        assert submit(client,wrong).status_code==(409 if change=='receipt' else 422)
    # Explicit command-body scope accepts wrapper source without claiming execution.
    wrapper=copy.deepcopy(event['behavior']);wrapper.update(category='wrapper',method='literal_wrapper')
    wrapper['contents']=[fragment('text(await tools.exec_command({cmd:"echo hello"}));','command_body','input.code')]
    assert Behavior.model_validate(wrapper).contents[0].kind=='command_body'


def test_capture_default_serialization_preserves_existing_receipts():
    assert CaptureScope().model_dump()==dict(prompt=False,tool_output=False,file_body=False)
    assert CaptureScope(max_fragment_bytes=1024,max_event_bytes=2048).model_dump()==CaptureScope().model_dump()
    with pytest.raises(ValueError): CaptureScope(max_fragment_bytes=8192,max_event_bytes=4096)
