"""Bound held-writer reads while preserving audit/alert transaction semantics."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from backend import aidr_skill_usage as usage, models
from backend.aidr_models import AidrSkillUse, AidrSkillCheck
from tests.test_aidr_api import service
from tests.test_aidr_skill_transactions import seed


def verified(*_):
    return dict(status='verified_content', reason='agent_identity_unknown',
                checked_at=datetime.utcnow().isoformat()+'Z')


def test_fifty_checks_do_not_reload_each_usage_or_query_each_alert_under_writer(service, monkeypatch):
    _, factory = service
    seed(factory, 50)
    monkeypatch.setattr(usage, 'certification', verified)
    reads = []
    def observe(conn, _cursor, statement, _parameters, _context, _many):
        if conn.connection.driver_connection.in_transaction and statement.lstrip().startswith('SELECT'):
            reads.append(statement)
    engine = factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with factory() as db:
            rows = db.query(AidrSkillUse).order_by(AidrSkillUse.id).all()
            results = usage.refresh_batch(db, rows, SimpleNamespace())
            assert all(json.loads(row.payload_json)['certification'] == result['certification']
                       for row, result in zip(rows, results))
            db.commit()
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert len(reads) == 1 and 'client_events' in reads[0]
    with factory() as db:
        assert db.query(AidrSkillCheck).count() == 50
        assert {r.certification for r in db.query(AidrSkillUse)} == {'verified_content'}


def test_batch_resolves_alert_committed_after_preparation(service, monkeypatch):
    _, factory = service
    seed(factory, 2)
    monkeypatch.setattr(usage, 'certification', verified)
    original = usage._apply_refresh
    inserted = []
    def interleave(db, plan, **kwargs):
        if not inserted:
            with factory() as writer:
                for row in writer.query(AidrSkillUse).all():
                    writer.add(models.ClientEvent(client_id=row.client_id,
                        event_type='aidr_skill_alert', aggregate_key=usage._alert_key(row),
                        details_json=json.dumps({'active':True, 'reason_code':'revoked'})))
                writer.commit()
            inserted.append(True)
        return original(db, plan, **kwargs)
    monkeypatch.setattr(usage, '_apply_refresh', interleave)
    with factory() as db:
        usage.refresh_batch(db, db.query(AidrSkillUse).all(), SimpleNamespace())
        db.commit()
    with factory() as db:
        alerts = db.query(models.ClientEvent).all()
        assert len(alerts) == 2
        assert all(json.loads(a.details_json)['active'] is False for a in alerts)
        assert all(json.loads(a.details_json)['latest_check']['status'] == 'verified_content' for a in alerts)
        assert db.query(AidrSkillCheck).count() == 2


def test_failure_rolls_back_synchronized_rows_and_alert_resolution(service, monkeypatch):
    _, factory = service
    seed(factory, 2)
    monkeypatch.setattr(usage, 'certification', verified)
    with factory() as db:
        for row in db.query(AidrSkillUse):
            db.add(models.ClientEvent(client_id=row.client_id, event_type='aidr_skill_alert',
                aggregate_key=usage._alert_key(row), details_json='{"active":true}'))
        db.commit()
    original = usage._apply_refresh
    calls = []
    def fail(db, plan, **kwargs):
        if calls:
            raise OSError('second check failed')
        calls.append(True)
        return original(db, plan, **kwargs)
    monkeypatch.setattr(usage, '_apply_refresh', fail)
    with factory() as db:
        rows = db.query(AidrSkillUse).all()
        with pytest.raises(OSError, match='second check failed'):
            usage.refresh_batch(db, rows, SimpleNamespace())
        db.rollback()
        assert all(r.certification == 'pending' and 'certification' not in json.loads(r.payload_json) for r in rows)
        assert db.query(AidrSkillCheck).count() == 0
        assert all(json.loads(a.details_json)['active'] for a in db.query(models.ClientEvent))
