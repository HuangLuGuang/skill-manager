import base64
import hashlib
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from backend import auth, models
from backend import aidr_hook_control as control_logic
from backend.aidr_enforcement import canonical, sign
from tests.test_aidr_enforcement import control as base_control
import pytest
from tests.test_aidr_api import service
from tests.test_aidr_hooks import hook_batch, send

ROOT = "/api/v1/clients/one/aidr"
HEADERS = {"authorization": "Bearer test-one"}
INSTANCE = "e"*32


@pytest.fixture
def control(base_control):
    from backend.aidr_hook_runtime import HookRuntimeRow
    client, factory, key = base_control
    with factory() as db:
        db.add(HookRuntimeRow(client_id='one', stream_id='b'*32, receiver_instance=INSTANCE,
                             sequence=1, received_at=int(time.time()), payload=json.dumps({'approval_wait_schema': 1, 'control_revision': '', 'control_mode': 'audit'})))
        db.commit()
    return client, factory, key


def test_client_attempt_receipt_exact_scope_durable_replay_and_terminal_gate(control):
    client, factory, _ = control
    assert client.put(ROOT+"/hook-policy", json=policy()).status_code==200
    row, request=pending(client)
    body={"schema_version":1,"client_id":"one","stream_id":request["stream_id"],"event_id":request["event_id"],"receiver_instance":INSTANCE,"approval_id":row["id"],"state":"denied","code":"aidr_hook_approval_timeout","reported_at":str(int(time.time()))}
    raw=json.dumps(body,separators=(',',':')).encode()
    first=client.post(ROOT+"/hook-attempt-reports",content=raw,headers={**HEADERS,"content-type":"application/json"})
    assert first.status_code==200,first.text
    assert first.json()["durable"] and first.json()["digest"]==hashlib.sha256(raw).hexdigest()
    assert client.post(ROOT+"/hook-attempt-reports",content=raw,headers=HEADERS).json()==first.json()
    detail=client.get(ROOT+f"/hook-approvals/{row['id']}").json()
    assert detail["client_report"]["record"]==body and detail["client_report"]["evidence_type"]=="client_report"
    assert detail["approval"]["recorded_state"]=="pending"  # Client evidence does not rewrite platform history.
    assert detail["approval"]["state"] == "timed_out"
    listed = next(x for x in client.get(ROOT+"/hook-approvals").json()["items"] if x["id"] == row["id"])
    assert listed == detail["approval"]
    assert int(listed["expires_at"]) > time.time()
    assert decision(client,row,"allow").status_code==409
    altered={**body,"code":"aidr_hook_approval_cancelled"}
    assert client.post(ROOT+"/hook-attempt-reports",json=altered,headers=HEADERS).status_code==409
    assert client.post(ROOT+"/hook-attempt-reports",json={**body,"receiver_instance":"f"*32},headers=HEADERS).status_code==422
    assert client.post(ROOT+"/hook-attempt-reports",json={**body,"state":"consumed","code":"aidr_hook_approval_consumed"},headers=HEADERS).status_code==422
    assert client.post(ROOT.replace('/one/','/two/')+"/hook-attempt-reports",content=raw,headers=HEADERS).status_code==403
    assert client.post(ROOT+"/hook-attempt-reports",json={**body,"output":"SYNTHETIC-UNWANTED-BODY"},headers=HEADERS).status_code==422
    with factory() as db:
        assert db.query(control_logic.HookAttemptReportRow).count()==1


def policy(expected="0"):
    return {"expected_revision": expected, "lifetime_seconds": 3600, "default_action": "deny", "rules": [{"id": "review", "agent": "codex", "tool": "Bash", "decision": "ask"}]}


def test_codebuddy_approval_requires_turn_and_preserves_empty_native_call(control):
    client, _, _ = control
    target = policy()
    target['rules'][0]['agent'] = '*'
    assert client.put(ROOT + '/hook-policy', json=target).status_code == 200
    approved_scopes = []
    for seq, (agent, turn, status) in enumerate([
        ('codebuddy', 'same-turn', 200), ('codebuddy', 'same-turn', 200),
        ('codebuddy', '', 422), ('workbuddy', 'same-turn', 422),
    ], 1):
        batch = hook_batch(seq)
        row = batch['records'][0]
        row['receiver_instance'] = INSTANCE
        row['event'].update(agent=agent, hook_event='PreToolUse', kind='tool.pre', tool='Bash',
                            turn_id=turn, input_digest='c' * 64)
        row['event']['behavior'] = dict(version=3, policy=row['event']['policy'], category='command',
            method='direct_fields', actions=[], status='unknown', result_basis=[],
            redacted=False, truncated=False, uncertainty=[])
        submitted = send(client, batch)
        assert submitted.status_code == 200, submitted.text
        request = dict(expires_at=int(time.time())+180, stream_id=batch['stream_id'], event_id=row['event_id'],
                       receiver_instance=INSTANCE, policy_revision='1', rule_id='review')
        response = client.post(ROOT + '/hook-approvals', json=request, headers=HEADERS)
        assert response.status_code == status, response.text
        if status == 200:
            scope = response.json()['scope']
            assert scope['native_call_id'] == '' and scope['attempt_nonce'] == row['event_id']
            approved_scopes.append(scope)
        else:
            assert response.json()['error_code'] == 'aidr.hook_scope_unverified'
    assert approved_scopes[0]['attempt_nonce'] != approved_scopes[1]['attempt_nonce']


def test_twenty_concurrent_terminal_receipts_keep_exact_identity(control):
    client, factory, _ = control
    assert client.put(ROOT + "/hook-policy", json=policy()).status_code == 200
    bodies = []
    for seq in range(1, 21):
        row, request = pending(client, seq)
        bodies.append({"schema_version": 1, "client_id": "one", "stream_id": request["stream_id"],
            "event_id": request["event_id"], "receiver_instance": INSTANCE,
            "approval_id": row["id"], "state": "denied", "code": "aidr_hook_approval_timeout",
            "reported_at": str(int(time.time()))})
    barrier = Barrier(20)

    def report(body):
        raw = json.dumps(body, separators=(",", ":")).encode()
        barrier.wait(timeout=15)
        for _ in range(2):
            result = client.post(ROOT + "/hook-attempt-reports", content=raw, headers=HEADERS)
            assert result.status_code == 200, result.text
            assert result.json()["durable"]
            assert result.json()["digest"] == hashlib.sha256(raw).hexdigest()
        detail = client.get(ROOT + f"/hook-approvals/{body['approval_id']}").json()
        assert detail["client_report"]["record"] == body
        assert detail["approval"]["recorded_state"] == "pending"
        assert detail["approval"]["state"] == "timed_out"

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(report, bodies))
    with factory() as db:
        assert db.query(control_logic.HookAttemptReportRow).count() == 20


def pending(client, seq=1, user_scope='501'):
    batch = hook_batch(seq)
    row = batch["records"][0]
    row["receiver_instance"] = INSTANCE
    row['user_scope'] = user_scope
    event = row["event"]
    event.update(hook_event="PreToolUse", kind="tool.pre", tool="Bash", turn_id="turn", native_call_id=f"call-{seq}", input_digest="c"*64)
    event["behavior"] = {"version": 3, "policy": event["policy"], "body_omitted": False, "category": "command", "method": "direct_fields", "actions": [{"tool": "Bash", "category": "command", "command": "/bin/sleep 1", "cwd": "/private/tmp", "targets": [], "source_fields": ["command", "cwd"]}], "status": "unknown", "result_basis": [], "redacted": False, "truncated": False, "uncertainty": []}
    result = send(client, batch)
    assert result.status_code == 200, result.text
    request = {"expires_at": int(time.time())+180, "stream_id": "b"*32, "event_id": row["event_id"], "receiver_instance": INSTANCE, "policy_revision": "1", "rule_id": "review"}
    result = client.post(ROOT+"/hook-approvals", json=request, headers=HEADERS)
    assert result.status_code == 200, result.text
    return result.json(), request


def decision(client, row, action, key="a", expected=None):
    return client.post(ROOT+f"/hook-approvals/{row['id']}/decision", json={"request_id": key*32, "expected_revision": expected or row["revision"], "decision": action})


@pytest.mark.parametrize('user_scope', ['501', 'S-1-5-21-1234567890-2345678901-3456789012-1001'])
def test_policy_request_decision_signature_idempotence_and_revocation(control, user_scope):
    client, factory, key = control
    assert client.put(ROOT+"/hook-policy", json=policy()).json()["revision"] == "1"
    assert client.put(ROOT+"/hook-policy", json=policy()).status_code == 409
    row, request = pending(client, user_scope=user_scope)
    assert row['scope']['user_scope'] == user_scope
    detail = client.get(ROOT+f"/hook-approvals/{row['id']}")
    assert detail.status_code == 200
    assert detail.json()["approval"] == row
    evidence = detail.json()["evidence"]
    assert evidence["event_id"] == request["event_id"]
    assert 'command' not in evidence["event"]["behavior"]["actions"][0]
    assert evidence["event"]["behavior"]["contents"][0]["source_field"] == 'behavior.actions.command'
    assert client.get(ROOT.replace('/one/', '/two/')+f"/hook-approvals/{row['id']}").status_code == 404
    assert row["state"] == "pending" and row["scope"]["execution_point"] == "plugin_pre_tool"
    assert client.post(ROOT+"/hook-approvals", json=request, headers=HEADERS).json() == row
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: decision(client,row,"allow"), range(8)))
    assert all(r.status_code == 200 for r in results)
    assert all(r.json() == results[0].json() for r in results)
    approved = results[0].json()
    snapshot_body = {"stream_id": "b"*32, "receiver_instance": INSTANCE}
    snapshot = client.post(ROOT+"/hook-control/snapshot", json=snapshot_body, headers=HEADERS).json()
    assert len(snapshot["grants"]) == 1 and not snapshot["more_grants"]
    for envelope in [snapshot["policy"], *snapshot["grants"]]:
        key.public_key().verify(base64.b64decode(envelope["signature"]), base64.b64decode(envelope["payload"]), ec.ECDSA(hashes.SHA256()))
    grant = json.loads(base64.b64decode(snapshot["grants"][0]["payload"]))
    assert grant["scope"] == row["scope"] and grant["domain"] == "aidr.tool-grant/1"
    assert grant["decision"] == "allow" and grant["revision"] == "2"
    assert decision(client,row,"deny").status_code == 409  # same idempotency key, different content
    assert decision(client,row,"allow",key="b").status_code == 409  # stale revision
    revoked = decision(client,approved,"revoke",key="c")
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert decision(client,revoked.json(),"allow",key="d").status_code == 409
    with factory() as db:
        assert db.query(control_logic.HookApprovalRow).count() == 1
        assert db.query(control_logic.HookApprovalReceipt).count() == 2
        assert db.query(models.OperationLog).filter(models.OperationLog.action=="aidr.hook.approval").count() == 2


def test_scope_permissions_expiry_and_policy_change(control):
    client, factory, _ = control
    assert client.put(ROOT+"/hook-policy", json=policy()).status_code == 200
    row, request = pending(client)
    bad = {**request, "receiver_instance": "f"*32}
    assert client.post(ROOT+"/hook-approvals", json=bad, headers=HEADERS).status_code == 422
    assert client.post(ROOT.replace("/one/","/two/")+"/hook-approvals", json=request, headers=HEADERS).status_code == 403
    assert client.get(ROOT.replace("/one/","/two/")+"/hook-approvals").status_code == 404
    actor = models.User(id=1,username="owner",role="user")
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: actor
    assert decision(client,row,"allow").status_code == 403
    assert client.put(ROOT+"/hook-policy", json=policy("1")).status_code == 403
    actor.role="admin"
    assert client.put(ROOT+"/hook-policy", json={**policy("1"), 'default_action': 'allow'}).status_code == 200
    assert decision(client,row,"allow").status_code == 409
    with factory() as db:
        db.get(control_logic.HookApprovalRow,row["id"]).expires_at=int(time.time())-1
        db.commit()
    result = client.get(ROOT+"/hook-approvals").json()["items"][0]
    assert result["state"] == "expired" and result["recorded_state"] == "pending"
    assert decision(client,row,"deny").status_code == 409


def test_conflict_explanation_and_same_second_pagination(control):
    client, factory, _ = control
    p=policy(); p["rules"] += [{"id":"allow","agent":"*","tool":"*","decision":"allow"}]
    assert control_logic.evaluate({"rules":p["rules"],"default_action":"deny"},"codex","Bash")=={"decision":"ask","rule_id":"review","matched_rule_ids":["allow","review"]}
    p["rules"] += [{"id":"deny","agent":"codex","tool":"Bash","decision":"deny"}]
    assert control_logic.evaluate({"rules":list(reversed(p["rules"])),"default_action":"allow"},"codex","Bash")["decision"]=="deny"
    assert client.put(ROOT+"/hook-policy",json=policy()).status_code==200
    ids=[]
    for i in range(1,6):
        row,_=pending(client,i);ids.append(row["id"])
    with factory() as db:
        db.query(control_logic.HookApprovalRow).update({"created_at":1800000000})
        db.commit()
    params={"limit":2};seen=[]
    for _ in range(4):
        page=client.get(ROOT+"/hook-approvals",params=params).json()
        seen.extend(item["id"] for item in page["items"])
        if not page["has_more"]: break
        params.update(before=page["next_before"],before_id=page["next_before_id"])
    assert sorted(seen)==sorted(ids) and len(seen)==5


def test_approval_iam_mapping():
    from backend.iam_routes import route_permission
    path="/api/v1/clients/{client_id}/aidr/hook-approvals/{approval_id}/decision"
    request=SimpleNamespace(scope={"route":SimpleNamespace(path=path)},url=SimpleNamespace(path=path),method="POST")
    assert route_permission(request)=="clients:execute"


def test_control_delivery_is_scoped_and_byte_bounded(control):
    client,factory,_=control
    assert client.put(ROOT+"/hook-policy",json=policy()).status_code==200
    row,_=pending(client)
    approved=decision(client,row,"allow").json()
    with factory() as db:
        source=db.get(control_logic.HookApprovalRow,approved["id"])
        scope=json.loads(source.scope)
        for index in range(2,152):
            identity=f"{index:032x}"
            grant={"schema":1,"domain":"aidr.tool-grant/1","grant_id":identity,"nonce":identity,"revision":"2","decision":"allow","issued_at":str(source.created_at),"expires_at":str(source.expires_at),"scope":{**scope,"attempt_nonce":identity,"native_call_id":"concurrent-"+str(index)}}
            db.add(control_logic.HookApprovalRow(id=identity,client_id="one",stream_id="b"*32,event_id=identity,receiver_instance=INSTANCE,scope=canonical(grant["scope"]),nonce=identity,revision=2,state="approved",created_at=source.created_at,expires_at=source.expires_at,envelope=canonical(sign(grant))))
        db.commit()
    body={"stream_id":"b"*32,"receiver_instance":INSTANCE}
    seen=[]
    for _ in range(10):
        response=client.post(ROOT+"/hook-control/snapshot",json=body,headers=HEADERS)
        assert response.status_code==200 and len(response.content)<65536
        page=response.json()
        seen.extend(json.loads(base64.b64decode(g["payload"]))["grant_id"] for g in page["grants"])
        if not page["more_grants"]:break
        assert page["next_after"]>body.get("after","")
        body["after"]=page["next_after"]
    assert len(seen)==151 and len(set(seen))==151
    empty=client.post(ROOT+"/hook-control/snapshot",json={**body,"after":"","receiver_instance":"f"*32},headers=HEADERS)
    assert empty.json()["grants"]==[]
    assert client.post(ROOT.replace("/one/","/two/")+"/hook-control/snapshot",json=body,headers=HEADERS).status_code==403
    with factory() as db:
        db.query(models.AccessToken).filter_by(name="one").one().scopes_json='["aidr:report-events"]'
        db.commit()
    assert client.post(ROOT+"/hook-control/snapshot",json=body,headers=HEADERS).status_code==403


def test_persistent_rules_and_legacy_policy_keep_approval_attempts_bounded(control):
    client, factory, _ = control
    body = policy()
    body.pop("lifetime_seconds")
    result = client.put(ROOT + "/hook-policy", json=body)
    assert result.status_code == 200, result.text
    published = result.json()["policy"]
    assert published["schema"] == 4 and published["domain"] == "aidr.tool-policy/4"
    assert "expires_at" not in published
    assert result.json()["analysis"]["validity"] == "until_replaced"
    # Existing signed configuration survives its former lease without rewriting history.
    with factory() as db:
        old = db.query(control_logic.HookPolicyRow).one()
        payload = json.loads(old.payload)
        payload.update(schema=1, domain="aidr.tool-policy/1", issued_at=str(int(time.time())-7200), expires_at=str(int(time.time())-3600))
        old.payload, old.envelope = canonical(payload), canonical(sign(payload))
        db.commit()
    row, _ = pending(client)
    assert 0 < int(row["expires_at"]) - int(time.time()) <= 300
    assert decision(client, row, "allow").status_code == 200
