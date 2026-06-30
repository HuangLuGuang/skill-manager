import argparse
import importlib.util
from pathlib import Path


def _load_verifier():
    path = (
        Path(__file__).resolve().parents[1]
        / "demo"
        / "agent-manager-skill-verifier"
        / "skills"
        / "agent-manager-skill-verifier"
        / "scripts"
        / "agent_manager_skill_verifier.py"
    )
    spec = importlib.util.spec_from_file_location("agent_manager_skill_verifier", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_verifier_prefers_specific_env(monkeypatch):
    verifier = _load_verifier()
    args = argparse.Namespace(server=None, token=None)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://verifier.example")
    monkeypatch.setenv("AGENT_MANAGER_BASE_URL", "http://legacy.example")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "verifier-token")

    assert verifier.resolve_server(args) == "http://verifier.example"
    assert verifier.resolve_token(args) == "verifier-token"
