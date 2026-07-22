import json
import time
import uuid
from typing import Any


def anthropic_to_openai_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if system:
        messages.append({"role": "system", "content": _anthropic_text(system)})

    for message in payload.get("messages", []):
        role = message.get("role")
        content = message.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue

        text_blocks: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content if isinstance(content, list) else []:
            block_type = block.get("type") if isinstance(block, dict) else None
            if block_type == "text":
                text_blocks.append({"type": "text", "text": block.get("text", "")})
            elif block_type == "image":
                source = block.get("source") or {}
                if source.get("type") == "base64":
                    text_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{source.get('media_type', 'application/octet-stream')};base64,{source.get('data', '')}"},
                    })
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                })
            elif block_type == "tool_result":
                messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id"),
                    "content": _anthropic_text(block.get("content", "")),
                })

        if text_blocks or tool_calls or not messages:
            converted: dict[str, Any] = {"role": role, "content": text_blocks or ""}
            if tool_calls:
                converted["tool_calls"] = tool_calls
            messages.append(converted)

    result: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "stream": bool(payload.get("stream", False)),
        "metadata": payload.get("metadata") or {},
    }
    field_map = {
        "max_tokens": "max_tokens",
        "temperature": "temperature",
        "top_p": "top_p",
        "stop_sequences": "stop",
    }
    for source, target in field_map.items():
        if source in payload:
            result[target] = payload[source]
    if payload.get("tools"):
        result["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for tool in payload["tools"]
        ]
    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, dict):
        choice_type = tool_choice.get("type")
        if choice_type == "tool":
            result["tool_choice"] = {"type": "function", "function": {"name": tool_choice.get("name")}}
        elif choice_type == "any":
            result["tool_choice"] = "required"
        elif choice_type == "auto":
            result["tool_choice"] = "auto"
    result["anthropic_options"] = {
        key: payload[key]
        for key in ("top_k", "thinking", "service_tier", "context_management", "output_config")
        if payload.get(key) is not None
    }
    return result


def openai_to_anthropic_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system_parts: list[Any] = []
    for message in payload.get("messages", []):
        role = message.get("role")
        if role == "system":
            system_parts.append(message.get("content", ""))
            continue
        if role == "tool":
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id"),
                    "content": message.get("content", ""),
                }],
            })
            continue

        content = _openai_content_blocks(message.get("content", ""))
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {"raw": function.get("arguments", "")}
            content.append({
                "type": "tool_use",
                "id": tool_call.get("id"),
                "name": function.get("name"),
                "input": arguments,
            })
        messages.append({"role": role, "content": content or [{"type": "text", "text": ""}]})

    result: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "max_tokens": payload.get("max_tokens") or payload.get("max_completion_tokens") or 4096,
        "stream": bool(payload.get("stream", False)),
    }
    if system_parts:
        result["system"] = "\n\n".join(_anthropic_text(part) for part in system_parts)
    field_map = {"temperature": "temperature", "top_p": "top_p", "stop": "stop_sequences"}
    for source, target in field_map.items():
        if source in payload:
            result[target] = payload[source]
    if payload.get("tools"):
        result["tools"] = [
            {
                "name": tool.get("function", {}).get("name"),
                "description": tool.get("function", {}).get("description", ""),
                "input_schema": tool.get("function", {}).get("parameters") or {"type": "object", "properties": {}},
            }
            for tool in payload["tools"]
        ]
    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, dict):
        result["tool_choice"] = {"type": "tool", "name": tool_choice.get("function", {}).get("name")}
    elif tool_choice == "required":
        result["tool_choice"] = {"type": "any"}
    elif tool_choice == "auto":
        result["tool_choice"] = {"type": "auto"}
    return result


def openai_to_anthropic_response(payload: dict[str, Any]) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = _openai_content_blocks(message.get("content", ""))
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {"raw": function.get("arguments", "")}
        content.append({
            "type": "tool_use",
            "id": tool_call.get("id"),
            "name": function.get("name"),
            "input": arguments,
        })
    usage = payload.get("usage") or {}
    return {
        "id": payload.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model"),
        "content": content,
        "stop_reason": _anthropic_stop_reason(choice.get("finish_reason")),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def anthropic_to_openai_response(payload: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    text: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id"),
                "type": "function",
                "function": {
                    "name": block.get("name"),
                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                },
            })
    message["content"] = "".join(text)
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    return {
        "id": payload.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model"),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _openai_finish_reason(payload.get("stop_reason")),
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def anthropic_stream_event_to_openai(event: str, payload: dict[str, Any]) -> list[dict[str, Any] | str]:
    if event == "message_start":
        message = payload.get("message") or {}
        usage = message.get("usage") or {}
        return [{
            "id": message.get("id"),
            "object": "chat.completion.chunk",
            "model": message.get("model"),
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            "usage": {"prompt_tokens": int(usage.get("input_tokens") or 0), "completion_tokens": 0, "total_tokens": int(usage.get("input_tokens") or 0)},
        }]
    if event == "content_block_start":
        block = payload.get("content_block") or {}
        if block.get("type") != "tool_use":
            return []
        index = int(payload.get("index") or 0)
        return [{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": index, "id": block.get("id"), "type": "function", "function": {"name": block.get("name"), "arguments": ""}}]}, "finish_reason": None}]}]
    if event == "content_block_delta":
        delta = payload.get("delta") or {}
        if delta.get("type") == "text_delta":
            return [{"choices": [{"index": 0, "delta": {"content": delta.get("text", "")}, "finish_reason": None}]}]
        if delta.get("type") == "input_json_delta":
            index = int(payload.get("index") or 0)
            return [{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": index, "function": {"arguments": delta.get("partial_json", "")}}]}, "finish_reason": None}]}]
        return []
    if event == "message_delta":
        usage = payload.get("usage") or {}
        output_tokens = int(usage.get("output_tokens") or 0)
        return [{
            "choices": [{"index": 0, "delta": {}, "finish_reason": _openai_finish_reason((payload.get("delta") or {}).get("stop_reason"))}],
            "usage": {"completion_tokens": output_tokens},
        }]
    if event == "message_stop":
        return ["[DONE]"]
    return []


async def openai_stream_to_anthropic(chunks: Any, model: str | None):
    buffer = ""
    started = False
    text_block: int | None = None
    tool_blocks: dict[int, int] = {}
    next_block = 0
    message_id = f"msg_{uuid.uuid4().hex}"
    stop_reason: str | None = None
    output_tokens = 0

    async for chunk in chunks:
        buffer += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in raw_event.splitlines() if line.startswith("data:")]
            if not data_lines:
                continue
            data = "\n".join(data_lines)
            payload: dict[str, Any] = {}
            if data != "[DONE]":
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if payload.get("id"):
                    message_id = payload["id"]
                if payload.get("model"):
                    model = payload["model"]
            usage = payload.get("usage") or {}
            if not started:
                started = True
                yield _sse("message_start", {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0), "output_tokens": 0},
                    },
                })
            if data == "[DONE]":
                for block_index in sorted(([text_block] if text_block is not None else []) + list(tool_blocks.values())):
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                yield _sse("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason or "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": output_tokens},
                })
                yield _sse("message_stop", {"type": "message_stop"})
                return
            if payload.get("error"):
                yield _sse("error", {"type": "error", "error": payload["error"]})
                continue
            output_tokens = max(output_tokens, int(usage.get("completion_tokens") or 0))
            for choice in payload.get("choices") or []:
                if choice.get("finish_reason"):
                    stop_reason = _anthropic_stop_reason(choice["finish_reason"])
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    if text_block is None:
                        text_block = next_block
                        next_block += 1
                        yield _sse("content_block_start", {
                            "type": "content_block_start",
                            "index": text_block,
                            "content_block": {"type": "text", "text": ""},
                        })
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": text_block,
                        "delta": {"type": "text_delta", "text": content},
                    })
                for tool_call in delta.get("tool_calls") or []:
                    tool_index = int(tool_call.get("index") or 0)
                    if tool_index not in tool_blocks:
                        tool_blocks[tool_index] = next_block
                        next_block += 1
                        function = tool_call.get("function") or {}
                        yield _sse("content_block_start", {
                            "type": "content_block_start",
                            "index": tool_blocks[tool_index],
                            "content_block": {
                                "type": "tool_use",
                                "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex}",
                                "name": function.get("name") or "tool",
                                "input": {},
                            },
                        })
                    arguments = (tool_call.get("function") or {}).get("arguments")
                    if arguments:
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": tool_blocks[tool_index],
                            "delta": {"type": "input_json_delta", "partial_json": arguments},
                        })


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _anthropic_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text")
    return str(content or "")


def _openai_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    result: list[dict[str, Any]] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            result.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image_url":
            url = (block.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:
                media_type, data = url[5:].split(";base64,", 1)
                result.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    return result


def _anthropic_stop_reason(reason: str | None) -> str | None:
    return {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}.get(reason, reason)


def _openai_finish_reason(reason: str | None) -> str | None:
    return {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}.get(reason, reason)
