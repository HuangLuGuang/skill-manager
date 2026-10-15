import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agent_manager.core.licensing import LicenseError, LicenseStore, canonical, require_license, verify
from backend.license_policy import enforce_license_request, license_error_handler


def assert_error(code, call):
    with pytest.raises(LicenseError) as caught:
        call()
    assert caught.value.code == 'license.' + code


def test_issuer_wire_format_and_signature(licensed_deployment):
    issuer = licensed_deployment
    payload = issuer.payload(2)
    raw = issuer.sign(payload)
    assert verify(raw)[0] == payload
    envelope = json.loads(raw)
    envelope['signature'] = envelope['signature'][::-1]
    assert_error('invalid', lambda: issuer.store.import_license(canonical(envelope), 'admin'))
    assert issuer.store.status()['current']['revision'] == 1


@pytest.mark.parametrize('changes', [
    {'product':'other'}, {'schema_version':True}, {'revision':True}, {'revision':0},
    {'limits':{'clients':True}}, {'limits':{'clients':0}}, {'limits':{'clients':1.1}},
    {'features':['unknown']}, {'features':['aidr','aidr']}, {'expires_at':'2028-01-01'},
    {'expiry_policy':'stop_all'}, {'license_id':'bad'}, {'extra':1},
])
def test_strict_signed_payload(licensed_deployment, changes):
    issuer = licensed_deployment
    assert_error('invalid', lambda: verify(issuer.sign({**issuer.payload(2), **changes})))


def test_binding_unknown_key_and_size(licensed_deployment, tmp_path):
    issuer = licensed_deployment
    assert_error('deployment_mismatch',lambda: issuer.store.import_license(issuer.sign(issuer.payload(2,deployment_id='DEP-other')),'admin'))
    assert_error('customer_mismatch',lambda: issuer.store.import_license(issuer.sign(issuer.payload(2,customer_id='other')),'admin'))
    assert_error('untrusted_key',lambda: verify(issuer.sign(issuer.payload()),tmp_path/'unknown'))
    assert_error('invalid',lambda: verify(b' '*65537))
    assert_error('invalid',lambda: verify(b'{"format":1,"format":2}'))


def test_atomic_revision_idempotency_and_invalid_preservation(licensed_deployment):
    issuer = licensed_deployment
    _, second = issuer.install(2)
    assert issuer.store.import_license(second, 'admin')['highest_revision'] == 2
    assert_error('rollback',lambda: issuer.store.import_license(issuer.sign(issuer.payload(1)), 'admin'))
    assert_error('revision_conflict',lambda: issuer.store.import_license(issuer.sign(issuer.payload(2)), 'admin'))
    assert_error('invalid',lambda: issuer.store.import_license(b'{}','admin'))
    state = LicenseStore().status()
    assert state['current']['revision'] == 2
    assert len(state['history']) == 2


def test_future_renewal_keeps_current_and_activates_on_time(licensed_deployment):
    issuer = licensed_deployment
    future = datetime.now(timezone.utc) + timedelta(days=10)
    issuer.install(2,not_before=future.isoformat(),limits={'clients':3})
    assert issuer.store.status()['current']['revision'] == 1
    assert issuer.store.status()['pending'][0]['revision'] == 2
    state = LicenseStore(now=lambda:future.timestamp()).status()
    assert state['current']['revision'] == 2
    assert state['current']['limits']['clients'] == 3


def test_expiry_runtime_modules_and_clock_rollback(licensed_deployment):
    issuer = licensed_deployment
    end = datetime.now(timezone.utc) + timedelta(seconds=60)
    issuer.install(2,expires_at=end.isoformat(),features=['aidr','mcp_gateway','model_gateway'])
    assert_error('feature_denied',lambda: require_license('security_scanning'))
    state = LicenseStore(now=lambda:end.timestamp()).status()
    assert state['state'] == 'expired'
    assert_error('expired',lambda: require_license('aidr'))
    assert require_license('aidr',runtime=True)['revision'] == 2
    assert require_license('mcp_gateway',runtime=True)
    assert require_license('model_gateway',runtime=True)
    LicenseStore(now=lambda:end.timestamp()+3600).status()
    assert LicenseStore().status()['state'] == 'clock_rollback'
    assert_error('clock_rollback',lambda: require_license())
    assert require_license('aidr',runtime=True)


def test_concurrent_imports_and_persistent_identity(licensed_deployment):
    issuer = licensed_deployment
    before=issuer.store.status()['deployment_id']
    raw=issuer.sign(issuer.payload(2))
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda _:LicenseStore().import_license(raw,'admin'),range(4)))
    assert all(r['highest_revision']==2 for r in results)
    assert len(LicenseStore().status()['history'])==2
    assert LicenseStore().status()['deployment_id']==before
    assert_error('identity_locked',lambda:issuer.store.request('different','Different'))


@pytest.mark.parametrize('method,path,allowed', [
    ('GET','/api/v1/skills',True), ('GET','/api/v1/skills/id/download',True),
    ('POST','/api/v1/runtime-traces/id/exports',True), ('POST','/api/v1/license/import',True),
    ('POST','/api/v1/skills/submit-zip',False), ('POST','/api/v1/skills/id/rescan',False),
    ('POST','/api/v1/scanner/imports',False), ('POST','/api/v1/agent-security/tasks',False),
    ('POST','/api/v1/mcp/gateways',False), ('POST','/api/v1/model-providers',False),
    ('POST','/api/agents',False), ('POST','/api/v1/access/tokens',False),
    ('POST','/api/v1/iam/users',False), ('POST','/api/tasks',False),
    ('POST','/v1/chat/completions',True), ('POST','/mcp/existing',True),
    ('POST','/api/v1/clients/host/aidr/hooks:batch',True),
    ('PUT','/api/v1/clients/host/aidr/hook-policy',True),
    ('POST','/api/v1/mcp/approval-requests/id/approve',True),
    ('POST','/api/v1/runtime/verify-skill-signature',True),
    ('POST','/api/v1/access/runtime/verify-skill-signature',True),
])
def test_expired_http_execution_matrix(licensed_deployment, method, path, allowed):
    issuer = licensed_deployment
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    issuer.install(2,expires_at=end.isoformat())
    LicenseStore(now=lambda:end.timestamp()).status()
    app=FastAPI(dependencies=[Depends(enforce_license_request)])
    app.add_exception_handler(LicenseError,license_error_handler)
    app.add_api_route(path,lambda:{'ok':True},methods=[method])
    response=TestClient(app).request(method,path,headers={'Accept-Language':'en-US'})
    assert response.status_code==(200 if allowed else 403),response.text
    if not allowed: assert response.json()['error_code']=='license.expired'


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/v1/access/runtime/can-load/example'),
    ('POST', '/api/v1/access/runtime/verify-skill-signature'),
    ('POST', '/v1/chat/completions'),
    ('POST', '/mcp/existing'),
    ('POST', '/api/v1/clients/host/aidr/hooks:batch'),
])
def test_runtime_requires_signed_module(licensed_deployment, method, path):
    licensed_deployment.install(2, features=['security_scanning'])
    app = FastAPI(dependencies=[Depends(enforce_license_request)])
    app.add_exception_handler(LicenseError, license_error_handler)
    app.add_api_route(path, lambda: {'ok': True}, methods=[method])
    response = TestClient(app).request(method, path)
    assert response.status_code == 403
    assert response.json()['error_code'] == 'license.feature_denied'


def test_new_client_quota_is_atomic_and_reconnect_survives_expiry(licensed_deployment,tmp_path):
    from tests.test_clients_api import _client
    issuer=licensed_deployment
    issuer.install(2,limits={'clients':1})
    client=_client(tmp_path)
    client.app.add_exception_handler(LicenseError,license_error_handler)
    tokens=[client.post('/api/v1/access/tokens',json={'name':f'token-{i}','token_type':'client'}).json()['token'] for i in range(2)]
    def register(i):
        return client.post('/api/v1/clients/register',headers={'Authorization':f'Bearer {tokens[i]}'},json={'client_id':f'host-{i}','name':'Host','hostname':f'host-{i}','os':'linux','arch':'amd64','client_version':'1.0','agents':[]})
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(register,range(2)))
    assert sorted(r.status_code for r in responses)==[200,403]
    winner=next(i for i,r in enumerate(responses) if r.status_code==200)
    loser=1-winner
    assert responses[loser].json()['error_code']=='license.client_limit'
    assert register(winner).status_code==200
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    issuer.install(3,expires_at=end.isoformat(),limits={'clients':1})
    LicenseStore(now=lambda:end.timestamp()).status()
    assert register(winner).status_code==200
    assert register(loser).json()['error_code']=='license.expired'


def test_core_and_worker_execution_stop_before_work(licensed_deployment):
    import asyncio
    from backend.routers.security_scans import claim_task, create_task
    from backend.security_scan_schemas import SecurityWorkerClaimRequest
    from agent_manager.core.manager import AgentManager
    from backend.routers.clients import require_client_task
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    licensed_deployment.install(2,expires_at=end.isoformat())
    LicenseStore(now=lambda:end.timestamp()).status()
    assert_error('expired',lambda: AgentManager.prepare_submission(None,'/not-used'))
    assert_error('expired',lambda: asyncio.run(create_task(None,None,None)))
    assert asyncio.run(claim_task(SecurityWorkerClaimRequest(),None,None)).task is None
    assert_error('expired',lambda:require_client_task('rescan'))
    require_client_task('aidr_plugin_action')


def test_all_model_execution_aliases_share_runtime_entitlement():
    from backend.routers.llm_gateway import runtime_router
    from backend.license_policy import requirement
    for route in runtime_router.routes:
        if 'POST' in route.methods:
            assert requirement('POST',route.path)==('model_gateway',True),route.path


def _with_license_boundary(client):
    app=FastAPI(dependencies=[Depends(enforce_license_request)])
    app.include_router(client.app.router)
    app.dependency_overrides.update(client.app.dependency_overrides)
    app.exception_handlers.update(client.app.exception_handlers)
    app.add_exception_handler(LicenseError,license_error_handler)
    return TestClient(app)


def test_expired_model_gateway_still_executes_privacy_pipeline(licensed_deployment,tmp_path,monkeypatch):
    from tests.test_llm_gateway import _client
    original,token,factory=_client(tmp_path,monkeypatch)
    client=_with_license_boundary(original)
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    licensed_deployment.install(2,expires_at=end.isoformat())
    LicenseStore(now=lambda:end.timestamp()).status()
    result=client.post('/v1/chat/completions',headers={'Authorization':f'Bearer {token}'},json={'model':'mock-model','messages':[{'role':'user','content':'jane@example.com'}]})
    assert result.status_code==200,result.text
    assert 'jane@example.com' in result.json()['choices'][0]['message']['content']
    from backend import models
    with factory() as db:
        assert db.query(models.PseudonymMapping).count()>0
        assert db.query(models.LlmRequestAudit).count()==1


def test_expired_mcp_gateway_still_calls_existing_tool(licensed_deployment,tmp_path,monkeypatch):
    from tests.test_mcp_gateway import _client,_configured_gateway,_gateway_token
    original,_=_client(tmp_path,monkeypatch)
    client=_with_license_boundary(original)
    _configured_gateway(client)
    token=_gateway_token(client)
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    licensed_deployment.install(2,expires_at=end.isoformat())
    LicenseStore(now=lambda:end.timestamp()).status()
    result=client.post('/mcp/readonly',headers={'Authorization':f'Bearer {token}'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'crm__search','arguments':{'query':'still running'}}})
    assert result.status_code==200,result.text
    assert result.json().get('result'),result.text
    assert client.post('/api/v1/mcp/gateways',json={}).json()['error_code']=='license.expired'


def test_import_api_authentication_stream_limit_and_bilingual_errors(licensed_deployment,tmp_path):
    from backend import auth, models
    from backend.routers import license as routes
    from backend.api_errors import ApiError, api_error_handler
    from backend.sqlite_db import Base, get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine=create_engine(f'sqlite:///{tmp_path / "api.db"}',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    def db():
        with factory() as session: yield session
    app=FastAPI()
    app.add_exception_handler(ApiError,api_error_handler)
    app.add_exception_handler(LicenseError,license_error_handler)
    app.dependency_overrides[get_db]=db
    app.include_router(routes.router,prefix='/api')
    client=TestClient(app)
    assert client.post('/api/v1/license/import',content=b'{}').status_code==401
    app.dependency_overrides[auth.get_current_active_user]=lambda: models.User(username='reader',role='user')
    assert client.post('/api/v1/license/import',content=b'{}').status_code==403
    app.dependency_overrides[auth.get_current_active_user]=lambda: models.User(username='admin',role='super_admin')
    raw=licensed_deployment.sign(licensed_deployment.payload(2))
    result=client.post('/api/v1/license/import',content=raw)
    assert result.status_code==200,result.text
    assert result.json()['current']['revision']==2
    invalid=client.post('/api/v1/license/import',content=b'x'*65537,headers={'Accept-Language':'en-US'})
    assert invalid.status_code==403
    assert invalid.json()['detail']=='Invalid license format or signature'
    assert client.get('/api/v1/license/status').json()['current']['revision']==2
    request=client.post('/api/v1/license/request',json={'customer_id':'test-customer','customer_name':'Test Customer'})
    assert request.status_code==200
    assert request.json()['deployment_id']==licensed_deployment.request['deployment_id']


def test_worker_heartbeat_stops_running_scan_with_control_response(licensed_deployment,tmp_path):
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import models
    from backend.sqlite_db import Base
    from backend.security_scan_controls import hash_value
    from backend.security_scan_schemas import SecurityWorkerHeartbeatRequest
    from backend.routers.security_scans import task_heartbeat
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    licensed_deployment.install(2,expires_at=end.isoformat())
    LicenseStore(now=lambda:end.timestamp()).status()
    engine=create_engine(f'sqlite:///{tmp_path / "worker.db"}')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        task=models.SecurityScanTask(task_id='stop-test',target_id='target',policy_id='policy',scan_kind='mcp_risk_scan',status='running',worker_id='worker',lease_token_hash=hash_value('lease-test-123456'),idempotency_key='stop-test',request_fingerprint='test',created_by='test',timeout_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=1))
        db.add(task)
        db.commit()
        result=asyncio.run(task_heartbeat('stop-test',SecurityWorkerHeartbeatRequest(lease_token='lease-test-123456'),db,models.SecurityScanWorker(worker_id='worker')))
        assert result.continue_allowed is False
        assert result.stop_reason=='license.scan_stopped'
        assert db.get(models.SecurityScanTask,task.id).status=='cancelled'
