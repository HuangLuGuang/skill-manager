"""Tests for Prompt registry — SQLite CRUD operations."""

import uuid
from datetime import datetime, timezone

import pytest

from agent_manager.core.models import (
    RiskLevel,
    VettingResult,
)
from agent_manager.core.prompt_models import (
    PromptAuditEvent,
    PromptEntry,
    PromptReviewRequest,
    PromptStatus,
    make_prompt_event,
)
from agent_manager.core.registry import Registry


def _make_prompt(name="test-prompt", agent_id="agent-1", status=PromptStatus.APPROVED) -> PromptEntry:
    return PromptEntry(
        prompt_id=str(uuid.uuid4()),
        name=name,
        description="A test prompt",
        agent_id=agent_id,
        content="You are a helpful assistant.",
        status=status,
        risk_level=RiskLevel.BENIGN,
        signature="sigtestsig",
    )


@pytest.fixture
def registry(tmp_path):
    return Registry(data_dir=tmp_path)


class TestPromptRegistryCRUD:
    def test_add_and_get_by_id(self, registry):
        entry = _make_prompt()
        registry.add_prompt(entry)
        found = registry.get_prompt_by_id(entry.prompt_id)
        assert found is not None
        assert found.name == "test-prompt"
        assert found.agent_id == "agent-1"
        assert found.content == "You are a helpful assistant."

    def test_duplicate_id_raises(self, registry):
        entry = _make_prompt()
        registry.add_prompt(entry)
        with pytest.raises(ValueError, match="already exists"):
            registry.add_prompt(entry)

    def test_update_prompt(self, registry):
        entry = _make_prompt(status=PromptStatus.PENDING)
        registry.add_prompt(entry)
        entry.status = PromptStatus.APPROVED
        entry.signature = "new-signature"
        registry.update_prompt(entry)
        found = registry.get_prompt_by_id(entry.prompt_id)
        assert found.status == PromptStatus.APPROVED
        assert found.signature == "new-signature"

    def test_update_nonexistent_raises(self, registry):
        entry = _make_prompt()
        with pytest.raises(KeyError, match="not found"):
            registry.update_prompt(entry)

    def test_get_by_name_exact(self, registry):
        registry.add_prompt(_make_prompt(name="my-system-prompt"))
        found = registry.get_prompt_by_name("my-system-prompt")
        assert found is not None
        assert found.name == "my-system-prompt"

    def test_get_by_name_case_insensitive(self, registry):
        registry.add_prompt(_make_prompt(name="My-Prompt"))
        found = registry.get_prompt_by_name("my-prompt")
        assert found is not None
        assert found.name == "My-Prompt"

    def test_get_by_name_returns_latest(self, registry):
        older = _make_prompt(name="shared-name")
        older.submitted_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        newer = _make_prompt(name="shared-name")
        newer.submitted_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        registry.add_prompt(older)
        registry.add_prompt(newer)
        found = registry.get_prompt_by_name("shared-name")
        assert found.prompt_id == newer.prompt_id

    def test_get_nonexistent(self, registry):
        assert registry.get_prompt_by_id("nonexistent") is None
        assert registry.get_prompt_by_name("nonexistent") is None

    def test_list_all(self, registry):
        registry.add_prompt(_make_prompt(name="prompt-a"))
        registry.add_prompt(_make_prompt(name="prompt-b"))
        all_prompts = registry.list_prompts()
        assert len(all_prompts) == 2

    def test_list_filter_by_status(self, registry):
        registry.add_prompt(_make_prompt(name="a", status=PromptStatus.APPROVED))
        registry.add_prompt(_make_prompt(name="b", status=PromptStatus.PENDING))
        registry.add_prompt(_make_prompt(name="c", status=PromptStatus.RETIRED))

        approved = registry.list_prompts(status=PromptStatus.APPROVED)
        assert len(approved) == 1
        assert approved[0].name == "a"

        pending = registry.list_prompts(status=PromptStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].name == "b"

    def test_list_filter_by_agent(self, registry):
        registry.add_prompt(_make_prompt(name="a", agent_id="agent-x"))
        registry.add_prompt(_make_prompt(name="b", agent_id="agent-y"))
        registry.add_prompt(_make_prompt(name="c", agent_id="agent-x"))

        agent_x = registry.list_prompts(agent_id="agent-x")
        assert len(agent_x) == 2
        names = {e.name for e in agent_x}
        assert names == {"a", "c"}

    def test_list_loadable(self, registry):
        registry.add_prompt(_make_prompt(name="a", status=PromptStatus.APPROVED))
        registry.add_prompt(_make_prompt(name="b", status=PromptStatus.DEPLOYED))
        registry.add_prompt(_make_prompt(name="c", status=PromptStatus.PENDING))
        registry.add_prompt(_make_prompt(name="d", status=PromptStatus.REJECTED))

        loadable = registry.list_prompts_loadable()
        assert len(loadable) == 2
        statuses = {e.status for e in loadable}
        assert statuses == {PromptStatus.APPROVED, PromptStatus.DEPLOYED}

    def test_list_loadable_by_agent(self, registry):
        registry.add_prompt(_make_prompt(name="a", agent_id="agent-x", status=PromptStatus.APPROVED))
        registry.add_prompt(_make_prompt(name="b", agent_id="agent-y", status=PromptStatus.APPROVED))
        registry.add_prompt(_make_prompt(name="c", agent_id="agent-x", status=PromptStatus.DEPLOYED))

        loadable_x = registry.list_prompts_loadable(agent_id="agent-x")
        assert len(loadable_x) == 2

        loadable_y = registry.list_prompts_loadable(agent_id="agent-y")
        assert len(loadable_y) == 1


class TestPromptReviewQueue:
    def test_enqueue_and_list(self, registry):
        req = PromptReviewRequest(
            prompt_id="p-001",
            prompt_name="test-prompt",
            risk_level=RiskLevel.MALICIOUS,
            findings_summary={"total": 3, "CRITICAL": 2},
            submitted_at=datetime.now(timezone.utc),
            notes="Needs review",
        )
        registry.enqueue_prompt_review(req)
        queue = registry.list_prompt_review_queue()
        assert len(queue) == 1
        assert queue[0].prompt_name == "test-prompt"

    def test_dequeue_removes(self, registry):
        req = PromptReviewRequest(
            prompt_id="p-002",
            prompt_name="another-prompt",
            risk_level=RiskLevel.SUSPICIOUS,
            findings_summary={"total": 1},
            submitted_at=datetime.now(timezone.utc),
        )
        registry.enqueue_prompt_review(req)
        dequeued = registry.dequeue_prompt_review("p-002")
        assert dequeued is not None
        assert dequeued.prompt_name == "another-prompt"
        assert registry.list_prompt_review_queue() == []

    def test_dequeue_nonexistent(self, registry):
        assert registry.dequeue_prompt_review("nonexistent") is None


class TestPromptAuditLog:
    def test_log_and_read(self, registry):
        entry = _make_prompt(name="audit-test")
        registry.add_prompt(entry)

        event = PromptAuditEvent(
            event_id=str(uuid.uuid4()),
            event_type="prompt_submitted",
            prompt_id=entry.prompt_id,
            prompt_name=entry.name,
            timestamp=datetime.now(timezone.utc),
            actor="admin",
            details={"agent_id": entry.agent_id},
        )
        registry.log_prompt_event(event)

        events = registry.read_prompt_audit(limit=10)
        assert len(events) == 1
        assert events[0].event_type == "prompt_submitted"
        assert events[0].prompt_name == "audit-test"

    def test_filter_by_prompt_id(self, registry):
        entry_a = _make_prompt(name="a")
        entry_b = _make_prompt(name="b")
        registry.add_prompt(entry_a)
        registry.add_prompt(entry_b)

        registry.log_prompt_event(PromptAuditEvent(
            event_id=str(uuid.uuid4()), event_type="prompt_submitted",
            prompt_id=entry_a.prompt_id, prompt_name="a",
            timestamp=datetime.now(timezone.utc), actor="admin",
        ))
        registry.log_prompt_event(PromptAuditEvent(
            event_id=str(uuid.uuid4()), event_type="prompt_submitted",
            prompt_id=entry_b.prompt_id, prompt_name="b",
            timestamp=datetime.now(timezone.utc), actor="admin",
        ))

        events_a = registry.read_prompt_audit(prompt_id=entry_a.prompt_id)
        assert len(events_a) == 1
        assert events_a[0].prompt_name == "a"

    def test_log_events_time_ordered(self, registry):
        entry = _make_prompt(name="time-test")
        registry.add_prompt(entry)

        ts1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2025, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
        ts3 = datetime(2025, 1, 1, 12, 2, 0, tzinfo=timezone.utc)

        registry.log_prompt_event(PromptAuditEvent(
            event_id=str(uuid.uuid4()), event_type="prompt_submitted",
            prompt_id=entry.prompt_id, prompt_name=entry.name,
            timestamp=ts1, actor="admin",
        ))
        registry.log_prompt_event(PromptAuditEvent(
            event_id=str(uuid.uuid4()), event_type="prompt_vetted",
            prompt_id=entry.prompt_id, prompt_name=entry.name,
            timestamp=ts2, actor="system",
        ))
        registry.log_prompt_event(PromptAuditEvent(
            event_id=str(uuid.uuid4()), event_type="prompt_approved",
            prompt_id=entry.prompt_id, prompt_name=entry.name,
            timestamp=ts3, actor="reviewer",
        ))

        events = registry.read_prompt_audit()
        # Should be in chronological order (oldest first)
        types = [e.event_type for e in events]
        assert types == ["prompt_submitted", "prompt_vetted", "prompt_approved"]


class TestMakePromptEvent:
    def test_creates_event(self):
        entry = _make_prompt(name="my-p")
        event = make_prompt_event("prompt_deployed", entry, actor="deployer", details={"env": "prod"})
        assert event.event_type == "prompt_deployed"
        assert event.prompt_id == entry.prompt_id
        assert event.prompt_name == "my-p"
        assert event.actor == "deployer"
        assert event.details == {"env": "prod"}
        assert event.event_id  # UUID auto-generated
