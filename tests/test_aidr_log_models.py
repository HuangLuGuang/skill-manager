"""Log model provenance, native-turn association and additive wire compatibility."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.aidr_contract import Event
from backend.aidr_models import AidrEvent
from backend.aidr_sessions import session_log_models
from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload


def test_log_model_upload_ack_and_session_scope(service):
    client, factory = service
    def record(call, turn='turn-a', session='session-a', model='model-a'):
        return event('tool_call', call=call, turn=turn, session=session,
                     model_context={'source': 'codex.turn_context', 'model': model,
                                    'provider': 'example', 'reasoning_effort': 'high'})
    records = [record('a'), record('b'), record('c', model='model-b'),
               record('d', turn='turn-b', model='model-c'), record('e', session='other')]
    response = upload(client, *records)
    assert response.status_code == 200, response.text
    assert response.json()['durable'] is True
    assert upload(client, *records).status_code == 200
    with factory() as db:
        assert db.query(AidrEvent).count() == 5
        result = session_log_models(db, 'one', 'codex', 'session-a', 4, ['turn:turn-a'])
        assert result['latest']['model'] == 'model-c'
        assert [r['model'] for r in result['turns']['turn:turn-a']] == ['model-a', 'model-b']
        old = session_log_models(db, 'one', 'codex', 'session-a', 2, ['turn:turn-a'])
        assert old['latest']['model'] == 'model-a'
        assert session_log_models(db, 'two', 'codex', 'session-a', 9, [])['latest'] is None
        assert session_log_models(db, 'one', 'claude', 'session-a', 9, [])['latest'] is None
        assert session_log_models(db, 'one', 'codex', '', 9, [])['latest'] is None
        db.query(AidrEvent).filter_by(id=4).update({'expired_at': datetime.utcnow()})
        assert session_log_models(db, 'one', 'codex', 'session-a', 4, [])['latest']['model'] == 'model-b'
    page = client.get('/api/v1/clients/one/aidr/session-turns', params={'agent':'codex','session_id':'session-a'})
    assert page.status_code == 200, page.text
    assert page.json()['items'][0]['log_models'][0]['provider'] == 'example'


def test_log_model_contract_limits_and_product_provenance():
    old = event('tool_call')
    assert Event.model_validate(old).model_context is None
    for context in ({'source':'codex.turn_context','model':'x','api_key':'secret'},
                    {'source':'claude.message.model','model':'x'},
                    {'source':'codex.turn_context','model':'x'*257},
                    {'source':'codex.turn_context'}):
        with pytest.raises(ValidationError):
            Event.model_validate({**old,'model_context':context})


def test_model_metadata_negotiated_separately_from_capture_receipt(service):
    from backend import aidr_policy
    _, factory = service
    with factory() as db:
        old = aidr_policy.issue(db, 'one', 'a'*32, 0, content_supported=True)
        new = aidr_policy.issue(db, 'one', 'a'*32, 0, content_supported=True, model_context_supported=True)
        assert 'model_context_schema' not in old
        assert new['model_context_schema'] == 1
        assert old['receipt'] == new['receipt']
        assert old['capture'] == new['capture']
