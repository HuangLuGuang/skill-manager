"""Controlled OpenAI-compatible fixture for AI-Infra-Guard acceptance scans.

The fixture refuses target prompts and synthesizes schema-valid evaluator JSON.
It is intentionally deterministic and must never be presented as a real model.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse


app = FastAPI(title="Controlled AI-Infra-Guard Model Fixture")


def _example(schema: Any, name: str = "") -> Any:
    if not isinstance(schema, dict):
        return None
    if "const" in schema:
        return schema["const"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if isinstance(schema.get("anyOf"), list):
        choices = [item for item in schema["anyOf"] if item.get("type") != "null"]
        return _example(choices[0] if choices else schema["anyOf"][0], name)
    value_type = schema.get("type")
    if value_type == "object" or isinstance(schema.get("properties"), dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or list(properties)
        return {key: _example(properties[key], key) for key in required if key in properties}
    if value_type == "array":
        return []
    if value_type == "integer":
        return 0
    if value_type == "number":
        return 0.0
    if value_type == "boolean":
        return False
    if name == "reason":
        return "Controlled evaluator observed no unsafe target response."
    if name in {"purpose", "category", "verdict"}:
        return "controlled security evaluation"
    return "controlled-value"


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "fixture": "controlled-openai-compatible"}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "controlled-model", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    response_format = body.get("response_format") if isinstance(body, dict) else None
    json_schema = response_format.get("json_schema") if isinstance(response_format, dict) else None
    schema = json_schema.get("schema") if isinstance(json_schema, dict) else None
    model = str(body.get("model") or "")
    if isinstance(schema, dict):
        content = json.dumps(_example(schema), ensure_ascii=False, separators=(",", ":"))
    elif model == "controlled-evaluator":
        content = json.dumps(
            {"score": 0, "reason": "Controlled evaluator observed no unsafe target response."},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        content = "I cannot help with unsafe or policy-bypassing requests."
    prompt_tokens = max(1, len(json.dumps(body, ensure_ascii=False)) // 4)
    completion_tokens = max(1, len(content) // 4)
    return JSONResponse(
        {
            "id": "chatcmpl-controlled-fixture",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model") or "controlled-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    )


@app.get("/infra")
async def infrastructure_fixture():
    return PlainTextResponse(
        "controlled infrastructure fixture",
        headers={"Server": "controlled-fixture/1.0.0"},
    )
