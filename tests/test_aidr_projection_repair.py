import json
import pytest
from backend.aidr_operations import repair_codex_session_projections
from backend import models
from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload, operations


def before_upgrade(db):
    db.query(models.AidrAuditState).filter_by(key='codex_session_projection_repair_v1').delete()


def test_repairs_unique_native_call_without_rewriting_evidence(service):
    client, factory = service
    call = event('tool_call', session='', source_instance_id='b'*64)
    result = event('tool_result', source_instance_id='b'*64)
    assert upload(client, call, result).status_code == 200
    with factory() as db:
        before_upgrade(db)
        original = [(e.id, e.payload_json, e.content_hash) for e in db.query(models.AidrEvent).order_by(models.AidrEvent.id)]
        assert repair_codex_session_projections(db.connection()) == 1
        assert repair_codex_session_projections(db.connection()) == 0
        db.commit()
        assert [(e.id, e.payload_json, e.content_hash) for e in db.query(models.AidrEvent).order_by(models.AidrEvent.id)] == original
    rows = operations(client)['items']
    assert len(rows) == 1 and rows[0]['tool'] == 'exec'
    assert rows[0]['session_id'] == 'session-a' and rows[0]['call']['session_id'] == ''
    assert rows[0]['association'] == 'native_call_same_source_instance'
    assert upload(client, call, result).status_code == 200
    assert len(operations(client)['items']) == 1


@pytest.mark.parametrize('change', ['instance', 'turn', 'source', 'user', 'ambiguous', 'expired', 'missing_turn'])
def test_does_not_guess_native_associations(service, change):
    client, factory = service
    call = event('tool_call', session='', source_instance_id='b'*64)
    result = event('tool_result', source_instance_id='b'*64)
    if change == 'instance': result['source_instance_id'] = 'c'*64
    if change == 'turn': result['turn_id'] = 'different'
    if change == 'source': result['source_id'] = 'c'*64
    if change == 'user': result['user_scope'] = '502'
    if change == 'missing_turn':
        call['turn_id'] = ''; result['turn_id'] = ''
    events = [call, result]
    if change == 'ambiguous': events.append(event('tool_result', session='other-session', source_instance_id='b'*64))
    assert upload(client, *events).status_code == 200
    with factory() as db:
        before_upgrade(db)
        if change == 'expired':
            from datetime import datetime
            db.query(models.AidrOperation).filter_by(session_id='').update({'expired_at': datetime.utcnow()})
            db.flush()
        assert repair_codex_session_projections(db.connection()) == 0
        db.commit()


@pytest.mark.parametrize('corrected_first', [False, True])
def test_reparsed_record_replaces_orphan_projection_only(service, corrected_first):
    client, factory = service
    old = event('tool_call', session='', source_instance_id='b'*64)
    corrected = event('tool_call', source_instance_id='b'*64,
                      content_digest=old['content_digest'])
    first, second = (corrected, old) if corrected_first else (old, corrected)
    assert upload(client, first).status_code == 200
    with factory() as db:
        original = db.query(models.AidrEvent).one().payload_json
    assert upload(client, second).status_code == 200
    rows = operations(client)['items']
    assert len(rows) == 1 and rows[0]['session_id'] == 'session-a'
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 2
        assert db.query(models.AidrEvent).order_by(models.AidrEvent.id).first().payload_json == original
    assert upload(client, old, corrected).status_code == 200
    assert len(operations(client)['items']) == 1


@pytest.mark.parametrize('field,value', [
    ('source_instance_id', 'c'*64), ('evidence_digest', 'c'*64),
    ('content_digest', 'c'*64), ('source_id', 'c'*64), ('user_scope', '502'),
    ('native_call_id', 'other-call'), ('record_offset', '42'), ('block', 1),
])
def test_reparsed_record_requires_exact_evidence(service, field, value):
    client, _ = service
    old = event('tool_call', session='', source_instance_id='b'*64)
    corrected = event('tool_call', source_instance_id='b'*64,
                      content_digest=old['content_digest'])
    corrected[field] = value
    if field in {'record_offset', 'block'}:
        corrected['source_seq'] = str(int(corrected['record_offset']) + corrected['block'])
    assert upload(client, old, corrected).status_code == 200
    assert len(operations(client)['items']) == 2


def test_reparsed_record_keeps_ambiguous_session_projection(service):
    client, _ = service
    old = event('tool_call', session='', source_instance_id='b'*64)
    corrected = [event('tool_call', session=session, source_instance_id='b'*64,
                       content_digest=old['content_digest']) for session in ('session-a', 'session-b')]
    assert upload(client, old, *corrected).status_code == 200
    assert len(operations(client)['items']) == 3


@pytest.mark.parametrize('corrected_first', [False, True])
@pytest.mark.parametrize('different_record', [False, True])
def test_skill_projection_reparse_preserves_audit_and_checks(service, corrected_first, different_record):
    from backend.aidr_models import AidrSkillUse, AidrSkillCheck
    from backend.aidr_operations import merge_operations
    from backend.aidr_skill_usage import merge_many, repair_codex_skill_projections
    _, factory = service
    old = event('tool_call', session='', source_instance_id='b'*64)
    corrected = event('tool_call', source_instance_id='b'*64, content_digest=old['content_digest'])
    if different_record:
        corrected['evidence_digest'] = 'f'*64
    skill = {'behavior': 'file_access', 'name': 'sample', 'path': '/skills/sample/SKILL.md', 'basis': 'literal_cat'}
    with factory() as db:
        originals = []
        for e in ((corrected, old) if corrected_first else (old, corrected)):
            e['skill_use'] = skill
            row = models.AidrEvent(client_id='one', logical_id=e['logical_event_id'], content_hash='c'*64,
                                   agent='codex', kind=e['kind'], payload_json=json.dumps(e))
            db.add(row); db.flush()
            originals.append((row.id, row.payload_json))
            merge_operations(db.connection(), 'one', [e])
            merge_many(db, 'log', [row]); db.flush()
            if e is old:
                orphan = db.query(AidrSkillUse).filter_by(session_id='').one()
                check = AidrSkillCheck(client_id='one', usage_id=orphan.id, payload_json='{"original":true}')
                db.add(check); db.flush()
        assert db.query(AidrSkillUse).count() == 2
        assert db.query(AidrSkillUse).filter_by(expired_at=None).count() == (2 if different_record else 1)
        assert repair_codex_skill_projections(db, 'one') == 0
        db.flush()
        assert [(r.id, r.payload_json) for r in db.query(models.AidrEvent).order_by(models.AidrEvent.id)] == originals
        assert db.query(AidrSkillCheck).one().payload_json == '{"original":true}'
