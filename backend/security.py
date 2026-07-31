import os

from .config import Settings


def validate_security_settings(settings: Settings) -> None:
    """Reject insecure production configuration before the service starts."""
    if not settings.ENFORCE_SECURE_STARTUP:
        return
    secret_key = settings.SECRET_KEY.strip()
    if secret_key == "change-me-in-production" or len(secret_key) < 32:
        raise RuntimeError("secure startup requires a non-default SECRET_KEY with at least 32 characters")
    sandbox_key = os.environ.get("AGENT_MANAGER_SANDBOX_API_KEY", "").strip()
    if not sandbox_key or sandbox_key in {"sandbox-change-me", "change-me"}:
        raise RuntimeError("secure startup requires a non-placeholder AGENT_MANAGER_SANDBOX_API_KEY")
    signing_key_path = os.environ.get("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", "").strip()
    if not signing_key_path:
        raise RuntimeError("secure startup requires AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH")
    from agent_manager.core.signer import validate_signing_key

    validate_signing_key()


def initialize_signing_identity(*, allow_create: bool = True) -> None:
    """Initialize the server signing identity during process startup."""
    from agent_manager.core.signer import ensure_signing_key, validate_signing_key

    if allow_create:
        ensure_signing_key()
    else:
        validate_signing_key()
