"""Stateless Gemini GenerateContent bridge to the governed chat pipeline."""
import json
import codecs
import uuid


def gemini_to_chat(payload: dict, model: str, stream: bool) -> dict:
    unknown = set(payload) - {"contents", "systemInstruction", "tools", "toolConfig", "generationConfig", "safetySettings"}
    if unknown:
        raise ValueError("Unsupported Gemini request fields: " + ", ".join(sorted(unknown)))
    if payload.get("safetySettings"):
        raise ValueError("Gemini safetySettings cannot be mapped by this gateway")
    contents = payload.get("contents")
    if not isinstance(contents, list) or not contents:
        raise ValueError("contents must be a non-empty array")
    messages = []
    instruction = payload.get("systemInstruction") or {}
    if instruction:
        parts = instruction.get("parts", [])
        if any(set(part) != {"text"} for part in parts):
            raise ValueError("Only text systemInstruction is supported")
        messages.append({"role": "system", "content": "\n".join(part["text"] for part in parts)})
    calls = {}
    for content in contents:
        if content.get("role", "user") not in {"user", "model"}:
            raise ValueError("Unsupported Gemini content role")
        role = "assistant" if content.get("role") == "model" else "user"
        text, tool_calls, responses = [], [], []
        for part in content.get("parts", []):
            fields = set(part) - {"thoughtSignature", "thought"}
            if fields == {"text"}:
                text.append(part["text"])
            elif fields == {"functionCall"}:
                call = part["functionCall"]
                call_id = call.get("id") or "call_" + uuid.uuid4().hex
                calls.setdefault(call["name"], []).append(call_id)
                tool_calls.append({"id": call_id, "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call.get("args", {}))}})
            elif fields == {"functionResponse"}:
                result = part["functionResponse"]
                pending = calls.get(result["name"], [])
                call_id = result.get("id") or (pending[0] if pending else None)
                if not call_id or call_id not in pending:
                    raise ValueError("functionResponse has no matching functionCall")
                pending.remove(call_id)
                responses.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result.get("response", {}))})
            else:
                raise ValueError("Unsupported Gemini content part")
        if tool_calls and role != "assistant":
            raise ValueError("functionCall must have model role")
        if text or tool_calls:
            message = {"role": role, "content": "\n".join(text) or None}
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)
        messages.extend(responses)
    request = {"model": model, "messages": messages, "stream": stream}
    config = {key: value for key, value in (payload.get("generationConfig") or {}).items() if value is not None}
    mapping = {"temperature": "temperature", "topP": "top_p", "maxOutputTokens": "max_completion_tokens", "stopSequences": "stop"}
    unknown = set(config) - set(mapping) - {"candidateCount"}
    if unknown or config.get("candidateCount", 1) != 1:
        raise ValueError("Unsupported Gemini generationConfig fields")
    for source, target in mapping.items():
        if source in config:
            request[target] = config[source]
    declarations = []
    for tool in payload.get("tools", []):
        if set(tool) != {"functionDeclarations"}:
            raise ValueError("Only Gemini functionDeclarations are supported")
        for declaration in tool["functionDeclarations"]:
            parameters = declaration.get("parametersJsonSchema", declaration.get("parameters", {"type": "object", "properties": {}}))
            declarations.append({"type": "function", "function": {"name": declaration["name"], "description": declaration.get("description", ""), "parameters": _schema(parameters)}})
    if declarations:
        request["tools"] = declarations
    tool_config = (payload.get("toolConfig") or {}).get("functionCallingConfig") or {}
    if tool_config:
        if set(tool_config) - {"mode", "allowedFunctionNames"}:
            raise ValueError("Unsupported Gemini functionCallingConfig")
        mode = tool_config.get("mode", "AUTO")
        if mode not in {"AUTO", "ANY", "NONE"}:
            raise ValueError("Unsupported Gemini function calling mode")
        allowed = tool_config.get("allowedFunctionNames") or []
        if allowed:
            if mode != "ANY" or len(allowed) != 1:
                raise ValueError("Only one forced function name can be mapped")
            request["tool_choice"] = {"type": "function", "function": {"name": allowed[0]}}
        else:
            request["tool_choice"] = {"AUTO": "auto", "ANY": "required", "NONE": "none"}[mode]
    return request


def _schema(value):
    if isinstance(value, dict):
        return {key: (item.lower() if key == "type" and isinstance(item, str) else _schema(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_schema(item) for item in value]
    return value


def chat_to_gemini(result: dict) -> dict:
    choice = result.get("choices", [{}])[0]
    message = choice.get("message", {})
    parts = []
    if message.get("content"):
        parts.append({"text": message["content"]})
    for call in message.get("tool_calls", []):
        function = call["function"]
        parts.append({"functionCall": {"id": call["id"], "name": function["name"], "args": json.loads(function.get("arguments") or "{}")}})
    usage = result.get("usage") or {}
    return {"candidates": [{"index": 0, "content": {"role": "model", "parts": parts}, "finishReason": "MAX_TOKENS" if choice.get("finish_reason") == "length" else "STOP"}],
            "modelVersion": result.get("model"), "responseId": result.get("id"),
            "usageMetadata": {"promptTokenCount": usage.get("prompt_tokens", 0), "candidatesTokenCount": usage.get("completion_tokens", 0), "totalTokenCount": usage.get("total_tokens", 0)}}


async def chat_stream_to_gemini(chunks, model):
    buffer = ""
    calls = {}
    decoder = codecs.getincrementaldecoder("utf-8")()
    async for chunk in chunks:
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            value = json.loads(line[5:].strip())
            if value.get("error"):
                yield "data: " + json.dumps(value) + "\n\n"
                return
            choices = value.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            for call in delta.get("tool_calls", []):
                entry = calls.setdefault(call["index"], {"id": "", "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    entry["id"] = call["id"]
                for key, part in (call.get("function") or {}).items():
                    if key in {"name", "arguments"}:
                        entry["function"][key] += part or ""
            if delta.get("content") or choice.get("finish_reason"):
                result = chat_to_gemini({"model": model, "id": value.get("id"), "usage": value.get("usage"), "choices": [{"message": {"content": delta.get("content"), "tool_calls": list(calls.values()) if choice.get("finish_reason") else []}, "finish_reason": choice.get("finish_reason")}]})
                if not choice.get("finish_reason"):
                    result["candidates"][0].pop("finishReason", None)
                yield "data: " + json.dumps(result) + "\n\n"
