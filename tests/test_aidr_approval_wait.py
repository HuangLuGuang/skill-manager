import base64
import json
import time

from tests.test_aidr_api import service
from tests.test_aidr_hook_control import base_control, control, policy, pending, decision, ROOT, HEADERS
from backend.aidr_hook_runtime import HookRuntimeRow


def test_deadline_validation_and_existing_attempt_survives_wait_change(control):
    client, factory, _ = control
    result = client.put(ROOT+'/hook-policy', json=policy())
    assert result.status_code == 200, result.text
    assert result.json()['policy']['approval_wait_seconds'] == 180
    row, request = pending(client)
    assert int(row['expires_at']) == request['expires_at']
    for invalid in (None, int(time.time())+301):
        changed = dict(request, expires_at=invalid)
        assert client.post(ROOT+'/hook-approvals', json=changed, headers=HEADERS).status_code == 422
    result = client.put(ROOT+'/hook-policy', json={**policy('1'), 'approval_wait_seconds':300})
    assert result.status_code == 200, result.text
    assert client.get(ROOT+f"/hook-approvals/{row['id']}").json()['approval']['expires_at'] == row['expires_at']
    assert decision(client,row,'allow').status_code == 200
    for value in (29,301,1.5,True,'180'):
        assert client.put(ROOT+'/hook-policy', json={**policy('2'),'approval_wait_seconds':value}).status_code == 422
    with factory() as db:
        db.query(HookRuntimeRow).delete(); db.commit()
    result = client.put(ROOT+'/hook-policy',json=policy('2'))
    assert result.status_code == 409 and result.json()['error_code']=='aidr.hook_approval_wait_upgrade_required'


def test_global_inheritance_device_override_and_return(control):
    client, _, _ = control
    global_url='/api/v1/aidr/tool-policy'
    assert client.put(global_url,json={**policy(),'approval_wait_seconds':240}).status_code==200
    req={'stream_id':'b'*32,'receiver_instance':'e'*32}
    sync=lambda: client.post(ROOT+'/hook-control/snapshot',json=req,headers=HEADERS)
    assert sync().status_code==200
    view=client.get(ROOT+'/hook-policy').json()
    assert view['policy']['approval_wait_seconds']==240
    result=client.put(ROOT+'/hook-policy',json={**policy(view['revision']),'approval_wait_seconds':180,'inherit':False,'expected_scope_revision':view['scope_revision']})
    assert result.status_code==200,result.text
    view=result.json();assert view['policy']['approval_wait_seconds']==180
    result=client.put(ROOT+'/hook-policy',json={**policy(view['revision']),'inherit':True,'expected_scope_revision':view['scope_revision'],'expected_global_revision':view['global_revision']})
    assert result.status_code==200,result.text
    payload=json.loads(base64.b64decode(sync().json()['policy']['payload']))
    assert payload['approval_wait_seconds']==240


def test_legacy_deadline_still_has_platform_upper_bound(control):
    from backend.aidr_hook_control import HookPolicyRow
    from backend.aidr_enforcement import canonical, sign
    client, factory, _ = control
    assert client.put(ROOT+'/hook-policy', json=policy()).status_code == 200
    _, request = pending(client)
    with factory() as db:
        row = db.query(HookPolicyRow).one()
        payload = json.loads(row.payload)
        payload.update(schema=2, domain='aidr.tool-policy/2')
        payload.pop('approval_wait_seconds')
        row.payload, row.envelope = canonical(payload), canonical(sign(payload))
        db.commit()
    request['expires_at'] = int(time.time()) + 3600
    result = client.post(ROOT+'/hook-approvals', json=request, headers=HEADERS)
    assert result.status_code == 422
    assert result.json()['error_code'] == 'aidr.hook_approval_deadline_invalid'
