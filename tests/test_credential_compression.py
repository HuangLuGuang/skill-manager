from sqlalchemy import text

from backend import models
from backend.compression import CompressionResult
from backend.routers import llm_gateway
from tests.test_llm_gateway import _client
from tests.test_access_tokens import _client as access_client


def test_credential_creation_and_edit_preserve_compression_settings(tmp_path):
    client = access_client(tmp_path)
    response = client.post('/api/v1/access/tokens', json={
        'name': 'compressed-model', 'token_type': 'model_gateway', 'scopes': ['model:chat'],
        'enable_compression': True, 'compression_level': 'conservative',
    })
    assert response.status_code == 200, response.text
    row = response.json()['record']
    assert row['enable_compression'] and row['compression_level'] == 'conservative'
    updated = client.put(f"/api/v1/access/tokens/{row['id']}", json={'enable_compression': False})
    assert updated.status_code == 200, updated.text
    assert not updated.json()['enable_compression']


def test_gateway_uses_credential_compression_with_legacy_provider_data(tmp_path, monkeypatch):
    client, token, factory = _client(tmp_path, monkeypatch)
    with factory() as db:
        db.execute(text('ALTER TABLE model_providers ADD COLUMN enable_compression BOOLEAN NOT NULL DEFAULT 1'))
        db.commit()
    calls = []
    def compress(messages, *, model, level):
        calls.append(level)
        return CompressionResult(messages=messages, pre_tokens=20, post_tokens=10, tokens_saved=10)
    monkeypatch.setattr(llm_gateway, 'compress_messages', compress)
    for enabled, level in [(False, 'auto'), (True, 'conservative'), (False, 'conservative')]:
        with factory() as db:
            key = db.query(models.LlmApiKey).one()
            key.enable_compression = enabled
            key.compression_level = level
            db.commit()
        response = client.post('/v1/chat/completions', headers={'Authorization': f'Bearer {token}'},
                               json={'model': 'mock-model', 'messages': [{'role': 'user', 'content': 'jane@example.com'}]})
        assert response.status_code == 200, response.text
        assert response.headers['x-compression'] == ('on' if enabled else 'off')
    assert calls == ['conservative']
