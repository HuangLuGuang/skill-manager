import asyncio
import json

import pytest

from backend.responses_compat import (
    openai_stream_to_responses,
    openai_to_responses_response,
    response_tool_kinds,
    responses_to_openai_request,
)


def test_responses_request_converts_messages_and_namespaced_tools():
    converted = responses_to_openai_request(
        {
            "model": "mock-model",
            "instructions": "Be concise.",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Read it"}]},
                {"type": "function_call_output", "call_id": "call_1", "output": "done"},
            ],
            "tools": [{
                "type": "namespace",
                "name": "workspace",
                "tools": [{"type": "function", "name": "read_file", "parameters": {"type": "object"}}],
            }],
        }
    )
    assert converted["messages"][0] == {"role": "system", "content": "Be concise."}
    assert converted["messages"][1]["content"] == [{"type": "text", "text": "Read it"}]
    assert converted["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "done"}
    assert converted["tools"][0]["function"]["name"] == "workspace__read_file"


def test_responses_response_restores_custom_tool_shape():
    request = {"tools": [{"type": "custom", "name": "apply_patch"}]}
    converted = openai_to_responses_response(
        {
            "model": "mock-model",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "apply_patch", "arguments": json.dumps({"input": "*** Begin Patch"})},
                    }],
                }
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        },
        response_tool_kinds(request),
    )
    assert converted["output"] == [{
        "id": converted["output"][0]["id"],
        "type": "custom_tool_call",
        "status": "completed",
        "call_id": "call_1",
        "name": "apply_patch",
        "input": "*** Begin Patch",
    }]
    assert converted["usage"]["total_tokens"] == 5


def test_responses_request_rejects_unknown_fields():
    with pytest.raises(ValueError, match="Unsupported Responses API fields"):
        responses_to_openai_request({"model": "mock-model", "input": "hello", "unsafe_extension": True})


def test_responses_stream_emits_codex_lifecycle_and_completed_output():
    async def collect():
        async def chunks():
            yield 'data: {"id":"chatcmpl-1","model":"mock-model","choices":[{"index":0,"delta":{"role":"assistant","content":"Hi"},"finish_reason":null}]}\n\n'
            yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
            yield "data: [DONE]\n\n"

        return "".join([event async for event in openai_stream_to_responses(chunks(), "mock-model")])

    body = asyncio.run(collect())
    assert "event: response.created" in body
    assert "event: response.output_item.added" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.output_item.done" in body
    assert "event: response.completed" in body
    assert '"text": "Hi"' in body
    assert '"total_tokens": 3' in body


def test_responses_stream_emits_failed_event_for_upstream_error():
    async def collect():
        async def chunks():
            yield 'data: {"error":{"message":"upstream unavailable","type":"upstream_error"}}\n\n'
            yield "data: [DONE]\n\n"

        return "".join([event async for event in openai_stream_to_responses(chunks(), "mock-model")])

    body = asyncio.run(collect())
    assert "event: response.failed" in body
    assert '"status": "failed"' in body
    assert '"code": "upstream_error"' in body
    assert '"message": "upstream unavailable"' in body
    assert "event: response.completed" not in body
