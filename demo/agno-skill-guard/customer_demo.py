from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from main import (
    AgentManagerRuntimeClient,
    build_agent,
    compute_local_signature,
    ensure_skill_can_load,
    make_skill_runtime_hook,
    run_demo,
    staged_skills_root,
)


ROOT = Path(__file__).resolve().parent
SAMPLE_SKILLS = ROOT / "sample_skills"
DEFAULT_BASE_URL = os.getenv("AGENT_MANAGER_BASE_URL", "http://127.0.0.1:8080")


def log_step(message: str) -> None:
    print(f"\n[Demo] {message}")


def print_json_or_text(value: object) -> None:
    if isinstance(value, BaseModel):
        print(value.model_dump_json(indent=2, ensure_ascii=False))
        return
    print(value)


def approved_skill(base_url: str, agent_id: str) -> None:
    skill_name = "approved-helper"
    skill_path = SAMPLE_SKILLS / skill_name
    question = (
        "请使用 approved-helper skill 的内容，用客户能听懂的话解释："
        "Agent Manager 如何保护 Agno 加载本地 skill？"
    )

    log_step("1. Agno Agent 准备加载安全 skill")
    print(f"skill_name={skill_name}")
    print(f"skill_path={skill_path}")

    log_step("2. 本地计算 skill 内容签名")
    print(compute_local_signature(skill_path))

    log_step("3. 调用 Agent Manager 验签 + can-load，通过后创建真实 Agno Agent")
    answer = run_demo(
        skill_name=skill_name,
        skill_path=skill_path,
        question=question,
        base_url=base_url,
        agent_id=agent_id,
    )

    log_step("4. Agno Agent 输出")
    print_json_or_text(answer)


def rejected_skill(base_url: str, agent_id: str) -> None:
    skill_name = "rejected-exfiltrator"
    skill_path = SAMPLE_SKILLS / skill_name

    log_step("1. Agno Agent 尝试加载恶意 skill")
    print(f"skill_name={skill_name}")
    print(f"skill_path={skill_path}")

    log_step("2. 加载前调用 Agent Manager runtime 校验")
    try:
        run_demo(
            skill_name=skill_name,
            skill_path=skill_path,
            question="请解释这个 skill 是否可以安全加载。",
            base_url=base_url,
            agent_id=agent_id,
        )
    except Exception as exc:
        log_step("3. 预期阻断")
        print(str(exc))
        return
    raise RuntimeError("Expected rejected skill to be blocked, but it loaded successfully")


def tampered_skill(base_url: str, agent_id: str) -> None:
    skill_name = "approved-helper"
    source_path = SAMPLE_SKILLS / skill_name

    with tempfile.TemporaryDirectory(prefix="agno-tampered-skill-") as temp_dir:
        tampered_path = Path(temp_dir) / skill_name
        shutil.copytree(source_path, tampered_path)
        with open(tampered_path / "SKILL.md", "a", encoding="utf-8") as file:
            file.write("\n\n<!-- tampered locally after approval -->\n")

        log_step("1. 本地 skill 已被篡改")
        print(f"original_path={source_path}")
        print(f"tampered_path={tampered_path}")

        log_step("2. Agno Agent 计算篡改后签名并提交给 Agent Manager")
        print(compute_local_signature(tampered_path))

        try:
            run_demo(
                skill_name=skill_name,
                skill_path=tampered_path,
                question="请解释这个 skill 是否可以安全加载。",
                base_url=base_url,
                agent_id=agent_id,
            )
        except Exception as exc:
            log_step("3. 预期阻断：签名不匹配")
            print(str(exc))
            return
        raise RuntimeError("Expected tampered skill to be blocked, but it loaded successfully")


def tool_blocked(base_url: str, agent_id: str) -> None:
    skill_name = "read-only-script"
    skill_path = SAMPLE_SKILLS / skill_name
    client = AgentManagerRuntimeClient(
        base_url=base_url,
        token=os.getenv("AGENT_MANAGER_API_TOKEN") or os.getenv("AGENT_MANAGER_ACCESS_TOKEN"),
    )

    log_step("1. 加载前验签 + can-load")
    verification = ensure_skill_can_load(
        client=client,
        skill_name=skill_name,
        skill_path=skill_path,
        agent_id=agent_id,
    )
    print(verification.model_dump_json(indent=2, ensure_ascii=False))

    log_step("2. 创建真实 Agno Agent + LocalSkills")
    with staged_skills_root(skill_name, skill_path) as skills_root:
        if not os.getenv("AGNO_API_KEY") and not os.getenv("DEEPSEEK_API_KEY"):
            # This scenario does not call the model, but Agno still constructs a model object.
            os.environ["AGNO_API_KEY"] = "demo-not-used"
        _agent = build_agent(
            client=client,
            skill_name=skill_name,
            skills_root=skills_root,
            agent_id=agent_id,
        )
        print(f"Agno Agent created with LocalSkills root: {skills_root}")

        log_step("3. 调用同一个 Agno tool_hook 模拟 get_skill_script(..., execute=True)")
        hook = make_skill_runtime_hook(client, skill_name, agent_id)
        try:
            hook(
                "get_skill_script",
                lambda **kwargs: "script executed unexpectedly",
                {"skill_name": skill_name, "script_name": "maintenance.py", "execute": True},
            )
        except PermissionError as exc:
            log_step("4. 预期阻断：Bash 未在 allowed-tools 中声明")
            print(str(exc))
            return
        raise RuntimeError("Expected Bash tool call to be blocked, but it was allowed")


def all_scenarios(base_url: str, agent_id: str) -> None:
    scenarios: list[tuple[str, Callable[[str, str], None]]] = [
        ("approved", approved_skill),
        ("rejected", rejected_skill),
        ("tampered", tampered_skill),
        ("tool-blocked", tool_blocked),
    ]
    for name, fn in scenarios:
        print("\n" + "=" * 80)
        print(f"Scenario: {name}")
        print("=" * 80)
        fn(base_url, f"{agent_id}-{name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Closed-loop Agno + Agent Manager customer demo")
    parser.add_argument(
        "scenario",
        choices=["approved", "rejected", "tampered", "tool-blocked", "all"],
        help="Demo scenario to run",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--agent-id", default=os.getenv("AGENT_ID", "agno-customer-demo"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mapping: dict[str, Callable[[str, str], None]] = {
        "approved": approved_skill,
        "rejected": rejected_skill,
        "tampered": tampered_skill,
        "tool-blocked": tool_blocked,
    }
    if args.scenario == "all":
        all_scenarios(args.base_url, args.agent_id)
        return
    mapping[args.scenario](args.base_url, args.agent_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[Demo failed] {exc}", file=sys.stderr)
        raise
