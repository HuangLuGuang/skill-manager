import json

from agent_manager.core.llm import LLMConfig, generate_sandbox_probes_with_llm


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
