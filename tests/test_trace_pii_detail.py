import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import models
from backend.routers.llm_gateway import get_trace_detail, list_traces
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


def test_trace_list_reports_request_pii_detection_result(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trace-list.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for request_id, bypass, traffic_type, counts in [
            ('detected', False, 'pii_checked', {'EMAIL_ADDRESS': 1}),
            ('not-detected', False, 'pii_checked', {}),
            ('bypassed', True, 'pii_bypass', {}),
        ]:
            db.add(models.LlmPipelineTrace(
                request_id=request_id, stage='meta', tenant_id='tenant-a', conversation_id='conv-a',
                model='test', bypass_pii=bypass, payload_json='{}',
                expires_at=datetime.utcnow() + timedelta(days=1),
            ))
            db.add(models.LlmRequestAudit(
                request_id=request_id, tenant_id='tenant-a', conversation_id='conv-a',
                user_ref='test', model='test', traffic_type=traffic_type,
                detected_counts_json=json.dumps(counts),
            ))
        db.add(models.LlmPipelineTrace(
            request_id='missing-audit', stage='meta', tenant_id='tenant-a', conversation_id='conv-a',
            model='test', payload_json='{}', expires_at=datetime.utcnow() + timedelta(days=1),
        ))
        db.commit()
        result = asyncio.run(list_traces(db=db, current_user=None))
        by_id = {trace['request_id']: trace['has_pii'] for trace in result['traces']}
        assert by_id == {
            'detected': True,
            'not-detected': False,
            'bypassed': None,
            'missing-audit': None,
        }


def test_trace_list_input_tokens_match_detail_compression_stages(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trace-token-list.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            models.LlmPipelineTrace(
                request_id='compressed-request', stage='meta', tenant_id='tenant-a', conversation_id='conv-a',
                model='test', payload_json='{}', expires_at=datetime.utcnow() + timedelta(days=1),
            ),
            models.LlmPipelineTrace(
                request_id='compressed-request', stage='compressed', tenant_id='tenant-a', conversation_id='conv-a',
                model='test', payload_json=json.dumps({
                    'enabled': True,
                    'pre_tokens': 38470,
                    'post_tokens': 18103,
                    'tokens_saved': 20367,
                }), expires_at=datetime.utcnow() + timedelta(days=1),
            ),
            models.LlmUsageMetric(
                request_id='compressed-request', tenant_id='tenant-a', conversation_id='conv-a', model='test',
                prompt_tokens=18250, completion_tokens=100, total_tokens=18350,
            ),
            models.LlmPipelineTrace(
                request_id='plain-request', stage='meta', tenant_id='tenant-a', conversation_id='conv-b',
                model='test', payload_json='{}', expires_at=datetime.utcnow() + timedelta(days=1),
            ),
            models.LlmUsageMetric(
                request_id='plain-request', tenant_id='tenant-a', conversation_id='conv-b', model='test',
                prompt_tokens=700, completion_tokens=50, total_tokens=750,
            ),
        ])
        db.commit()

        result = asyncio.run(list_traces(db=db, current_user=None))
        by_id = {trace['request_id']: trace for trace in result['traces']}
        assert by_id['compressed-request']['prompt_tokens'] == 18250
        assert by_id['compressed-request']['original_input_tokens'] == 38470
        assert by_id['compressed-request']['model_input_tokens'] == 18103
        assert by_id['plain-request']['original_input_tokens'] == 700
        assert by_id['plain-request']['model_input_tokens'] == 700

        detail = asyncio.run(get_trace_detail('compressed-request', db=db, current_user=None))
        assert by_id['compressed-request']['original_input_tokens'] == detail['stages']['compressed']['pre_tokens']
        assert by_id['compressed-request']['model_input_tokens'] == detail['stages']['compressed']['post_tokens']
