from concurrent.futures import ThreadPoolExecutor

import pytest

from backend import auth, models, iam_models
from backend.aidr_risk import RiskDisposition, RiskEvidence, RiskFinding
from tests.test_aidr_risk import service, configure, call, drain, hook_insert, BASE
from tests.test_aidr_api import service as aidr_service


def finding(client, factory):
    configure(client)
    hook_insert(factory, 1, event=call())
    drain(factory)
    return client.get(BASE).json()['items'][0]


def test_disposition_cycle_evidence_late_results_and_new_risks(service):
    client, factory = service
    row = finding(client, factory)
    ident = row['id']
    with factory() as db:
        evidence_before = [(r.record_id, r.digest) for r in db.query(RiskEvidence).all()]
    for revision, state in enumerate(('accepted', 'false_positive', 'resolved', 'open'), 1):
        result = client.put(BASE + '/' + ident + '/disposition', json={
            'expected_revision': revision - 1, 'status': state, 'reason': '人工说明\n' + '😀' * 995})
        assert result.status_code == 200, result.text
        assert result.json()['disposition'] == state
        assert result.json()['disposition_revision'] == revision
        assert result.json()['updated_at'] == row['updated_at']
        assert client.get(BASE, params={'disposition': state}).json()['total'] == 1
        assert client.get(BASE + '/summary').json()['dispositions'][state] == 1
    history = client.get(BASE + '/' + ident + '/dispositions', params={'page_size': 2}).json()
    assert history['total'] == 4 and [x['revision'] for x in history['items']] == [4, 3]
    assert all(x['actor'] == 'owner' for x in history['items'])
    assert client.get(BASE + '/' + ident + '/dispositions', params={'page': 2, 'page_size': 2}).json()['items'][1]['revision'] == 1
    with factory() as db:
        assert [(r.record_id, r.digest) for r in db.query(RiskEvidence).all()] == evidence_before
        assert db.query(models.OperationLog).filter_by(action='aidr.risk.dispose').count() == 4
    assert client.put(BASE + '/' + ident + '/disposition', json={
        'expected_revision': 4, 'status': 'resolved', 'reason': 'done'}).status_code == 200
    hook_insert(factory, 2, event={**call(), 'kind': 'tool.post', 'behavior': {'status': 'reported_success'}})
    hook_insert(factory, 3, event={**call(), 'native_call_id': 'new-call'})
    drain(factory)
    assert client.get(BASE + '/' + ident).json()['disposition'] == 'resolved'
    assert client.get(BASE + '/' + ident).json()['result_status'] == 'reported_success'
    assert client.get(BASE, params={'disposition': 'open'}).json()['total'] == 1


@pytest.mark.parametrize('change', [{'reason': ''}, {'reason': ' \n '}, {'reason': '😀' * 1001},
    {'status': 'closed'}, {'expected_revision': True}, {'expected_revision': -1}, {'extra': 'input'}])
def test_disposition_rejects_invalid_input_without_writing(service, change):
    client, factory = service
    ident = finding(client, factory)['id']
    result = client.put(BASE + '/' + ident + '/disposition', json={
        'expected_revision': 0, 'status': 'resolved', 'reason': 'ok', **change})
    assert result.status_code == 422
    assert result.json()['error_code'] == 'aidr.risk.invalid_disposition'
    with factory() as db:
        assert db.query(RiskDisposition).count() == 0
        assert db.get(RiskFinding, ident).disposition == 'open'


def test_disposition_concurrent_retry_and_permissions(service):
    client, factory = service
    ident = finding(client, factory)['id']
    url = BASE + '/' + ident + '/disposition'
    body = {'expected_revision': 0, 'status': 'resolved', 'reason': 'done'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.put(url, json=body), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.put(url, json=body).status_code == 409
    assert client.put(url, json={**body, 'expected_revision': 1}).status_code == 409
    assert client.get(BASE.replace('/one/', '/two/') + '/' + ident + '/dispositions').status_code == 404
    assert client.put(url.replace('/one/', '/two/'), json=body).status_code == 404
    with factory() as db:
        assert db.query(RiskDisposition).count() == 1
        db.query(iam_models.RolePermission).filter_by(role_name='admin', permission_code='clients:update').delete()
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.headers['authorization'] = 'Bearer ' + auth.create_access_token({'sub': 'owner'})
    assert client.get(BASE + '/' + ident + '/dispositions').status_code == 200
    assert client.put(url, json={**body, 'expected_revision': 1, 'status': 'open'}).status_code == 403


def test_disposition_audit_failure_rolls_back(service, monkeypatch):
    from backend.routers import aidr
    client, factory = service
    ident = finding(client, factory)['id']
    def fail(*args):
        raise RuntimeError('audit_unavailable')
    monkeypatch.setattr(aidr, '_operation', fail)
    with pytest.raises(RuntimeError, match='audit_unavailable'):
        client.put(BASE + '/' + ident + '/disposition', json={'expected_revision': 0, 'status': 'resolved', 'reason': 'done'})
    with factory() as db:
        assert db.get(RiskFinding, ident).disposition == 'open'
        assert db.query(RiskDisposition).count() == 0
