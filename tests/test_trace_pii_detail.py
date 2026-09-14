import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import models
from backend.routers.llm_gateway import get_trace_detail
from backend.sqlite_db import Base


def test_detail_pii_mappings_are_scoped_to_trace_and_active(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trace.db'}")
    Base.metadata.create_all(engine)
    token = '<EMAIL_ADDRESS:em_0123456789>'
    with Session(engine) as db:
        db.add(models.LlmPipelineTrace(
            request_id='trace-test', stage='masked', tenant_id='tenant-a', conversation_id='conv-a',
            model='test', payload_json=json.dumps({'messages': [{'role': 'user', 'content': token}]}),
            expires_at=datetime.utcnow() + timedelta(days=1),
        ))
        for tenant, conversation, value, mapping_token, days in [
            ('tenant-a', 'conv-a', 'match@example.com', token, 1),
            ('tenant-b', 'conv-a', 'other-tenant@example.com', token, 1),
            ('tenant-a', 'conv-b', 'other-conversation@example.com', token, 1),
            ('tenant-a', 'conv-a', 'expired@example.com', token, -1),
            ('tenant-a', 'conv-a', 'unused@example.com', '<EMAIL_ADDRESS:em_9876543210>', 1),
        ]:
            db.add(models.PseudonymMapping(
                tenant_id=tenant, conversation_id=conversation, original_value=value,
                normalized_value=value, token=mapping_token, entity_type='EMAIL_ADDRESS',
                request_id='prior-request', created_by='test', expires_at=datetime.utcnow() + timedelta(days=days),
            ))
        db.commit()
        result = asyncio.run(get_trace_detail('trace-test', db=db, current_user=None))
        assert result['pii_mappings'] == [{
            'token': token, 'original_value': 'match@example.com', 'entity_type': 'EMAIL_ADDRESS',
        }]
        db.query(models.PseudonymMapping).delete()
        db.commit()
        result = asyncio.run(get_trace_detail('trace-test', db=db, current_user=None))
        assert result['pii_mappings'] == []
        assert result['stages']['masked']['messages'][0]['content'] == token
