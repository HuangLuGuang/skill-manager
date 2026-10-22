"""Local OpenAI-compatible fixture requiring raw Authorization and X-Customer-ID."""

import argparse
import json
import secrets
import time
import uuid

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse


def create_app(authorization: str, customer_id: str, expected_host: str | None = None) -> FastAPI:
    app = FastAPI(title="Model provider header mock")
    model_id = "header-test-model"

    async def authenticate(request: Request):
        expected = {"authorization": authorization, "x-customer-id": customer_id}
        if expected_host:
            expected["host"] = expected_host
        for name, value in expected.items():
            values = request.headers.getlist(name)
            if len(values) != 1 or not secrets.compare_digest(values[0].encode(), value.encode()):
                raise HTTPException(401, detail={"code": "mock.invalid_header", "header": name})

    @app.get("/health")
    async def health():
        return {"status": "ok", "mock": True}

    @app.get("/customer/v1/models", dependencies=[Depends(authenticate)])
    async def models():
        return {"object": "list", "data": [{"id": model_id, "object": "model", "created": 0, "owned_by": "header-mock"}]}

    @app.post("/customer/v1/chat/completions", dependencies=[Depends(authenticate)])
    async def chat(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or body.get("model") != model_id:
            raise HTTPException(400, detail={"code": "mock.invalid_model"})
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            raise HTTPException(400, detail={"code": "mock.messages_required"})
        if not isinstance(body.get("stream", False), bool):
            raise HTTPException(400, detail={"code": "mock.invalid_stream"})
        text = "OK — mock headers verified; this is not a real model response."
        if isinstance(body.get("response_format"), dict) and body["response_format"].get("type") == "json_object":
            text = json.dumps({"mock": True, "headers_verified": True})
        common = {"id": f"chatcmpl-mock-{uuid.uuid4().hex}", "created": int(time.time()), "model": model_id}
        if body.get("stream"):
            async def chunks():
                for delta, finish in [({"role": "assistant", "content": text}, None), ({}, "stop")]:
                    yield "data: " + json.dumps({**common, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(chunks(), media_type="text/event-stream")
        return {**common, "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18089)
    parser.add_argument("--authorization", default="mock-test-key", help="Exact raw Authorization value (test credential only)")
    parser.add_argument("--customer-id", default="demo-customer")
    parser.add_argument("--expected-host", help="Optional exact Host header, including port if required")
    args = parser.parse_args()
    uvicorn.run(create_app(args.authorization, args.customer_id, args.expected_host), host=args.host, port=args.port)
