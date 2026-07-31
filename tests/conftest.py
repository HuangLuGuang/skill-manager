import pytest


@pytest.fixture(autouse=True)
def isolate_signing_identity(tmp_path, monkeypatch):
    """Give every test an isolated server signing identity."""
    monkeypatch.setenv(
        "AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH",
        str(tmp_path / ".git" / "test-signing" / "skill-ed25519.pem"),
    )
    monkeypatch.delenv("AGENT_MANAGER_SIGNING_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("AGENT_MANAGER_SIGNING_PUBLIC_KEY_PATH", raising=False)
    from agent_manager.core.signer import ensure_signing_key

    ensure_signing_key()
