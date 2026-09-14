from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.services.gateway_sessions import associate, history_prefixes, finish
from backend.services.runtime_traces import cleanup_expired
from backend.sqlite_db import Base


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def message(value, role="user"):
    return {"role": role, "content": value}


def allocate(factory, messages, request_id, key_id=1, tenant="tenant", **kwargs):
    with factory() as db:
        key = models.LlmApiKey(id=key_id, user_id=None, group_id=None)
        return associate(db, key=key, tenant_id=tenant, messages=messages, request_id=request_id, **kwargs)


def test_extensions_interleaving_and_independent_requests(sessions):
    first = [message("shared", "system"), message("a")]
    second = [message("shared", "system"), message("b")]
    a = allocate(sessions, first, "a")
    b = allocate(sessions, second, "b")
    extended = first + [message("answer", "assistant"), message("next")]
    assert allocate(sessions, extended, "a2")["gateway_trace_id"] == a["gateway_trace_id"]
    assert allocate(sessions, second + [message("next")], "b2")["gateway_trace_id"] == b["gateway_trace_id"]
    repeated = allocate(sessions, extended, "a3")
    assert repeated["match_reason"] == "identical_history"
    assert repeated["request_index"] == 3
    assert allocate(sessions, extended, "other-key", key_id=2)["gateway_trace_id"] != a["gateway_trace_id"]
    assert allocate(sessions, extended, "other-tenant", tenant="other")["gateway_trace_id"] != a["gateway_trace_id"]
    assert allocate(sessions, [message("summary")], "compressed")["gateway_trace_id"] != a["gateway_trace_id"]


def test_explicit_id_survives_history_changes(sessions):
    a = allocate(sessions, [message("a")], "a", explicit_id="session-a", source="x-hermes-session-id")
    b = allocate(sessions, [message("summary")], "b", explicit_id="session-a", source="x-hermes-session-id")
    assert a["gateway_trace_id"] == b["gateway_trace_id"]
    assert allocate(sessions, [message("a")], "c", explicit_id="session-b", source="x-hermes-session-id")["gateway_trace_id"] != a["gateway_trace_id"]


def completed(factory, request_id, messages, answer):
    with factory() as db:
        finish(db, request_id, "completed", {"messages": messages}, {"choices": [{"content": answer}]})


def test_changed_system_requires_observed_answer(sessions):
    initial = [message("old", "system"), message("question")]
    first = allocate(sessions, initial, "first")
    completed(sessions, "first", initial, "observed answer")
    changed = [message("new", "system"), message("question"), message("observed answer", "assistant"), message("next")]
    continuation = allocate(sessions, changed, "next")
    assert continuation["gateway_trace_id"] == first["gateway_trace_id"]
    assert continuation["match_reason"] == "dialogue_extension_v1"
    assert allocate(sessions, [message("new", "system"), message("question")], "fresh")["gateway_trace_id"] != first["gateway_trace_id"]
    changed[2]["content"] = "different answer"
    assert allocate(sessions, changed, "wrong")["gateway_trace_id"] != first["gateway_trace_id"]


def title_messages(user, answer):
    return [message("Generate a short, descriptive title (3-7 words) for a conversation that starts with the following exchange. Return ONLY the title text", "system"),
            message(f"User: {user}\n\nAssistant: {answer}")]


def test_title_association_requires_both_observed_parts_and_scope(sessions):
    messages = [message("question")]
    first = allocate(sessions, messages, "first")
    completed(sessions, "first", messages, "answer")
    title = allocate(sessions, title_messages("question", "answer"), "title")
    assert title["gateway_trace_id"] == first["gateway_trace_id"]
    assert title["match_reason"] == "auxiliary_title_v1"
    assert allocate(sessions, title_messages("question", "invented"), "wrong")["gateway_trace_id"] != first["gateway_trace_id"]
    assert allocate(sessions, title_messages("question", "answer"), "other", key_id=2)["gateway_trace_id"] != first["gateway_trace_id"]
    second = allocate(sessions, [message("different", "system")] + messages, "second")
    completed(sessions, "second", messages, "answer")
    ambiguous = allocate(sessions, title_messages("question", "answer"), "ambiguous")
    assert ambiguous["match_reason"] == "ambiguous_history"
    assert ambiguous["gateway_trace_id"] not in {first["gateway_trace_id"], second["gateway_trace_id"]}


def test_probe_events_keep_checks_separate_from_conversations(sessions):
    messages = [message("connection check")]
    first = allocate(sessions, messages, "first")
    with sessions() as db:
        db.add(models.ClientEvent(client_id="test-client", event_type="model_probe", aggregate_key="probe"))
        db.commit()
    probe = allocate(sessions, messages, "probe", explicit_id="ignored")
    assert probe["match_reason"] == "connection_probe"
    assert probe["gateway_trace_id"] != first["gateway_trace_id"]
    completed(sessions, "probe", messages, "answer")
    with sessions() as db:
        assert db.query(models.GatewaySessionFingerprint).filter_by(request_id="probe").count() == 0


def test_observed_tool_call_matches_only_same_tool_identity(sessions):
    initial = [message("old", "system"), message("read file")]
    first = allocate(sessions, initial, "first")
    call = {"id": "call-a", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'}}
    with sessions() as db:
        finish(db, "first", "completed", {"messages": initial}, {"choices": [{"tool_calls": [call]}]})
    continuation = [message("new", "system"), initial[1], {"role": "assistant", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": "call-a", "content": "file contents"}]
    assert allocate(sessions, continuation, "next")["gateway_trace_id"] == first["gateway_trace_id"]
    continuation[2] = {"role": "assistant", "tool_calls": [{**call, "id": "call-b"}]}
    continuation[3]["tool_call_id"] = "call-b"
    assert allocate(sessions, continuation, "other-call")["gateway_trace_id"] != first["gateway_trace_id"]


def test_failed_and_expired_responses_cannot_supply_evidence(sessions):
    initial = [message("question")]
    allocate(sessions, initial, "failed")
    with sessions() as db:
        finish(db, "failed", "error", {"messages": initial}, {"choices": [{"content": "answer"}]})
        assert db.query(models.GatewaySessionFingerprint).count() == 0
    completed(sessions, "failed", initial, "answer")
    with sessions() as db:
        db.query(models.RuntimeTraceSession).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
        cleanup_expired(db)
        assert db.query(models.GatewaySessionFingerprint).count() == 0


def test_concurrent_first_requests_use_one_group_and_unique_indexes(sessions):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: allocate(sessions, [message("same")], str(i)), range(12)))
    assert len({r["gateway_trace_id"] for r in results}) == 1
    assert sorted(r["request_index"] for r in results) == list(range(1, 13))


def test_concurrent_publication_keeps_all_request_events(sessions, monkeypatch):
    from backend.config import settings
    from backend.routers.llm_gateway import _publish_model_runtime_trace
    monkeypatch.setattr(settings, "RUNTIME_TRACE_ENABLED", True)

    def publish(index):
        request_id = f"concurrent-{index}"
        context = allocate(sessions, [message("same")], request_id)
        with sessions() as db:
            _publish_model_runtime_trace(db, key=models.LlmApiKey(id=1, user_id=None, group_id=None),
                trace_context=context, tenant_id="tenant", request_id=request_id, model_name="test",
                request_payload={"messages":[message("same")]}, response_payload={"choices":[]})
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(publish, range(12)))
    with sessions() as db:
        assert db.query(models.RuntimeTraceSession).one().event_count == 24
        assert sorted(row.seq for row in db.query(models.RuntimeTraceEvent).all()) == list(range(1,25))
        assert db.query(models.GatewaySessionRequest).filter_by(status="completed").count() == 12


def test_ambiguous_longest_match_starts_independent_group(sessions):
    messages = [message("same")]
    a = allocate(sessions, messages, "a")
    b = allocate(sessions, [message("different")], "b")
    with sessions() as db:
        row = db.get(models.GatewaySessionRequest, "b")
        row.history_digest = history_prefixes(messages)[-1]
        db.commit()
    c = allocate(sessions, messages + [message("next")], "c")
    assert c["match_reason"] == "ambiguous_history"
    assert c["gateway_trace_id"] not in {a["gateway_trace_id"], b["gateway_trace_id"]}


def test_expiration_removes_associations(sessions):
    a = allocate(sessions, [message("a")], "a")
    with sessions() as db:
        db.query(models.RuntimeTraceSession).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
        cleanup_expired(db)
        assert db.query(models.GatewaySessionRequest).count() == 0
        assert db.query(models.GatewaySessionGroup).count() == 0
    assert allocate(sessions, [message("a")], "b")["gateway_trace_id"] != a["gateway_trace_id"]


def test_prefix_lookup_uses_index_and_bounded_queries(sessions):
    messages = [message(str(i)) for i in range(78)]
    allocate(sessions, messages[:-1], "a")
    statements = []
    query_parameters = []
    engine = sessions.kw['bind']
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if "history_digest IN" in statement:
            query_parameters.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        allocate(sessions, messages, "b")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert sum("history_digest IN" in sql for sql in statements) == 1
    with engine.connect() as connection:
        sql, parameters = query_parameters[0]
        actual_plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, parameters).all()
        assert "ix_gateway_request_prefix" in str(actual_plan)
        plan = connection.execute(text("EXPLAIN QUERY PLAN SELECT * FROM gateway_session_requests WHERE scope_id=:scope AND history_digest IN (:digest)"), {"scope":"s", "digest":"h"}).all()
        assert "ix_gateway_request_prefix" in str(plan)
