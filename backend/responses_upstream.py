"""Adapt the gateway's normalized chat messages to a Responses provider."""

from typing import Any


def openai_to_responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    options = dict(payload.pop("anthropic_options", {}) or {})
    thinking = options.pop("thinking", {}) or {}
    output_config = dict(options.pop("output_config", {}) or {})
    effort = output_config.pop("effort", None)
    if effort is not None:
        payload["reasoning_effort"] = effort
    if thinking.get("type") == "disabled":
        payload["reasoning_effort"] = "none"
    elif thinking.get("type") in ("enabled", "adaptive"):
        payload.setdefault("reasoning_effort", "high")
    elif thinking:
        raise ValueError("Unsupported thinking configuration")
    context = options.pop("context_management", {}) or {}
    # Claude Code's keep-all edit does not change the full history sent upstream.
    for edit in context.get("edits", []):
        if edit != {"type": "clear_thinking_20251015", "keep": "all"}:
            raise ValueError("Unsupported context edit")
    if set(context) - {"edits"} or output_config or options:
        raise ValueError("Unsupported Anthropic provider options")
    unsupported = [key for key in ("stop", "presence_penalty", "frequency_penalty", "logit_bias", "seed")
                   if payload.get(key) is not None]
    if payload.get("n") not in (None, 1):
        unsupported.append("n")
    if unsupported:
        raise ValueError(f"Unsupported Responses provider parameters: {', '.join(unsupported)}")
    items = []
    for message in payload.get("messages", []):
        role = message["role"]
        content = message.get("content")
        if role == "tool":
            if isinstance(content, list):
                if any(part.get("type") != "text" for part in content):
                    raise ValueError("Responses provider tool results must contain text")
                content = "\n".join(part["text"] for part in content)
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": content or ""})
            continue
        parts = []
        if isinstance(content, str) and content:
            parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": part["text"]})
                elif part.get("type") == "image_url" and role != "assistant":
                    image = part["image_url"]
                    parts.append({"type": "input_image", "image_url": image["url"], "detail": image.get("detail", "auto")})
                else:
                    raise ValueError("Unsupported Responses provider message content")
        if parts:
            items.append({"role": role, "content": "".join(part["text"] for part in parts) if role == "assistant" else parts})
        for call in message.get("tool_calls") or []:
            function = call["function"]
            items.append({"type": "function_call", "call_id": call["id"],
                          "name": function["name"], "arguments": function.get("arguments") or "{}"})
    result = {"model": payload.get("model"), "input": items, "stream": bool(payload.get("stream")), "store": False}
    for key in ("temperature", "top_p", "user", "service_tier", "parallel_tool_calls"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    limit = payload.get("max_completion_tokens", payload.get("max_tokens"))
    if limit is not None:
        result["max_output_tokens"] = limit
    if payload.get("reasoning_effort") is not None:
        result["reasoning"] = {"effort": payload["reasoning_effort"]}
    text = {}
    if payload.get("verbosity") is not None:
        text["verbosity"] = payload["verbosity"]
    response_format = payload.get("response_format")
    if response_format:
        text["format"] = ({"type": "json_schema", **response_format["json_schema"]}
                          if response_format.get("type") == "json_schema" else response_format)
    if text:
        result["text"] = text
    if payload.get("tools") is not None:
        result["tools"] = []
        for tool in payload["tools"]:
            if tool.get("type") != "function":
                raise ValueError("Responses provider supports function tools")
            result["tools"].append({"type": "function", "strict": False, **tool["function"]})
    choice = payload.get("tool_choice")
    if choice is not None:
        result["tool_choice"] = ({"type": "function", "name": choice["function"]["name"]}
                                 if isinstance(choice, dict) else choice)
    return result


def responses_to_openai_response(payload: dict[str, Any]) -> dict[str, Any]:
    if (not isinstance(payload, dict) or payload.get("error") or
            payload.get("status") not in ("completed", "incomplete") or not isinstance(payload.get("output"), list)):
        raise ValueError("Invalid or failed Responses provider response")
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    calls = []
    for item in payload["output"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid Responses output item")
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    raise ValueError("Invalid Responses content part")
                if part.get("type") == "output_text":
                    message["content"] += part.get("text", "")
                elif part.get("type") == "refusal":
                    message["content"] += part.get("refusal", "")
        elif item.get("type") == "function_call":
            calls.append({"id": item["call_id"], "type": "function",
                          "function": {"name": item["name"], "arguments": item.get("arguments", "")}})
    if calls:
        message["tool_calls"] = calls
    usage = payload.get("usage") or {}
    prompt = usage.get("input_tokens") or 0
    completion = usage.get("output_tokens") or 0
    reason = "length" if payload.get("status") == "incomplete" else "tool_calls" if calls else "stop"
    return {"id": payload.get("id"), "object": "chat.completion", "created": payload.get("created_at", 0),
            "model": payload.get("model"), "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": usage.get("total_tokens", prompt + completion),
                      "prompt_tokens_details": usage.get("input_tokens_details") or {},
                      "completion_tokens_details": usage.get("output_tokens_details") or {}}
            if any(usage.get(key) is not None for key in ("input_tokens", "output_tokens", "total_tokens")) else {}}


class ResponsesStreamAdapter:
    def __init__(self):
        self.response = {}
        self.tools = {}
        self.completed = False

    def convert(self, event: dict[str, Any]) -> list[Any]:
        if not isinstance(event, dict):
            raise ValueError("Invalid Responses stream event")
        kind = event.get("type")
        if kind in ("error", "response.failed"):
            raise ValueError("Responses provider stream failed")
        if kind == "response.created":
            self.response = event.get("response") or {}
        delta = None
        if kind == "response.output_text.delta":
            delta = {"content": event.get("delta", "")}
        elif kind == "response.refusal.delta":
            delta = {"content": event.get("delta", "")}
        elif kind == "response.output_item.added" and event.get("item", {}).get("type") == "function_call":
            item = event["item"]
            index = len(self.tools)
            self.tools[event["output_index"]] = index
            delta = {"tool_calls": [{"index": index, "id": item["call_id"], "type": "function",
                                     "function": {"name": item["name"], "arguments": item.get("arguments", "")}}]}
        elif kind == "response.function_call_arguments.delta":
            delta = {"tool_calls": [{"index": self.tools[event["output_index"]],
                                     "function": {"arguments": event.get("delta", "")}}]}
        elif kind in ("response.completed", "response.incomplete"):
            result = responses_to_openai_response(event["response"])
            self.completed = True
            return [{"id": result["id"], "object": "chat.completion.chunk", "created": result["created"],
                     "model": result["model"], "choices": [{"index": 0, "delta": {},
                     "finish_reason": result["choices"][0]["finish_reason"]}], "usage": result["usage"]}, "[DONE]"]
        if delta is None:
            return []
        return [{"id": self.response.get("id"), "object": "chat.completion.chunk",
                 "created": self.response.get("created_at", 0), "model": self.response.get("model"),
                 "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}]
