import json
import time
import uuid
from typing import Any, AsyncIterator


RESPONSES_REQUEST_FIELDS = {
    "background", "client_metadata", "conversation", "include", "input", "instructions", "max_output_tokens",
    "metadata", "model", "parallel_tool_calls", "previous_response_id", "prompt",
    "prompt_cache_key", "prompt_cache_retention", "reasoning", "safety_identifier",
    "service_tier", "store", "stream", "stream_options", "temperature", "text",
    "tool_choice", "tools", "top_p", "truncation", "user",
}


def responses_to_openai_request(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - RESPONSES_REQUEST_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported Responses API fields: {', '.join(unknown)}")
    if "input" not in payload:
        raise ValueError("Responses API field 'input' is required")
    for field in ("previous_response_id", "conversation", "prompt"):
        if payload.get(field):
            raise ValueError(f"Responses API field '{field}' requires server-side state; send the full input history")
    if payload.get("background") or payload.get("store"):
        raise ValueError("This gateway supports foreground, stateless Responses requests; use background=false and store=false")
    messages: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})
    input_value = payload.get("input")
    if isinstance(input_value, str):
        messages.append({"role": "user", "content": input_value})
    elif isinstance(input_value, list):
        _append_response_input(messages, input_value)
    else:
        raise ValueError("Responses API field 'input' must be a string or array")
    result: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "stream": bool(payload.get("stream", False)),
        "metadata": {**dict(payload.get("client_metadata") or {}), **dict(payload.get("metadata") or {})},
    }
    for source, target in {
        "max_output_tokens": "max_completion_tokens", "temperature": "temperature",
        "top_p": "top_p", "user": "user",
    }.items():
        if payload.get(source) is not None:
            result[target] = payload[source]
    if payload.get("service_tier") is not None:
        result["service_tier"] = payload["service_tier"]
    if payload.get("parallel_tool_calls") is not None:
        result["parallel_tool_calls"] = payload["parallel_tool_calls"]
    if payload.get("stream_options") is not None:
        result["stream_options"] = payload["stream_options"]
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort") is not None:
        result["reasoning_effort"] = reasoning["effort"]
    text = payload.get("text")
    if isinstance(text, dict):
        if text.get("verbosity") is not None:
            result["verbosity"] = text["verbosity"]
        text_format = text.get("format")
        if isinstance(text_format, dict) and text_format.get("type") in {"text", "json_object"}:
            result["response_format"] = {"type": text_format["type"]}
        if isinstance(text_format, dict) and text_format.get("type") == "json_schema":
            result["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": text_format.get("name") or "response",
                    "description": text_format.get("description"),
                    "schema": text_format.get("schema") or {},
                    "strict": bool(text_format.get("strict", False)),
                },
            }
    tools = payload.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            raise ValueError("Responses API field 'tools' must be an array")
        result["tools"] = []
        for tool in tools:
            result["tools"].extend(_response_tool_to_openai(tool))
    if payload.get("tool_choice") is not None:
        result["tool_choice"] = _response_tool_choice_to_openai(payload["tool_choice"])
    return result


def _append_response_input(messages: list[dict[str, Any]], items: list[Any]) -> None:
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Responses API input items must be objects")
        item_type = item.get("type")
        if item_type in {None, "message"}:
            messages.append({
                "role": str(item.get("role") or "user"),
                "content": _response_content_to_openai(item.get("content", "")),
            })
        elif item_type == "function_call":
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": item.get("call_id") or item.get("id"), "type": "function",
                    "function": {"name": item.get("name"), "arguments": item.get("arguments") or "{}"},
                }],
            })
        elif item_type == "function_call_output":
            messages.append({
                "role": "tool", "tool_call_id": item.get("call_id"),
                "content": _response_content_to_text(item.get("output", "")),
            })
        elif item_type == "custom_tool_call":
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": item.get("call_id") or item.get("id"), "type": "function",
                    "function": {
                        "name": item.get("name"),
                        "arguments": json.dumps({"input": item.get("input", "")}, ensure_ascii=False),
                    },
                }],
            })
        elif item_type == "custom_tool_call_output":
            messages.append({
                "role": "tool", "tool_call_id": item.get("call_id"),
                "content": _response_content_to_text(item.get("output", "")),
            })
        elif item_type == "reasoning":
            continue
        elif item_type == "item_reference":
            raise ValueError("Responses item_reference requires server-side state; send the full input item")
        else:
            raise ValueError(f"Unsupported Responses API input item type: {item_type}")


def _response_content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("Responses API message content must be a string or array")
    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("Responses API content blocks must be objects")
        block_type = block.get("type")
        if block_type in {"input_text", "output_text", "text"}:
            blocks.append({"type": "text", "text": block.get("text", "")})
        elif block_type == "input_image" and block.get("image_url"):
            blocks.append({"type": "image_url", "image_url": {"url": block["image_url"]}})
        elif block_type == "input_file":
            raise ValueError("Responses API input_file is not supported by this gateway")
        else:
            raise ValueError(f"Unsupported Responses API content type: {block_type}")
    return blocks


def _response_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or block.get("output") or "")
            for block in content if isinstance(block, dict)
        )
    return json.dumps(content, ensure_ascii=False)


def _response_tool_to_openai(tool: Any) -> list[dict[str, Any]]:
    if not isinstance(tool, dict):
        raise ValueError("Responses API tools must be objects")
    tool_type = tool.get("type")
    if tool_type == "function":
        return [_openai_function_tool(tool.get("name"), tool.get("description", ""), tool.get("parameters"), bool(tool.get("strict", False)))]
    if tool_type == "custom":
        return [_openai_function_tool(
            tool.get("name"), tool.get("description", ""),
            {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"], "additionalProperties": False},
            False,
        )]
    if tool_type == "namespace":
        namespace = str(tool.get("name") or "")
        nested = tool.get("tools") or []
        if not namespace or not isinstance(nested, list):
            raise ValueError("Responses API namespace tools require a name and tools array")
        result: list[dict[str, Any]] = []
        for child in nested:
            if not isinstance(child, dict) or child.get("type") != "function":
                raise ValueError("Only function tools are supported inside a Responses namespace")
            result.append(_openai_function_tool(
                f"{namespace}__{child.get('name')}", child.get("description", ""),
                child.get("parameters"), bool(child.get("strict", False)),
            ))
        return result
    raise ValueError(f"Unsupported Responses API tool type: {tool_type}")


def _openai_function_tool(name: Any, description: Any, parameters: Any, strict: bool) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description or "",
        "parameters": parameters or {"type": "object", "properties": {}}, "strict": strict,
    }}


def response_tool_kinds(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for tool in payload.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type") or "")
        name = str(tool.get("name") or "")
        if tool_type == "custom" and name:
            result[name] = {"type": "custom", "name": name}
        elif tool_type == "namespace" and name:
            for child in tool.get("tools") or []:
                if isinstance(child, dict) and child.get("type") == "function" and child.get("name"):
                    flattened = f"{name}__{child['name']}"
                    result[flattened] = {"type": "function", "name": str(child["name"]), "namespace": name}
    return result


def _response_tool_choice_to_openai(tool_choice: Any) -> Any:
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict) and tool_choice.get("type") in {"function", "custom"}:
        return {"type": "function", "function": {"name": tool_choice.get("name")}}
    raise ValueError("Unsupported Responses API tool_choice")


def _tool_item(name: Any, arguments: str, call_id: Any, tool_kinds: dict[str, dict[str, str]] | None, *, status: str = "completed", item_id: str | None = None) -> dict[str, Any]:
    name = str(name or "")
    kind = (tool_kinds or {}).get(name, {})
    if kind.get("type") == "custom":
        custom_input = arguments
        try:
            parsed = json.loads(arguments or "{}")
            if isinstance(parsed, dict) and isinstance(parsed.get("input"), str):
                custom_input = parsed["input"]
        except json.JSONDecodeError:
            pass
        return {"id": item_id or f"ctc_{uuid.uuid4().hex}", "type": "custom_tool_call", "status": status, "call_id": call_id or f"call_{uuid.uuid4().hex}", "name": kind.get("name") or name, "input": custom_input}
    item = {"id": item_id or f"fc_{uuid.uuid4().hex}", "type": "function_call", "status": status, "call_id": call_id or f"call_{uuid.uuid4().hex}", "name": kind.get("name") or name, "arguments": arguments}
    if kind.get("namespace"):
        item["namespace"] = kind["namespace"]
    return item


def openai_to_responses_response(payload: dict[str, Any], tool_kinds: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output: list[dict[str, Any]] = []
    content = message.get("content")
    text = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict)) if isinstance(content, list) else str(content or "")
    if text or not message.get("tool_calls"):
        output.append({"id": f"msg_{uuid.uuid4().hex}", "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}]})
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") or {}
        output.append(_tool_item(function.get("name"), function.get("arguments") or "{}", tool_call.get("id"), tool_kinds))
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    result = {"id": f"resp_{uuid.uuid4().hex}", "object": "response", "created_at": int(payload.get("created") or time.time()), "status": "completed", "error": None, "incomplete_details": None, "model": payload.get("model"), "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "usage": {"input_tokens": input_tokens, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": output_tokens, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens)}}

    if choice.get("finish_reason") == "length":
        result["status"] = "incomplete"
        result["incomplete_details"] = {"reason": "max_output_tokens"}
    return result


async def openai_stream_to_responses(chunks: Any, model: str | None, tool_kinds: dict[str, dict[str, str]] | None = None) -> AsyncIterator[str]:
    response_id = f"resp_{uuid.uuid4().hex}"
    message_id = f"msg_{uuid.uuid4().hex}"
    response = _stream_response(response_id, model, "in_progress", [])
    yield _sse("response.created", {"type": "response.created", "response": response, "sequence_number": 0})
    yield _sse("response.in_progress", {"type": "response.in_progress", "response": response, "sequence_number": 1})
    buffer, text_started = "", False
    text_parts: list[str] = []
    tools: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    sequence = 2
    next_output_index = 0
    text_index = 0
    finish_reason = None
    async for chunk in chunks:
        buffer += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in raw_event.splitlines() if line.startswith("data:")]
            if not data_lines:
                continue
            data = "\n".join(data_lines)
            if data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            error = payload.get("error")
            if isinstance(error, dict):
                response_error = {
                    "code": str(error.get("code") or error.get("type") or "upstream_error"),
                    "message": str(error.get("message") or "Upstream model request failed"),
                }
                yield _sse(
                    "response.failed",
                    {
                        "type": "response.failed",
                        "response": _stream_response(
                            response_id,
                            model,
                            "failed",
                            [],
                            error=response_error,
                        ),
                        "sequence_number": sequence,
                    },
                )
                return
            model = payload.get("model") or model
            if isinstance(payload.get("usage"), dict):
                usage.update(payload["usage"])
            for choice in payload.get("choices") or []:
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                value = delta.get("content")
                if isinstance(value, str) and value:
                    if not text_started:
                        text_started = True
                        text_index = next_output_index
                        next_output_index += 1
                        item = {"id": message_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}
                        yield _sse("response.output_item.added", {"type": "response.output_item.added", "output_index": text_index, "item": item, "sequence_number": sequence})
                        sequence += 1
                        yield _sse("response.content_part.added", {"type": "response.content_part.added", "item_id": message_id, "output_index": text_index, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []}, "sequence_number": sequence})
                        sequence += 1
                    text_parts.append(value)
                    yield _sse("response.output_text.delta", {"type": "response.output_text.delta", "item_id": message_id, "output_index": text_index, "content_index": 0, "delta": value, "logprobs": [], "sequence_number": sequence})
                    sequence += 1
                for tool_call in delta.get("tool_calls") or []:
                    index = int(tool_call.get("index") or 0)
                    current = tools.setdefault(index, {"id": f"fc_{uuid.uuid4().hex}", "call_id": tool_call.get("id") or f"call_{uuid.uuid4().hex}", "name": "", "arguments": "", "started": False})
                    if tool_call.get("id"):
                        current["call_id"] = tool_call["id"]
                    function = tool_call.get("function") or {}
                    if function.get("name"):
                        current["name"] = function["name"]
                    if current["name"] and not current["started"]:
                        current["started"] = True
                        current["output_index"] = next_output_index
                        next_output_index += 1
                        yield _sse("response.output_item.added", {"type": "response.output_item.added", "output_index": current["output_index"], "item": _tool_item(current["name"], "", current["call_id"], tool_kinds, status="in_progress", item_id=current["id"]), "sequence_number": sequence})
                        sequence += 1
                    arguments = function.get("arguments")
                    if isinstance(arguments, str) and arguments:
                        current["arguments"] += arguments
                        if (tool_kinds or {}).get(current["name"], {}).get("type") != "custom":
                            yield _sse("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": current["id"], "output_index": current["output_index"], "delta": arguments, "sequence_number": sequence})
                            sequence += 1
    output: list[dict[str, Any]] = []
    if text_started:
        text = "".join(text_parts)
        message_item = {"id": message_id, "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}]}
        yield _sse("response.output_text.done", {"type": "response.output_text.done", "item_id": message_id, "output_index": text_index, "content_index": 0, "text": text, "logprobs": [], "sequence_number": sequence})
        sequence += 1
        yield _sse("response.content_part.done", {"type": "response.content_part.done", "item_id": message_id, "output_index": text_index, "content_index": 0, "part": message_item["content"][0], "sequence_number": sequence})
        sequence += 1
        yield _sse("response.output_item.done", {"type": "response.output_item.done", "output_index": text_index, "item": message_item, "sequence_number": sequence})
        sequence += 1
        output.append(message_item)
    for index, current in sorted(tools.items()):
        output_index = current["output_index"]
        item = _tool_item(current["name"], current["arguments"], current["call_id"], tool_kinds, item_id=current["id"])
        custom = item["type"] == "custom_tool_call"
        event_type = "response.custom_tool_call_input.done" if custom else "response.function_call_arguments.done"
        yield _sse(event_type, {"type": event_type, "item_id": current["id"], "output_index": output_index,
                                "input" if custom else "arguments": item["input"] if custom else item["arguments"], "sequence_number": sequence})
        sequence += 1
        yield _sse("response.output_item.done", {"type": "response.output_item.done", "output_index": output_index, "item": item, "sequence_number": sequence})
        sequence += 1
        output.append(item)
    positions = {message_id: text_index, **{item["id"]: item["output_index"] for item in tools.values()}}
    output.sort(key=lambda item: positions[item["id"]])
    status = "incomplete" if finish_reason == "length" else "completed"
    final = _stream_response(response_id, model, "completed", output, usage)
    final["status"] = status
    if status == "incomplete":
        final["incomplete_details"] = {"reason": "max_output_tokens"}
    yield _sse(f"response.{status}", {"type": f"response.{status}", "response": final, "sequence_number": sequence})


def _stream_response(
    response_id: str,
    model: str | None,
    status: str,
    output: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
    *,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_tokens = int((usage or {}).get("prompt_tokens") or 0)
    completion_tokens = int((usage or {}).get("completion_tokens") or 0)
    return {"id": response_id, "object": "response", "created_at": int(time.time()), "status": status, "error": error, "incomplete_details": None, "model": model, "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "usage": None if status != "completed" else {"input_tokens": prompt_tokens, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": completion_tokens, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": int((usage or {}).get("total_tokens") or prompt_tokens + completion_tokens)}}


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
