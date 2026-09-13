import asyncio
import json

import httpx
import pytest

from backend import models, schemas
from backend.api_errors import ApiError
from backend.responses_upstream import openai_to_responses_request, responses_to_openai_response
from backend.routers import llm_gateway as gateway


def response(output=None, status="completed"):
    return {"id": "resp_test", "model": "test-model", "created_at": 1, "status": status,
            "output": output if output is not None else [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
                      "input_tokens_details": {"cached_tokens": 1}, "output_tokens_details": {"reasoning_tokens": 1}}}


def test_claude_code_options_on_responses_provider():
    provider = models.ModelProvider(base_url="https://example.test/v1", api_format="responses_api")
    request = {"model": "model", "messages": [{"role": "user", "content": "Hi"}],
               "anthropic_options": {
                   "thinking": {"type": "adaptive", "display": "omitted"},
                   "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
                   "output_config": {"effort": "high"}}}
    _, upstream, _ = gateway._upstream_request(provider, request)
    assert upstream["reasoning"] == {"effort": "high"}
    assert "anthropic_options" not in upstream
    assert request["anthropic_options"]["output_config"] == {"effort": "high"}
    request["anthropic_options"] = {"thinking": {"type": "disabled"}}
    assert gateway._upstream_request(provider, request)[1]["reasoning"] == {"effort": "none"}
    request["anthropic_options"] = {"context_management": {"edits": [{"type": "clear_tool_uses_20250919"}]}}
    with pytest.raises(ApiError) as error:
        gateway._upstream_request(provider, request)
    assert error.value.status_code == 422


def test_request_converts_history_tools_images_and_options():
    payload = openai_to_responses_request({
        "model": "test-model", "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": [{"type": "text", "text": "Read"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]},
            {"role": "assistant", "content": "Checking", "tool_calls": [{"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "found"}],
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        "max_completion_tokens": 128, "reasoning_effort": "low", "verbosity": "low",
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": {"type": "object"}, "strict": True}},
        "stream": True, "stream_options": {"include_usage": True}, "service_tier": "auto"})
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["content"][1]["type"] == "input_image"
    assert payload["input"][2]["content"] == "Checking"
    assert payload["input"][3] == {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": "{}"}
    assert payload["input"][4] == {"type": "function_call_output", "call_id": "call_1", "output": "found"}
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["tool_choice"] == {"type": "function", "name": "lookup"}
    assert payload["max_output_tokens"] == 128 and payload["store"] is False
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["text"]["format"]["name"] == "result"
    assert "stream_options" not in payload


@pytest.mark.parametrize("param", [{"n": 2}, {"stop": ["stop"]}, {"seed": 5}])
def test_unrepresentable_chat_options_return_stable_error(param):
    provider = models.ModelProvider(api_format="responses_api", base_url="https://example.test/v1")
    with pytest.raises(ApiError) as exc:
        gateway._upstream_request(provider, {"messages": [], **param})
    assert exc.value.status_code == 422


def test_response_converts_tool_calls_usage_and_truncation():
    result = responses_to_openai_response(response([{"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": "{}"}]))
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"
    assert result["usage"]["prompt_tokens_details"] == {"cached_tokens": 1}
    assert responses_to_openai_response(response(status="incomplete"))["choices"][0]["finish_reason"] == "length"


@pytest.mark.parametrize("payload", [response(status="failed"), response([]), {"choices": [{}]}, response(status="queued")])
def test_provider_test_does_not_accept_failed_or_empty_response(payload):
    assert not gateway._is_valid_provider_test_response("responses_api", payload)


@pytest.mark.parametrize("api_format,payload", [
    ("openai", {"choices": [{}]}), ("openai", {"choices": [{"message": {"content": "", "reasoning_content": "thinking"}}]}),
    ("anthropic", {"content": []}), ("anthropic", {"content": [{"type": "thinking", "thinking": "wait"}]}),
])
def test_other_provider_formats_require_actual_output(api_format, payload):
    assert not gateway._is_valid_provider_test_response(api_format, payload)


@pytest.mark.parametrize("base", ["https://example.test/custom/v2", "https://example.test/custom/v2/responses/"])
def test_provider_format_schema_endpoint_and_bearer_auth(base):
    data = schemas.ModelProviderCreate(name="test", api_format="responses_api", base_url=base, api_key="secret")
    provider = models.ModelProvider(**data.model_dump())
    url, body, headers = gateway._upstream_request(provider, {"model": "test-model", "messages": [{"role": "user", "content": "Hi"}]})
    assert url == "https://example.test/custom/v2/responses"
    assert headers["authorization"] == "Bearer secret"
    assert body["input"][0]["content"][0]["text"] == "Hi"


def read_stream(events):
    upstream = httpx.Response(200, text="".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events))
    async def collect():
        return [chunk async for chunk in gateway._upstream_sse_data(upstream, "responses_api")]
    return asyncio.run(collect())


def test_stream_maps_text_tools_and_usage_without_duplicate_final_output():
    chunks = read_stream([
        {"type": "response.created", "response": response([])},
        {"type": "response.output_text.delta", "delta": "OK"},
        {"type": "response.output_item.added", "output_index": 2, "item": {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": "{}"},
        {"type": "response.completed", "response": response()},
    ])
    assert chunks[-1] == "[DONE]"
    parsed = [json.loads(c) for c in chunks[:-1]]
    assert parsed[0]["choices"][0]["delta"] == {"content": "OK"}
    assert parsed[1]["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert parsed[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert parsed[-1]["usage"]["total_tokens"] == 5


@pytest.mark.parametrize("events", [[], [{"type": "response.failed", "response": response(status="failed")}], [{"type": "error"}]])
def test_stream_failure_or_disconnect_is_not_success(events):
    with pytest.raises(ApiError):
        read_stream(events)
