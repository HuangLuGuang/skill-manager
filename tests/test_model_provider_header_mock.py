import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


spec = importlib.util.spec_from_file_location("header_mock", Path(__file__).parents[1] / "demo/model-provider-header-mock/server.py")
mock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)


@pytest.mark.parametrize("path", ["/customer/v1/models", "/customer/v1/chat/completions"])
def test_authentication_and_responses(path):
    client = TestClient(mock.create_app("test-key", "customer"))
    body = {"model": "header-test-model", "messages": [{"role": "user", "content": "hello"}]}
    def call(headers, stream=False):
        return client.get(path, headers=headers) if path.endswith("models") else client.post(path, headers=headers, json={**body, "stream": stream})
    valid = {"Authorization": "test-key", "X-Customer-ID": "customer"}
    for headers in [{}, {"Authorization": "test-key"}, {"X-Customer-ID": "customer"}, {**valid, "Authorization": "Bearer test-key"}, {**valid, "X-Customer-ID": "wrong"}, [("Authorization", "test-key"), ("Authorization", "test-key"), ("X-Customer-ID", "customer")]]:
        result = call(headers)
        assert result.status_code == 401
        assert "test-key" not in result.text
    result = call(valid)
    assert result.status_code == 200
    if path.endswith("models"):
        assert result.json()["data"][0]["id"] == "header-test-model"
    else:
        assert "mock" in result.json()["choices"][0]["message"]["content"]
        assert "data: [DONE]" in call(valid, stream=True).text


def test_optional_host():
    client = TestClient(mock.create_app("test-key", "customer", "model.customer.test"))
    headers = {"Authorization": "test-key", "X-Customer-ID": "customer"}
    assert client.get("/customer/v1/models", headers=headers).status_code == 401
    assert client.get("/customer/v1/models", headers={**headers, "Host": "model.customer.test"}).status_code == 200
    assert client.get("/health").status_code == 200
