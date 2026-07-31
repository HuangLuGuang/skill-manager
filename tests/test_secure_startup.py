import pytest

from backend.config import Settings
from backend.security import initialize_signing_identity, validate_security_settings


def test_secure_startup_rejects_default_secret(monkeypatch):
    settings = Settings(ENFORCE_SECURE_STARTUP=True, SECRET_KEY="change-me-in-production")
    monkeypatch.setenv("AGENT_MANAGER_SANDBOX_API_KEY", "sandbox-key-with-enough-entropy")
    monkeypatch.setenv("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", "/tmp/not-used.pem")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_security_settings(settings)


def test_secure_startup_requires_sandbox_key(monkeypatch):
    settings = Settings(ENFORCE_SECURE_STARTUP=True, SECRET_KEY="s" * 32)
    monkeypatch.delenv("AGENT_MANAGER_SANDBOX_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SANDBOX_API_KEY"):
        validate_security_settings(settings)


def test_secure_startup_requires_preprovisioned_ed25519_identity(tmp_path, monkeypatch):
    private_key_path = tmp_path / "signing" / "skill-ed25519.pem"
    settings = Settings(ENFORCE_SECURE_STARTUP=True, SECRET_KEY="s" * 32)
    monkeypatch.setenv("AGENT_MANAGER_SANDBOX_API_KEY", "sandbox-key-with-enough-entropy")
    monkeypatch.setenv("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", str(private_key_path))

    with pytest.raises(RuntimeError, match="not initialized"):
        validate_security_settings(settings)


def test_local_startup_initializes_ed25519_identity(tmp_path, monkeypatch):
    private_key_path = tmp_path / "signing" / "skill-ed25519.pem"
    monkeypatch.setenv("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", str(private_key_path))

    initialize_signing_identity()

    assert private_key_path.exists()
    assert private_key_path.stat().st_mode & 0o777 == 0o600
