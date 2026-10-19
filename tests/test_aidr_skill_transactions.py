"""Fresh Skill certification outside short, evidence-checked write phases."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend import aidr_skill_usage as usage, models, sqlite_db
from backend.aidr_models import AidrSkillUse, AidrSkillCheck
from tests.test_aidr_api import service
from tests.test_aidr_skill_usage import evidence


def seed(factory, count):
    with factory() as db:
        db.execute(text('PRAGMA journal_mode=WAL'))
        for i in range(count):
            evidence(db, call=f'call-{i}', skill={
                'behavior': 'file_access', 'path': f'/skills/sample-{i}/SKILL.md',
                'name': f'sample-{i}', 'basis': 'tool_input.path', 'content_digest': 'a' * 64,
            })
        db.commit()


def probing_manager(factory, calls):
    def candidates(**kwargs):
        # Another writer must be admitted during every registry/file check.
        with factory.kw['bind'].connect() as conn:
            conn.exec_driver_sql('PRAGMA busy_timeout=100')
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            conn.rollback()
        calls.append(kwargs)
        return []
    return SimpleNamespace(list_certification_candidates=candidates)


def test_maintenance_checks_do_not_hold_writer_and_commit_alerts_together(service, monkeypatch):
    _, factory = service
    seed(factory, 3)
    calls = []
    monkeypatch.setattr(sqlite_db, 'SessionLocal', factory)
    monkeypatch.setattr(usage, 'registry_manager', lambda: probing_manager(factory, calls))
    usage.maintenance()
    assert len(calls) == 3
    with factory() as db:
        assert {r.certification for r in db.query(AidrSkillUse)} == {'unregistered'}
        assert db.query(AidrSkillCheck).count() == 3
        assert db.query(models.ClientEvent).count() == 3


def test_list_checks_release_writer_between_groups_and_preserve_cursor(service, monkeypatch):
    client, factory = service
    seed(factory, 35)
    calls = []
    monkeypatch.setattr(usage, 'registry_manager', lambda: probing_manager(factory, calls))
    url = '/api/v1/clients/one/aidr/skill-uses'
    params = dict(agent='workbuddy', session_id='session', limit=30)
    first = client.get(url, params=params)
    assert first.status_code == 200, first.text
    a = first.json()
    assert len(a['items']) == a['checked_count'] == len(calls) == 30
    assert a['has_more']
    second = client.get(url, params={**params, 'after': a['next_cursor']})
    assert second.status_code == 200, second.text
    b = second.json()
    assert len(b['items']) == b['checked_count'] == 5 and not b['has_more']
    assert not {r['id'] for r in a['items']} & {r['id'] for r in b['items']}
    assert len(calls) == 35


@pytest.mark.parametrize('change', ['evidence', 'expire'])
def test_refresh_batch_does_not_overwrite_concurrent_evidence_or_expiry(service, monkeypatch, change):
    _, factory = service
    seed(factory, 1)
    original = usage._apply_refresh
    expected = []
    def interleave(db, plan, **kwargs):
        with factory() as writer:
            row = writer.query(AidrSkillUse).one()
            if change == 'evidence':
                evidence(writer, kind='tool.post', call='call-0', status='reported_complete')
            else:
                row.payload_json = '{}'
                row.expired_at = datetime.utcnow()
                row.certification = 'pending'
                row.session_id = ''
            writer.commit()
            expected.append(row.payload_json)
        return original(db, plan, **kwargs)
    monkeypatch.setattr(usage, '_apply_refresh', interleave)
    with factory() as db:
        usage.refresh_batch(db, db.query(AidrSkillUse).all(), SimpleNamespace(list_certification_candidates=lambda **_: []))
        db.commit()
    with factory() as db:
        row = db.query(AidrSkillUse).one()
        assert row.payload_json == expected[0]
        assert db.query(AidrSkillCheck).count() == db.query(models.ClientEvent).count() == 0
        if change == 'evidence':
            data = json.loads(row.payload_json)
            assert len(data['evidence']) == 2 and data['stage'] == 'host_confirmed'
        else:
            assert row.expired_at is not None


def test_batch_failure_rolls_back_checks_and_alerts(service, monkeypatch):
    _, factory = service
    seed(factory, 2)
    original = usage._apply_refresh
    calls = []
    def fail_second(db, plan, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise OSError('write failed')
        return original(db, plan, **kwargs)
    monkeypatch.setattr(usage, '_apply_refresh', fail_second)
    with pytest.raises(OSError, match='write failed'), factory() as db:
        usage.refresh_batch(db, db.query(AidrSkillUse).all(), SimpleNamespace(list_certification_candidates=lambda **_: []))
        db.commit()
    with factory() as db:
        assert {r.certification for r in db.query(AidrSkillUse)} == {'pending'}
        assert db.query(AidrSkillCheck).count() == db.query(models.ClientEvent).count() == 0


def test_list_failure_keeps_completed_group_and_rolls_back_current_group(service, monkeypatch):
    client, factory = service
    seed(factory, 35)
    monkeypatch.setattr(usage, 'registry_manager', lambda: SimpleNamespace(list_certification_candidates=lambda **_: []))
    original = usage._apply_refresh
    calls = []
    def fail_in_second_group(db, plan, **kwargs):
        calls.append(True)
        if len(calls) == 27:
            raise OSError('second group failed')
        return original(db, plan, **kwargs)
    monkeypatch.setattr(usage, '_apply_refresh', fail_in_second_group)
    with pytest.raises(OSError, match='second group failed'):
        client.get('/api/v1/clients/one/aidr/skill-uses',
                   params=dict(agent='workbuddy', session_id='session', limit=35))
    with factory() as db:
        assert db.query(AidrSkillUse).filter_by(certification='unregistered').count() == 25
        assert db.query(AidrSkillUse).filter_by(certification='pending').count() == 10
        assert db.query(AidrSkillCheck).count() == db.query(models.ClientEvent).count() == 25


def test_list_rechecks_revocation_and_alert_resolution_on_next_request(service, tmp_path, monkeypatch):
    from tests.test_aidr_skill_usage import setup_certification
    from agent_manager.core.signer import compute_signature
    client, factory = service
    monkeypatch.setenv('AGENT_MANAGER_DATA_DIR', str(tmp_path / 'keys'))
    with factory() as db:
        _, entry, _, root = setup_certification(db, tmp_path)
        entry.signature = compute_signature(root)
        db.commit()
    monkeypatch.setattr(usage, 'registry_manager', lambda: SimpleNamespace(
        list_certification_candidates=lambda **_: [entry], checks={}))
    for state, expected, active in [('APPROVED', 'verified_content', False),
                                    ('RETIRED', 'revoked', True), ('APPROVED', 'verified_content', False)]:
        entry.status = state
        response = client.get('/api/v1/clients/one/aidr/skill-uses',
                              params=dict(agent='workbuddy', session_id='session', certification=expected))
        assert response.status_code == 200, response.text
        assert response.json()['items'][0]['certification']['status'] == expected
        with factory() as db:
            alert = db.query(models.ClientEvent).first()
            assert (bool(alert) and json.loads(alert.details_json)['active']) is active


def test_filtered_list_keeps_200_check_budget(service, monkeypatch):
    client, factory = service
    seed(factory, 205)
    monkeypatch.setattr(usage, 'registry_manager', lambda: SimpleNamespace(list_certification_candidates=lambda **_: []))
    params = dict(agent='workbuddy', session_id='session', certification='verified', limit=30)
    response = client.get('/api/v1/clients/one/aidr/skill-uses', params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page['items'] == [] and page['checked_count'] == 200 and page['has_more']
    second = client.get('/api/v1/clients/one/aidr/skill-uses', params={**params, 'after': page['next_cursor']}).json()
    assert second['checked_count'] == 5 and second['items'] == [] and not second['has_more']
