"""Offline vendor entitlements, shared by API workers and background jobs."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FEATURES = ("skill_governance", "security_scanning", "aidr", "mcp_gateway", "model_gateway")
POLICY = "read_export_and_existing_runtime"
MAX_FILE = 65536
ROOT = Path(__file__).resolve().parents[2]
ERRORS = {
    "invalid": ("授权文件格式或签名无效", "Invalid license format or signature"),
    "untrusted_key": ("签发公钥不受信任，请联系管理员配置", "The issuing key is not trusted; contact your administrator"),
    "deployment_mismatch": ("授权与当前部署不匹配", "The license belongs to a different deployment"),
    "customer_mismatch": ("授权客户与本部署申请不匹配", "The license customer does not match this deployment"),
    "rollback": ("授权修订号低于已接收版本", "The license revision is older than an accepted revision"),
    "revision_conflict": ("相同修订号对应不同授权文件", "The revision is already associated with a different license"),
    "expired_import": ("不能导入已到期的授权", "An expired license cannot be imported"),
    "missing": ("请先导入有效 License", "Import a valid license first"),
    "expired": ("授权已到期，保留查看、导出及既有网关与防护", "License expired; viewing, exports and existing gateways/protection remain available"),
    "future": ("授权尚未生效", "The license is not yet effective"),
    "clock_rollback": ("检测到系统时间回拨，请校准服务器时间", "Clock rollback detected; correct the server clock"),
    "feature_denied": ("授权未包含此功能模块", "This module is not included in the license"),
    "client_limit": ("已达到注册客户端上限", "The registered client limit has been reached"),
    "identity_locked": ("已导入授权的客户标识不可修改", "The customer identity is locked after importing a license"),
    "unavailable": ("授权状态存储不可用", "License state storage is unavailable"),
}


class LicenseError(RuntimeError):
    def __init__(self, code, **params):
        self.code = "license." + code
        self.params = params
        self.zh, self.en = ERRORS[code]
        super().__init__(self.code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def _unb64(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("base64url")
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(result).rstrip(b"=").decode() != value:
        raise ValueError("base64url")
    return result


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone")
    return parsed.timestamp()


def verify(raw, keys_dir=None):
    """Verify original signed bytes against an independently provisioned key."""
    try:
        if not isinstance(raw, bytes) or len(raw) > MAX_FILE:
            raise ValueError("size")
        envelope = decode_json(raw)
        if not isinstance(envelope, dict) or set(envelope) != {"format", "key_id", "payload", "signature"}:
            raise ValueError("envelope")
        kid = envelope["key_id"]
        if envelope["format"] != "am-license-v1" or not isinstance(kid, str) or not re.fullmatch(r"[0-9a-f]{16}", kid):
            raise ValueError("format")
        directory = Path(keys_dir or os.environ.get("AGENT_MANAGER_LICENSE_KEYS_DIR", ROOT / "deploy/license/public-keys"))
        try:
            public = serialization.load_pem_public_key((directory / f"{kid}.pem").read_bytes())
        except (OSError, ValueError) as exc:
            raise LicenseError("untrusted_key") from exc
        if not isinstance(public, Ed25519PublicKey):
            raise LicenseError("untrusted_key")
        digest = hashlib.sha256(public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()[:16]
        if digest != kid:
            raise LicenseError("untrusted_key")
        public.verify(_unb64(envelope["signature"]), f"am-license-v1.{kid}.{envelope['payload']}".encode("ascii"))
        content = _unb64(envelope["payload"])
        payload = decode_json(content)
        expected = {"schema_version", "product", "customer_id", "customer_name", "deployment_id", "license_id", "revision", "issued_at", "not_before", "expires_at", "features", "limits", "expiry_policy"}
        if not isinstance(payload, dict) or set(payload) != expected or canonical(payload) != content:
            raise ValueError("payload")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["product"] != "agent-manager" or payload["expiry_policy"] != POLICY:
            raise ValueError("product")
        for field in ("customer_id", "deployment_id"):
            if not isinstance(payload[field], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", payload[field]):
                raise ValueError("identity")
        name = payload["customer_name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError("customer")
        if not isinstance(payload["license_id"], str) or not re.fullmatch(r"LIC-[a-f0-9]{32}", payload["license_id"]):
            raise ValueError("license id")
        if type(payload["revision"]) is not int or not 1 <= payload["revision"] <= 2**63 - 1:
            raise ValueError("revision")
        features = payload["features"]
        if not isinstance(features, list) or not features or any(not isinstance(x, str) or x not in FEATURES for x in features) or len(set(features)) != len(features):
            raise ValueError("features")
        limits = payload["limits"]
        if not isinstance(limits, dict) or set(limits) != {"clients"} or type(limits["clients"]) is not int or not 1 <= limits["clients"] <= 1_000_000:
            raise ValueError("limits")
        _time(payload["issued_at"])
        if _time(payload["not_before"]) >= _time(payload["expires_at"]):
            raise ValueError("period")
        return payload, kid, canonical(envelope)
    except LicenseError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidSignature, OverflowError, RecursionError) as exc:
        raise LicenseError("invalid") from exc


class LicenseStore:
    def __init__(self, path=None, keys_dir=None, now=None):
        default = Path(os.environ.get("DATA_DIR", ROOT / "data")) / "license/state.db"
        self.path = Path(path or os.environ.get("AGENT_MANAGER_LICENSE_STATE_PATH", default))
        self.keys_dir = keys_dir
        self.now = now or (lambda: datetime.now(timezone.utc).timestamp())

    @contextmanager
    def connection(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA busy_timeout=30000")
                db.execute("CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), deployment_id TEXT NOT NULL, customer_id TEXT NOT NULL DEFAULT '', customer_name TEXT NOT NULL DEFAULT '', max_seen REAL NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS licenses (revision INTEGER PRIMARY KEY, envelope BLOB NOT NULL, imported_at REAL NOT NULL, actor TEXT NOT NULL)")
                db.execute("INSERT OR IGNORE INTO identity(id,deployment_id,max_seen) VALUES(1,?,?)", ("DEP-" + uuid4().hex, self.now()))
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
        except (OSError, sqlite3.Error) as exc:
            raise LicenseError("unavailable") from exc

    def _state(self, db):
        identity = dict(db.execute("SELECT * FROM identity WHERE id=1").fetchone())
        now = self.now()
        rollback = now < identity["max_seen"] - 300
        effective = max(now, identity["max_seen"])
        db.execute("UPDATE identity SET max_seen=? WHERE id=1", (effective,))
        records = []
        invalid = None
        for row in db.execute("SELECT * FROM licenses ORDER BY revision DESC"):
            try:
                payload, kid, _ = verify(bytes(row["envelope"]), self.keys_dir)
                if payload["revision"] != row["revision"] or payload["deployment_id"] != identity["deployment_id"] or payload["customer_id"] != identity["customer_id"]:
                    raise LicenseError("invalid")
                records.append({**payload, "key_id": kid, "imported_at": row["imported_at"], "imported_by": row["actor"]})
            except LicenseError as exc:
                invalid = exc.code
                break
        current = next((r for r in records if _time(r["not_before"]) <= effective), None)
        pending = [r for r in records if _time(r["not_before"]) > effective and (current is None or r["revision"] > current["revision"])]
        state = "missing" if not records else "future" if current is None else "expired" if effective >= _time(current["expires_at"]) else "valid"
        if invalid:
            state = "invalid"
        elif rollback:
            state = "clock_rollback"
        return {"state": state, "deployment_id": identity["deployment_id"], "customer_id": identity["customer_id"], "customer_name": identity["customer_name"], "current": current, "pending": pending, "history": records, "error_code": invalid, "server_time": now, "highest_revision": max((r["revision"] for r in records), default=0), "expiry_policy": POLICY}

    def status(self):
        with self.connection() as db:
            return self._state(db)

    def request(self, customer_id, customer_name):
        if not isinstance(customer_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", customer_id) or not isinstance(customer_name, str) or not customer_name.strip() or len(customer_name) > 200 or any(ord(c) < 32 for c in customer_name):
            raise LicenseError("invalid")
        with self.connection() as db:
            identity = db.execute("SELECT * FROM identity WHERE id=1").fetchone()
            if db.execute("SELECT 1 FROM licenses LIMIT 1").fetchone() and identity["customer_id"] != customer_id:
                raise LicenseError("identity_locked")
            db.execute("UPDATE identity SET customer_id=?,customer_name=? WHERE id=1", (customer_id, customer_name.strip()))
            return {"schema_version": 1, "product": "agent-manager", "customer_id": customer_id, "customer_name": customer_name.strip(), "deployment_id": identity["deployment_id"]}

    def import_license(self, raw, actor):
        payload, _, encoded = verify(raw, self.keys_dir)
        with self.connection() as db:
            identity = db.execute("SELECT * FROM identity WHERE id=1").fetchone()
            if payload["deployment_id"] != identity["deployment_id"]:
                raise LicenseError("deployment_mismatch")
            if not identity["customer_id"] or payload["customer_id"] != identity["customer_id"]:
                raise LicenseError("customer_mismatch")
            highest = db.execute("SELECT max(revision) FROM licenses").fetchone()[0] or 0
            previous = db.execute("SELECT envelope FROM licenses WHERE revision=?", (payload["revision"],)).fetchone()
            if previous and bytes(previous[0]) == encoded:
                return self._state(db)
            if payload["revision"] < highest:
                raise LicenseError("rollback")
            if previous:
                raise LicenseError("revision_conflict")
            if _time(payload["expires_at"]) <= max(self.now(), identity["max_seen"]):
                raise LicenseError("expired_import")
            db.execute("INSERT INTO licenses VALUES(?,?,?,?)", (payload["revision"], encoded, self.now(), actor))
            return self._state(db)


def require_license(feature=None, *, runtime=False):
    status = LicenseStore().status()
    # The effective signed license continues to authorize existing runtime after expiry.
    if status["state"] not in ({"valid", "expired", "clock_rollback"} if runtime else {"valid"}):
        raise LicenseError(status["state"])
    current = status["current"]
    if not current:
        raise LicenseError("missing")
    if feature and feature not in current["features"]:
        raise LicenseError("feature_denied", feature=feature)
    return current


def scan_allowed():
    try:
        require_license("security_scanning")
        return True
    except LicenseError:
        return False
