import pytest


@pytest.fixture(autouse=True)
def licensed_deployment(tmp_path, monkeypatch):
    """Existing behavioral tests run with a genuine signed, isolated entitlement.

    License-specific tests replace this state to exercise failures and expiry.
    No production authorization function is mocked or disabled.
    """
    from tests.license_factory import TestLicenseIssuer
    issuer = TestLicenseIssuer(tmp_path / 'license', monkeypatch)
    issuer.install()
    return issuer


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
