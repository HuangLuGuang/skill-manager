import json

import pytest

from backend.aidr_models import AidrHookEvent
from tests.test_aidr_api import service
from tests.test_aidr_hooks import hook_batch, send


@pytest.mark.parametrize("turn", [None, "native-turn-1"])
@pytest.mark.parametrize("hook,kind", [
    ("UserPromptSubmit", "turn.submit"),
    ("PreToolUse", "tool.pre"),
    ("PostToolUse", "tool.post"),
    ("Stop", "turn.stop"),
])
def test_workbuddy_hook_identity_survives_ingestion(service, turn, hook, kind):
    client, factory = service
    batch = hook_batch()
    event = batch["records"][0]["event"]
    event.update(agent="workbuddy", hook_event=hook, kind=kind)
    if turn is not None:
        event["turn_id"] = turn
    if kind.startswith("tool."):
        event.update(tool="Bash", native_call_id="native-call-1")
        event["behavior"] = dict(
            version=3, policy=event["policy"], body_omitted=False,
            category="command", method="result_fields" if kind == "tool.post" else "direct_fields",
            actions=[], status="unknown",
            result_basis=[], redacted=False, truncated=False, uncertainty=[],
        )
    response = send(client, batch)
    assert response.status_code == 200, response.text
    with factory() as db:
        saved = json.loads(db.query(AidrHookEvent).one().payload_json)["event"]
    assert saved["session_id"] == event["session_id"]
    assert saved.get("turn_id", "") == (turn or "")
    if kind.startswith("tool."):
        assert saved["native_call_id"] == "native-call-1"
