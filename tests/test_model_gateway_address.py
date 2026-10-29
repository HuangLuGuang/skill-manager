import asyncio

import pytest
from pydantic import ValidationError

from backend.config import Settings, settings
from backend.routers.system import get_system_capabilities
from tests.test_client_manual_models import setup_client, URL


@pytest.mark.parametrize("value, expected", [
    ("", ""), (" http://gateway:8000/ ", "http://gateway:8000"),
    ("https://models.example.com", "https://models.example.com"),
    ("http://[::1]:18000", "http://[::1]:18000"),
])
def test_model_origin(value, expected):
    assert Settings(_env_file=None, MODEL_GATEWAY_PUBLIC_URL=value).MODEL_GATEWAY_PUBLIC_URL == expected


@pytest.mark.parametrize("value", [
    "/", "ftp://gateway", "//gateway", "http://", "http://gateway/v1", "http://gateway/?token=x",
    "http://user:password@gateway", "http://@gateway", "http://gateway:0", "http://gateway:65536",
    "http://gateway:bad", "http://gate way", "http://gateway#", "http://gateway?",
    "http://gateway\\admin", "http://gate\nway", "http://" + "a" * 2048,
])
def test_invalid_model_origin(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MODEL_GATEWAY_PUBLIC_URL=value)


def test_manual_configuration_and_web_use_same_model_origin(tmp_path, monkeypatch):
    origin = "http://models.example.test:18000"
    monkeypatch.setattr(settings, "MODEL_GATEWAY_PUBLIC_URL", origin)
    client, headers, body, _ = setup_client(tmp_path)
    options = client.post('/api/v1/clients/manual-host/manual-model/options', headers=headers, json={
        'local_agent_id': body['local_agent_id'], 'agent_type': body['agent_type'],
    })
    assert options.status_code == 200, options.text
    assert options.json()['gateway_url'] == origin
    issued = client.post(URL, headers=headers, json=body)
    assert issued.status_code == 200, issued.text
    assert issued.json()['gateway_url'] == origin
    assert asyncio.run(get_system_capabilities(current_user=None)).model_gateway_url == origin
