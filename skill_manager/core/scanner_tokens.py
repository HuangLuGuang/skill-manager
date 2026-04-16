"""Scanner token storage and validation."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


SCANNER_SCOPES = ["scanner:submit", "scanner:read-own-results", "scanner:read-own-sessions"]
RUNTIME_SCOPES = ["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"]
DEFAULT_SCOPES = list(SCANNER_SCOPES)
ALLOWED_SCOPES = set(SCANNER_SCOPES + RUNTIME_SCOPES)


class ScannerToken(BaseModel):
    id: str
    name: str
    token_prefix: str
    token_hash: str
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))
    status: str = "active"
    expires_at: datetime | None = None
    allowed_ips: list[str] = Field(default_factory=list)
    max_upload_mb: int = 50
    max_concurrent_jobs: int = 2
    created_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"token_hash"})


class ScannerTokenStore:
    def __init__(self, data_dir: str | Path | None = None):
        base = Path(data_dir or os.environ.get("SKILL_MANAGER_DATA_DIR", Path.home() / ".skill-manager"))
        base.mkdir(parents=True, exist_ok=True)
        self.data_dir = base
        self._token_file = base / "scanner_tokens.json"
        self._audit_file = base / "scanner_audit.jsonl"

    def create(
        self,
        name: str,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
        allowed_ips: list[str] | None = None,
        max_upload_mb: int = 50,
        max_concurrent_jobs: int = 2,
        created_by: str | None = None,
    ) -> tuple[ScannerToken, str]:
        plain = "smsc_live_" + secrets.token_urlsafe(32)
        token = ScannerToken(
            id=str(uuid.uuid4()),
            name=name.strip(),
            token_prefix=plain[:18],
            token_hash=self._hash(plain),
            scopes=_normalize_scopes(scopes or list(DEFAULT_SCOPES)),
            expires_at=expires_at,
            allowed_ips=allowed_ips or [],
            max_upload_mb=max_upload_mb,
            max_concurrent_jobs=max_concurrent_jobs,
            created_by=created_by,
        )
        tokens = self._load()
        tokens.append(token)
        self._save(tokens)
        self.log_event("scanner_token_created", token, actor=created_by)
        return token, plain

    def list(self) -> list[ScannerToken]:
        return sorted(self._load(), key=lambda item: item.created_at, reverse=True)

    def revoke(self, token_id: str, actor: str | None = None) -> ScannerToken:
        tokens = self._load()
        for index, token in enumerate(tokens):
            if token.id == token_id:
                token.status = "revoked"
                token.revoked_at = datetime.now(timezone.utc)
                token.revoked_by = actor
                tokens[index] = token
                self._save(tokens)
                self.log_event("scanner_token_revoked", token, actor=actor)
                return token
        raise KeyError(token_id)

    def validate(self, plain: str, required_scope: str, client_ip: str | None = None) -> ScannerToken:
        token_hash = self._hash(plain)
        now = datetime.now(timezone.utc)
        tokens = self._load()
        for index, token in enumerate(tokens):
            if not hmac.compare_digest(token.token_hash, token_hash):
                continue
            if token.status != "active":
                raise PermissionError("scanner token is not active")
            if token.expires_at and token.expires_at < now:
                raise PermissionError("scanner token expired")
            if required_scope not in token.scopes:
                raise PermissionError(f"scanner token missing scope: {required_scope}")
            if token.allowed_ips and not _ip_allowed(client_ip, token.allowed_ips):
                raise PermissionError("scanner token is not allowed from this IP")
            token.last_used_at = now
            tokens[index] = token
            self._save(tokens)
            self.log_event("scanner_token_used", token, details={"scope": required_scope, "client_ip": client_ip})
            return token
        raise PermissionError("invalid scanner token")

    def log_event(
        self,
        event_type: str,
        token: ScannerToken | None = None,
        actor: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "token_id": token.id if token else None,
            "token_name": token.name if token else None,
            "token_prefix": token.token_prefix if token else None,
            "details": details or {},
        }
        with open(self._audit_file, "a") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load(self) -> list[ScannerToken]:
        if not self._token_file.exists():
            return []
        raw = json.loads(self._token_file.read_text())
        return [ScannerToken.model_validate(item) for item in raw]

    def _save(self, tokens: list[ScannerToken]) -> None:
        payload = [token.model_dump(mode="json") for token in tokens]
        self._token_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _hash(self, plain: str) -> str:
        pepper = os.environ.get("SKILL_MANAGER_SCANNER_TOKEN_PEPPER", "")
        return hashlib.sha256((pepper + plain).encode("utf-8")).hexdigest()


def _ip_allowed(client_ip: str | None, allowed: list[str]) -> bool:
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for item in allowed:
        raw = item.strip()
        if not raw:
            continue
        try:
            if "/" in raw:
                if ip in ipaddress.ip_network(raw, strict=False):
                    return True
            elif ip == ipaddress.ip_address(raw):
                return True
        except ValueError:
            continue
    return False


def _normalize_scopes(scopes: list[str]) -> list[str]:
    result: list[str] = []
    for scope in scopes:
        value = str(scope).strip()
        if not value:
            continue
        if value not in ALLOWED_SCOPES:
            raise ValueError(f"unsupported token scope: {value}")
        if value not in result:
            result.append(value)
    return result
