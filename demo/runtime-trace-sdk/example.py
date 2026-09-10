from __future__ import annotations

import json
import os
import uuid
from urllib.request import Request, urlopen

from agent_manager.runtime_trace import RuntimeTraceClient, Timer


def call_model(base_url: str, token: str, model: str, metadata: dict[str, str]) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        method="POST",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "用一句话总结已检索到的制度依据"}],
            "metadata": metadata,
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    base_url = os.environ.get("AGENT_MANAGER_URL", "http://127.0.0.1:8000")
    token = os.environ["AGENT_RUNTIME_TOKEN"]
    session_id = f"demo-{uuid.uuid4().hex[:12]}"
    trace = RuntimeTraceClient(base_url, token)
    trace_id = trace.create_trace(session_id)

    turn_id = trace.turn_start(payload={"goal": "查找制度依据并生成摘要"})
    trace.user_message(turn_id, "请查找知识库中的安全制度")
    step_id = trace.step_start(turn_id, payload={"name": "retrieve-and-summarize"})
    trace.knowledge_retrieval(
        turn_id,
        step_id,
        knowledge_base="security-policy",
        document_id="policy-2026",
        chunk_ids=["chunk-7", "chunk-8"],
        redacted_summary="命中两段已脱敏制度摘要",
    )

    model = os.environ.get("AGENT_MANAGER_MODEL")
    if model:
        call_model(
            base_url,
            token,
            model,
            trace.gateway_metadata(turn_id=turn_id, step_id=step_id),
        )

    timer = Timer()
    call_id = trace.tool_call(turn_id, step_id, "policy_search", {"query": "智能体安全"})
    trace.tool_result(
        turn_id,
        step_id,
        call_id,
        "policy_search",
        {"matches": 2},
        duration_ms=timer.duration_ms,
    )
    trace.step_end(turn_id, step_id)
    trace.turn_end(turn_id)
    result = trace.flush()

    print({
        "trace_id": trace_id,
        "session_id": session_id,
        "accepted_count": result.get("accepted_count"),
        "gateway_metadata": trace.gateway_metadata(turn_id=turn_id, step_id=step_id),
    })


if __name__ == "__main__":
    main()
