import json
import pytest

from sqlalchemy import create_engine

from backend.config import settings
from backend.security_audit import append_security_audit, verify_security_audit
from backend.sqlite_db import Base


def _engine(tmp_path):
    bind = create_engine(f"sqlite:///{tmp_path / 'security-audit.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=bind)
    return bind


def test_security_audit_chain_is_signed_and_tamper_evident(tmp_path, monkeypatch):
    bind = _engine(tmp_path)
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit-key.pem"))
    append_security_audit(
        event_type="token_created",
        actor="admin",
        resource_type="access_token",
        resource_id="7",
        action="create",
        outcome="success",
        details={"token_type": "agent_runtime"},
        bind=bind,
    )
    append_security_audit(
        event_type="mcp_policy_updated",
        actor="admin",
        resource_type="mcp_tool",
        resource_id="crm__delete",
        action="update",
        outcome="success",
        bind=bind,
    )

    valid = verify_security_audit(bind=bind)
    assert valid["valid"] is True
    assert valid["checked"] == 2
    assert (tmp_path / "audit-key.pem").stat().st_mode & 0o777 == 0o600

    with bind.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE security_audit_events SET details_json = ? WHERE id = 1",
            (json.dumps({"token_type": "mcp_gateway"}),),
        )
    invalid = verify_security_audit(bind=bind)
    assert invalid["valid"] is False
    assert invalid["broken_event_id"]


def test_security_audit_can_export_append_only_jsonl(tmp_path, monkeypatch):
    bind = _engine(tmp_path)
    export_path = tmp_path / "export" / "security-audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit-key.pem"))
    monkeypatch.setattr(settings, "SECURITY_AUDIT_EXPORT_PATH", str(export_path))

    append_security_audit(
        event_type="agent_updated",
        actor="admin",
        resource_type="agent",
        resource_id="agent-1",
        action="update",
        outcome="success",
        bind=bind,
    )

    rows = export_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["event_type"] == "agent_updated"


@pytest.mark.parametrize("field,value", [("details_json", "{broken"), ("timestamp", "not-a-date")])
def test_malformed_audit_record_reports_chain_break(tmp_path, monkeypatch, field, value):
    bind = _engine(tmp_path)
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit-key.pem"))
    for name in ("first", "second"):
        append_security_audit(event_type="agent_updated", actor="admin", resource_type="agent",
                              resource_id=name, action="update", outcome="success", bind=bind)
    with bind.begin() as connection:
        broken_id = connection.exec_driver_sql("SELECT event_id FROM security_audit_events WHERE id = 2").scalar_one()
        connection.exec_driver_sql(f"UPDATE security_audit_events SET {field} = ? WHERE id = 2", (value,))
    assert verify_security_audit(bind=bind) == {
        "valid": False, "checked": 1, "broken_event_id": broken_id, "reason": "record_invalid",
    }
    bind.dispose()
