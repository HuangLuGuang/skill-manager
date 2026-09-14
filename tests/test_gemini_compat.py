import asyncio
import json

import pytest

from backend.gemini_compat import gemini_to_chat, chat_to_gemini, chat_stream_to_gemini


def test_gemini_text_parameters_and_tool_round_trip():
    payload = {
        "systemInstruction": {"parts": [{"text": "Help"}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Read"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "read", "args": {"path": "sample"}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "read", "response": {"output": "ok"}}}]},
        ],
        "tools": [{"functionDeclarations": [{"name": "read", "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"}}}}]}],
        "generationConfig": {"temperature": 0, "topP": 0.8, "maxOutputTokens": 512},
    }
    result = gemini_to_chat(payload, "model-a", False)
    assert result["model"] == "model-a"
    assert result["temperature"] == 0
    assert result["max_completion_tokens"] == 512
    assert result["messages"][3]["tool_call_id"] == result["messages"][2]["tool_calls"][0]["id"]
    assert result["tools"][0]["function"]["parameters"]["properties"]["path"]["type"] == "string"
    response = chat_to_gemini({"model": "model-a", "choices": [{"message": {"tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": '{"path":"sample"}'}}]}}]})
    assert response["candidates"][0]["content"]["parts"][0]["functionCall"]["args"] == {"path": "sample"}


@pytest.mark.parametrize("extra", [{"unknown": True}, {"safetySettings": [{}]}, {"generationConfig": {"topK": 1}}, {"tools": [{"googleSearch": {}}]}])
def test_rejects_unmapped_gemini_options(extra):
    with pytest.raises(ValueError):
        gemini_to_chat({"contents": [{"parts": [{"text": "hello"}]}], **extra}, "model", False)


def test_streaming_tool_fragments_and_text():
    async def chunks():
        values = [
            {"choices": [{"delta": {"content": "hello"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"path":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]
        for value in values:
            text = "data: " + json.dumps(value) + "\n\n"
            yield text[:8].encode()
            yield text[8:].encode()

    async def collect():
        return [json.loads(item[6:]) async for item in chat_stream_to_gemini(chunks(), "model")]

    result = asyncio.run(collect())
    assert result[0]["candidates"][0]["content"]["parts"] == [{"text": "hello"}]
    assert "finishReason" not in result[0]["candidates"][0]
    assert result[-1]["candidates"][0]["content"]["parts"][0]["functionCall"]["args"] == {"path": "x"}


def test_explicit_tool_response_consumes_matching_call_before_implicit_response():
    payload = {"contents": [
        {"role":"model", "parts":[{"functionCall":{"id":"a", "name":"read"}}, {"functionCall":{"id":"b", "name":"read"}}]},
        {"role":"user", "parts":[{"functionResponse":{"id":"a", "name":"read", "response":{}}}, {"functionResponse":{"name":"read", "response":{}}}]},
    ]}
    converted = gemini_to_chat(payload, 'model', False)
    assert [message['tool_call_id'] for message in converted['messages'] if message['role'] == 'tool'] == ['a', 'b']
    payload['contents'][1]['parts'][0]['functionResponse']['id'] = 'unknown'
    with pytest.raises(ValueError):
        gemini_to_chat(payload, 'model', False)


def test_streaming_utf8_characters_split_between_network_chunks():
    async def chunks():
        value = ('data: ' + json.dumps({'choices':[{'delta':{'content':'模型切换'}}]}, ensure_ascii=False) + '\n\n').encode()
        for byte in value:
            yield bytes([byte])
    async def collect():
        return [json.loads(item[6:]) async for item in chat_stream_to_gemini(chunks(), 'model')]
    result = asyncio.run(collect())
    assert result[0]['candidates'][0]['content']['parts'] == [{'text':'模型切换'}]
