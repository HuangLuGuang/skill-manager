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


def test_responses_common_client_parameters_and_state_boundary():
    body = responses_to_openai_request({'input':'hi', 'parallel_tool_calls':False, 'store':False, 'client_metadata': {'session_id': 'test'},
                                        'text':{'format':{'type':'json_object'}}, 'service_tier':'auto'})
    assert body['parallel_tool_calls'] is False
    assert body['response_format'] == {'type':'json_object'}
    assert body['service_tier'] == 'auto'
    assert body['metadata']['session_id'] == 'test'
    for field, value in [('previous_response_id','resp-old'), ('background',True), ('store',True)]:
        with pytest.raises(ValueError):
            responses_to_openai_request({'input':'hi', field:value})


def test_responses_stream_sequences_and_truncation():
    async def collect():
        async def chunks():
            yield 'data: {"choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":"length"}]}\n\n'
            yield 'data: [DONE]\n\n'
        return [json.loads(line[6:]) for event in [event async for event in openai_stream_to_responses(chunks(),'model')]
                for line in event.splitlines() if line.startswith('data: ')]
    events = asyncio.run(collect())
    assert [event['sequence_number'] for event in events] == list(range(len(events)))
    assert events[-1]['type'] == 'response.incomplete'
    assert events[-1]['response']['incomplete_details']['reason'] == 'max_output_tokens'


def test_responses_stream_preserves_item_indices_when_text_follows_tool():
    async def collect():
        async def chunks():
            for delta in [
                {'tool_calls': [{'index': 0, 'id': 'call-test', 'function': {'name': 'read_file', 'arguments': '{}'}}]},
                {'content': 'Reading'},
            ]:
                yield 'data: ' + json.dumps({'choices':[{'index':0, 'delta':delta}]}) + '\n\n'
        return [json.loads(line[6:]) for event in [event async for event in openai_stream_to_responses(chunks(),'model')]
                for line in event.splitlines() if line.startswith('data: ')]
    events = asyncio.run(collect())
    added = {event['item']['id']: event['output_index'] for event in events if event['type'] == 'response.output_item.added'}
    for event in events:
        if event['type'] == 'response.output_item.done':
            assert event['output_index'] == added[event['item']['id']]
    assert [item['type'] for item in events[-1]['response']['output']] == ['function_call', 'message']
