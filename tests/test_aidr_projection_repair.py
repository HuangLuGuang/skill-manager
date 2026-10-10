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
