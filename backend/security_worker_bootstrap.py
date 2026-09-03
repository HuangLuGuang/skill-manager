"""Bootstrap the built-in Agent Security Worker from an environment token."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .config import Settings
from .security_audit import append_security_audit
from .security_scan_controls import hash_value, json_dumps

logger = logging.getLogger(__name__)

BUILTIN_WORKER_NAME = "builtin-security-worker"
BUILTIN_WORKER_CREATED_BY = "system:environment"
BUILTIN_WORKER_CAPABILITIES = (
    "control_plane_validation",
    "agent_risk_scan",
    "mcp_risk_scan",
    "llm_redteam_scan",
    "ai_infrastructure_vulnerability_scan",
    "dify_asset_inventory",
)
BUILTIN_WORKER_MAX_CONCURRENCY = 1
_TOKEN_PATTERN = re.compile(r"^amsw_[A-Za-z0-9._~-]{32,}$")


class SecurityWorkerBootstrapError(RuntimeError):
    """Raised when the configured built-in identity cannot be initialized safely."""


@dataclass(frozen=True)
class SecurityWorkerBootstrapResult:
    action: str
    worker_id: str | None = None


def _stable_worker_id() -> str:
    digest = hashlib.sha256(BUILTIN_WORKER_NAME.encode("utf-8")).hexdigest()[:32]
    return f"asw_builtin_{digest}"


def _configured_token(settings: Settings) -> str | None:
    token = settings.AGENT_SECURITY_WORKER_TOKEN or ""
    if not token.strip():
        return None
    if token != token.strip():
        raise SecurityWorkerBootstrapError(
            "AGENT_SECURITY_WORKER_TOKEN must not contain leading or trailing whitespace"
        )
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise SecurityWorkerBootstrapError(
            "AGENT_SECURITY_WORKER_TOKEN must start with amsw_ and contain at least "
            "32 URL-safe characters after the prefix"
        )
    return token


def _audit(db: Session, *, event_type: str, worker_id: str, action: str) -> None:
    append_security_audit(
        event_type=event_type,
        actor=BUILTIN_WORKER_CREATED_BY,
        resource_type="security_scan_worker",
        resource_id=worker_id,
        action=action,
        outcome="success",
        details={"source": "environment"},
        bind=db.get_bind(),
    )


def _require_managed_identity(row: models.SecurityScanWorker) -> None:
    if row.created_by != BUILTIN_WORKER_CREATED_BY:
        raise SecurityWorkerBootstrapError(
            f"cannot bootstrap {BUILTIN_WORKER_NAME}: the name belongs to a manually created worker"
        )


def _create_worker(db: Session, token: str) -> SecurityWorkerBootstrapResult:
    worker_id = _stable_worker_id()
    row = models.SecurityScanWorker(
        worker_id=worker_id,
        name=BUILTIN_WORKER_NAME,
        token_hash=hash_value(token),
        token_prefix=token[:12],
        status="active",
        capabilities_json=json_dumps(list(BUILTIN_WORKER_CAPABILITIES)),
        max_concurrency=BUILTIN_WORKER_MAX_CONCURRENCY,
        created_by=BUILTIN_WORKER_CREATED_BY,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = (
            db.query(models.SecurityScanWorker)
            .filter(models.SecurityScanWorker.name == BUILTIN_WORKER_NAME)
            .first()
        )
        if concurrent is None:
            raise SecurityWorkerBootstrapError(
                "cannot bootstrap the built-in security worker because its token is already assigned"
            ) from exc
        _require_managed_identity(concurrent)
        if concurrent.token_hash != hash_value(token):
            raise SecurityWorkerBootstrapError(
                "concurrent Backend instances use different built-in security worker tokens"
            ) from exc
        return SecurityWorkerBootstrapResult("unchanged", concurrent.worker_id)
    _audit(db, event_type="security_scan_worker.created", worker_id=worker_id, action="create")
    return SecurityWorkerBootstrapResult("created", worker_id)


def _rotate_worker(
    db: Session,
    row: models.SecurityScanWorker,
    token: str,
) -> SecurityWorkerBootstrapResult:
    worker_id = row.worker_id
    previous_hash = row.token_hash
    desired_hash = hash_value(token)
    updated = (
        db.query(models.SecurityScanWorker)
        .filter(
            models.SecurityScanWorker.worker_id == worker_id,
            models.SecurityScanWorker.created_by == BUILTIN_WORKER_CREATED_BY,
            models.SecurityScanWorker.token_hash == previous_hash,
        )
        .update(
            {
                models.SecurityScanWorker.token_hash: desired_hash,
                models.SecurityScanWorker.token_prefix: token[:12],
                models.SecurityScanWorker.status: "active",
                models.SecurityScanWorker.capabilities_json: json_dumps(list(BUILTIN_WORKER_CAPABILITIES)),
                models.SecurityScanWorker.max_concurrency: BUILTIN_WORKER_MAX_CONCURRENCY,
                models.SecurityScanWorker.public_key_algorithm: None,
                models.SecurityScanWorker.public_key: None,
                models.SecurityScanWorker.public_key_fingerprint: None,
                models.SecurityScanWorker.public_key_registered_at: None,
                models.SecurityScanWorker.last_heartbeat_at: None,
                models.SecurityScanWorker.revoked_at: None,
                models.SecurityScanWorker.revoked_by: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated == 0:
        db.expire_all()
        current = (
            db.query(models.SecurityScanWorker)
            .filter(models.SecurityScanWorker.worker_id == worker_id)
            .first()
        )
        if current and current.created_by == BUILTIN_WORKER_CREATED_BY and current.token_hash == desired_hash:
            return SecurityWorkerBootstrapResult("unchanged", current.worker_id)
        raise SecurityWorkerBootstrapError(
            "concurrent Backend instances use different built-in security worker tokens"
        )
    _audit(db, event_type="security_scan_worker.token_rotated", worker_id=worker_id, action="rotate")
    return SecurityWorkerBootstrapResult("rotated", worker_id)


def bootstrap_builtin_security_worker(
    db: Session,
    settings: Settings,
) -> SecurityWorkerBootstrapResult:
    """Create or rotate the environment-managed Worker without exposing its token."""

    token = _configured_token(settings)
    if token is None:
        return SecurityWorkerBootstrapResult("disabled")
    row = (
        db.query(models.SecurityScanWorker)
        .filter(models.SecurityScanWorker.name == BUILTIN_WORKER_NAME)
        .first()
    )
    if row is None:
        return _create_worker(db, token)
    _require_managed_identity(row)
    if row.token_hash == hash_value(token):
        if row.status == "revoked":
            return SecurityWorkerBootstrapResult("revoked", row.worker_id)
        return SecurityWorkerBootstrapResult("unchanged", row.worker_id)
    return _rotate_worker(db, row, token)


def bootstrap_builtin_security_worker_once(settings: Settings, session_factory) -> SecurityWorkerBootstrapResult:
    db = session_factory()
    try:
        result = bootstrap_builtin_security_worker(db, settings)
    finally:
        db.close()
    if result.action == "disabled":
        logger.info("Built-in Agent Security Worker is disabled because no environment token is configured")
    elif result.action == "created":
        logger.info("Built-in Agent Security Worker was registered: %s", result.worker_id)
    elif result.action == "rotated":
        logger.info("Built-in Agent Security Worker credentials were rotated: %s", result.worker_id)
    elif result.action == "revoked":
        logger.warning(
            "Built-in Agent Security Worker remains revoked; configure a new token to rotate and reactivate it"
        )
    return result
