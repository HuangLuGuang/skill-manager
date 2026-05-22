from datetime import datetime, timedelta, timezone

import pytest

from agent_manager.core.scanner_tokens import ScannerTokenStore


def test_create_stores_only_hash(tmp_path):
    store = ScannerTokenStore(tmp_path)

    record, plain = store.create(name="customer-a", created_by="admin")

    assert plain.startswith("smsc_live_")
    assert record.token_prefix == plain[:18]
    assert record.token_hash
    assert plain not in (tmp_path / "scanner_tokens.json").read_text()
    assert store.list()[0].name == "customer-a"


def test_validate_updates_last_used(tmp_path):
    store = ScannerTokenStore(tmp_path)
    _record, plain = store.create(name="customer-a")

    validated = store.validate(plain, "scanner:submit", client_ip="127.0.0.1")

    assert validated.name == "customer-a"
    assert store.list()[0].last_used_at is not None


def test_validate_rejects_missing_scope(tmp_path):
    store = ScannerTokenStore(tmp_path)
    _record, plain = store.create(name="customer-a", scopes=["scanner:submit"])

    with pytest.raises(PermissionError):
        store.validate(plain, "scanner:read-own-results")


def test_validate_rejects_revoked_token(tmp_path):
    store = ScannerTokenStore(tmp_path)
    record, plain = store.create(name="customer-a")
    store.revoke(record.id, actor="admin")

    with pytest.raises(PermissionError):
        store.validate(plain, "scanner:submit")


def test_validate_rejects_expired_token(tmp_path):
    store = ScannerTokenStore(tmp_path)
    _record, plain = store.create(
        name="customer-a",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(PermissionError):
        store.validate(plain, "scanner:submit")


def test_validate_accepts_allowed_cidr(tmp_path):
    store = ScannerTokenStore(tmp_path)
    _record, plain = store.create(name="customer-a", allowed_ips=["10.0.0.0/24"])

    validated = store.validate(plain, "scanner:submit", client_ip="10.0.0.42")

    assert validated.name == "customer-a"


def test_runtime_scopes_can_be_created_and_validated(tmp_path):
    store = ScannerTokenStore(tmp_path)
    _record, plain = store.create(
        name="agent-runtime",
        scopes=["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"],
    )

    assert store.validate(plain, "runtime:verify-signature").name == "agent-runtime"
    assert store.validate(plain, "runtime:can-load").name == "agent-runtime"
    assert store.validate(plain, "runtime:check-tool").name == "agent-runtime"


def test_rejects_unknown_scope(tmp_path):
    store = ScannerTokenStore(tmp_path)

    with pytest.raises(ValueError):
        store.create(name="bad", scopes=["admin:all"])
