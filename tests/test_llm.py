import json

from agent_manager.core.llm import LLMConfig, _build_skill_snapshot, generate_sandbox_probes_with_llm


def test_generate_sandbox_probes_accepts_entrypoint_from_skill_md(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: doc-driven
description: test
---

Run:

```bash
python tools/check.py --target /tmp/input.txt --dry-run
```
""",
        encoding="utf-8",
    )
    (skill_dir / "tools").mkdir()
    (skill_dir / "tools" / "check.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            content = json.dumps({
                "probes": [{
                    "name": "skill-md-command",
                    "description": "from SKILL.md usage example",
                    "entrypoint": "tools/check.py",
                    "args": ["--target", "/tmp/input.txt", "--dry-run"],
                }],
            })
            return {"choices": [{"message": {"content": content}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("agent_manager.core.llm.httpx.Client", FakeClient)

    plan = generate_sandbox_probes_with_llm(
        skill_dir,
        "scripts/run.py",
        LLMConfig(enabled=True, api_key="test-key"),
    )

    assert len(plan.probes) == 1
    assert plan.probes[0].entrypoint == "tools/check.py"
    assert plan.probes[0].args == ["--target", "/tmp/input.txt", "--dry-run"]


def test_skill_snapshot_tolerates_non_utf8_manifest(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(
        b"# Social Media Marketing\r\n\r\n"
        b"Copy with Windows dash \x97 should not abort LLM analysis.\r\n"
    )

    snapshot = _build_skill_snapshot(skill_dir, LLMConfig())

    assert "Social Media Marketing" in snapshot
    assert "should not abort LLM analysis" in snapshot


def test_internal_gateway_enforces_ai_timeout(monkeypatch):
    """内部网关超时须取消模型协程，不继续等待供应商。"""
    import asyncio
    import pytest
    from agent_manager.core import llm

    cancelled = []
    async def slow_provider(*args, **kwargs):
        try:
            await asyncio.sleep(1)
            return {"choices": [{"message": {"content": '{"risk_level": "benign"}'}}]}
        finally:
            cancelled.append(True)
    monkeypatch.delenv("AGENT_MANAGER_LLM_GATEWAY_URL", raising=False)
    monkeypatch.setattr(llm, "_call_model_gateway_upstream", slow_provider)
    config = LLMConfig(enabled=True, provider="model-gateway", timeout_seconds=0.02)
    with pytest.raises(TimeoutError, match="AI analysis timed out"):
        llm._call_llm(config, "system", "user")
    assert cancelled == [True]


def test_analysis_budget_includes_preparation_and_result_processing(monkeypatch):
    import pytest
    from agent_manager.core import llm

    now = [100.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    config = LLMConfig(timeout_seconds=5)
    with llm.llm_analysis_timeout(config):
        now[0] += 2
        assert llm._remaining_timeout(config) == 3
    with pytest.raises(llm.LLMAnalysisTimeout):
        with llm.llm_analysis_timeout(config):
            now[0] += 6
    assert llm._remaining_timeout(config) == 5


def test_expired_preparation_does_not_start_model(monkeypatch):
    import pytest
    from unittest.mock import Mock
    from agent_manager.core import llm

    now = [0.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    model = Mock()
    monkeypatch.setattr(llm, "_call_model_gateway_sync", model)
    config = LLMConfig(provider="model-gateway", timeout_seconds=5)
    with pytest.raises(llm.LLMAnalysisTimeout):
        with llm.llm_analysis_timeout(config):
            now[0] = 6
            llm._call_llm(config, "system", "user")
    model.assert_not_called()


def test_provider_timeout_retains_original_reason(monkeypatch):
    import httpx
    import pytest
    from agent_manager.core import llm

    async def fail(*args, **kwargs):
        raise httpx.ReadTimeout("provider request timed out")
    monkeypatch.delenv("AGENT_MANAGER_LLM_GATEWAY_URL", raising=False)
    monkeypatch.setattr(llm, "_call_model_gateway_upstream", fail)
    with pytest.raises(httpx.ReadTimeout, match="provider request timed out"):
        llm._call_llm(LLMConfig(provider="model-gateway", timeout_seconds=5), "system", "user")


def test_ai_timeout_cancels_direct_and_environment_gateway_requests(monkeypatch):
    import asyncio
    import pytest
    from agent_manager.core import llm

    closed = []
    class SlowClient:
        def __init__(self, **kwargs):
            assert 0 < kwargs['timeout'] <= 0.02
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            closed.append(True)
        async def post(self, *args, **kwargs):
            await asyncio.sleep(1)
    monkeypatch.setattr(llm.httpx, 'AsyncClient', SlowClient)
    for gateway in ['', 'http://gateway.test/v1/chat/completions']:
        monkeypatch.setenv('AGENT_MANAGER_LLM_GATEWAY_URL', gateway)
        with pytest.raises(llm.LLMAnalysisTimeout):
            llm._call_llm(LLMConfig(api_key='test', timeout_seconds=0.02), 'system', 'user')
    assert closed == [True, True]
