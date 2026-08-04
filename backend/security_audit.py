"""Tamper-evident SQLite security audit chain with Ed25519 signatures."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.engine import Engine

from .config import settings
from .sqlite_db import engine


GENESIS_HASH = "0" * 64


def _key_path() -> Path:
    configured = settings.AUDIT_SIGNING_PRIVATE_KEY_PATH
    return Path(configured).expanduser().resolve() if configured else Path(settings.DATA_DIR).resolve() / "signing" / "audit-ed25519.pem"


def _load_or_create_key() -> Ed25519PrivateKey:
    path = _key_path()
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"Audit signing key is not Ed25519: {path}")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    encoded = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
        path.chmod(0o600)
        return key
    except FileExistsError:
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise RuntimeError(f"Audit signing key is not Ed25519: {path}")
        return loaded


def ensure_audit_signing_key() -> Path:
    _load_or_create_key()
    return _key_path()


def _key_id(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def append_security_audit(
    *,
    event_type: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    action: str,
    outcome: str,
    details: dict | None = None,
    bind: Engine = engine,
) -> dict:
    key = _load_or_create_key()
    event_id = uuid.uuid4().hex
    timestamp = datetime.utcnow()
    connection = bind.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        previous = connection.exec_driver_sql(
            "SELECT event_hash FROM security_audit_events ORDER BY id DESC LIMIT 1"
        ).first()
        prev_hash = previous[0] if previous else GENESIS_HASH
        payload = {
            "event_id": event_id,
            "timestamp": timestamp.isoformat(timespec="microseconds"),
            "event_type": event_type,
            "actor": actor,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "outcome": outcome,
            "details": details or {},
            "prev_hash": prev_hash,
        }
        event_hash = hashlib.sha256(_canonical(payload)).hexdigest()
        signature = base64.b64encode(key.sign(bytes.fromhex(event_hash))).decode("ascii")
        connection.exec_driver_sql(
            """
            INSERT INTO security_audit_events
                (event_id, timestamp, event_type, actor, resource_type, resource_id,
                 action, outcome, details_json, prev_hash, event_hash, key_id, signature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, timestamp, event_type, actor, resource_type, resource_id,
                action, outcome, json.dumps(details or {}, ensure_ascii=False), prev_hash,
                event_hash, _key_id(key), signature,
            ),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction():
            connection.rollback()
        raise
    finally:
        connection.close()
    result = {**payload, "event_hash": event_hash, "key_id": _key_id(key), "signature": signature}
    _export_event(result)
    return result


def _export_event(event: dict) -> None:
    configured = settings.SECURITY_AUDIT_EXPORT_PATH
    if not configured:
        return
    path = Path(configured).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def verify_security_audit(*, bind: Engine = engine) -> dict:
    key = _load_or_create_key()
    expected_prev = GENESIS_HASH
    checked = 0
    with bind.connect() as connection:
        rows = connection.exec_driver_sql(
            """
            SELECT id, event_id, timestamp, event_type, actor, resource_type, resource_id,
                   action, outcome, details_json, prev_hash, event_hash, key_id, signature
            FROM security_audit_events ORDER BY id ASC
            """
        ).mappings().all()
    for row in rows:
        details = json.loads(row["details_json"] or "{}")
        stored_timestamp = row["timestamp"]
        normalized_timestamp = (
            stored_timestamp.isoformat(timespec="microseconds")
            if isinstance(stored_timestamp, datetime)
            else datetime.fromisoformat(str(stored_timestamp)).isoformat(timespec="microseconds")
        )
        payload = {
            "event_id": row["event_id"],
            "timestamp": normalized_timestamp,
            "event_type": row["event_type"],
            "actor": row["actor"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "action": row["action"],
            "outcome": row["outcome"],
            "details": details,
            "prev_hash": row["prev_hash"],
        }
        actual = hashlib.sha256(_canonical(payload)).hexdigest()
        try:
            key.public_key().verify(base64.b64decode(row["signature"], validate=True), bytes.fromhex(row["event_hash"]))
        except Exception:
            return {"valid": False, "checked": checked, "broken_event_id": row["event_id"], "reason": "signature_invalid"}
        if row["prev_hash"] != expected_prev or row["event_hash"] != actual or row["key_id"] != _key_id(key):
            return {"valid": False, "checked": checked, "broken_event_id": row["event_id"], "reason": "hash_chain_invalid"}
        expected_prev = row["event_hash"]
        checked += 1
    return {"valid": True, "checked": checked, "head_hash": expected_prev}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Agent Manager security audit chain")
    parser.add_argument("command", choices=["verify"])
    parser.parse_args()
    result = verify_security_audit()
    print(json.dumps(result, ensure_ascii=False))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
