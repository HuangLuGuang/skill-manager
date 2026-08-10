from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import LocalSkills, Skills
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (  # noqa: E402
    AgentManagerRuntimeClient,
    ensure_skill_can_load,
    make_skill_runtime_hook,
    staged_skills_root,
)


SKILL_NAME = "travel-expense-calculator"
DEFAULT_SKILL_PATH = ROOT / "sample_skills" / SKILL_NAME
DEFAULT_QUESTION = (
    "我去上海出差3天2晚，酒店花了1280元，高铁票553元，"
    "市内交通260元，最多可以报销多少钱？"
)


class ExpenseItem(BaseModel):
    name: str
    reimbursable_amount: float
    personal_amount: float
    reason: str


class ExpenseAnswer(BaseModel):
    policy_version: str
    reimbursable_total: float
    employee_paid_total: float
    items: list[ExpenseItem] = Field(default_factory=list)
    explanation: str
    security_evidence: list[str] = Field(default_factory=list)


def runtime_client(base_url: str) -> AgentManagerRuntimeClient:
    return AgentManagerRuntimeClient(
        base_url=base_url,
        token=os.getenv("AGENT_MANAGER_API_TOKEN") or os.getenv("AGENT_MANAGER_ACCESS_TOKEN"),
    )


def execute_governed_calculator(
    client: AgentManagerRuntimeClient,
    skill_path: Path,
    agent_id: str,
) -> dict[str, Any]:
    check = client.check_tool(skill_name=SKILL_NAME, tool_name="Bash", agent_id=agent_id)
    if not check.allowed:
        raise PermissionError(f"Agent Manager 已阻止 Skill {SKILL_NAME!r} 使用工具 'Bash'")

    script_path = skill_path / "scripts" / "calculate.py"
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=skill_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"差旅报销计算失败：{completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("差旅报销计算器返回的 JSON 结果不是对象")
    return payload


def build_expense_agent(
    *,
    client: AgentManagerRuntimeClient,
    skills_root: Path,
    agent_id: str,
    skill_version_id: str | None,
) -> Agent:
    model_base_url = os.getenv("AGNO_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    model_id = os.getenv("AGNO_MODEL_ID", "deepseek-chat")
    model_api_key = os.getenv("AGNO_API_KEY")
    if not model_api_key:
        raise ValueError("必须配置 AGNO_API_KEY，并使用 Agent Manager 模型调用凭证")

    metadata = {"agent_manager_skill_name": SKILL_NAME}
    if skill_version_id:
        metadata["agent_manager_skill_version_id"] = skill_version_id

    return Agent(
        name="差旅报销演示 Agent",
        model=OpenAIChat(
            id=model_id,
            base_url=model_base_url,
            api_key=model_api_key,
            metadata=metadata,
            role_map={
                "system": "system",
                "developer": "system",
                "user": "user",
                "assistant": "assistant",
                "tool": "tool",
                "model": "assistant",
            },
            supports_native_structured_outputs=False,
        ),
        skills=Skills(loaders=[LocalSkills(str(skills_root))]),
        tool_hooks=[make_skill_runtime_hook(client, SKILL_NAME, agent_id)],
        output_schema=ExpenseAnswer,
        markdown=True,
        instructions=[
            "你是企业差旅报销助手，必须使用简体中文。",
            "计算结果已经由受治理的确定性脚本生成，不得修改任何金额。",
            "按计算结果解释每个项目，并明确说明这是演示制度，不是正式财务审批。",
            "security_evidence 必须说明 Skill 已验签、已通过 can-load、Bash 权限已检查、模型请求经过网关。",
        ],
    )


def run_demo(*, base_url: str, agent_id: str, skill_path: Path, question: str) -> ExpenseAnswer | BaseModel | str:
    client = runtime_client(base_url)
    verification = ensure_skill_can_load(
        client=client,
        skill_name=SKILL_NAME,
        skill_path=skill_path,
        agent_id=agent_id,
    )
    calculation = execute_governed_calculator(client, skill_path, agent_id)

    with staged_skills_root(SKILL_NAME, skill_path) as skills_root:
        agent = build_expense_agent(
            client=client,
            skills_root=skills_root,
            agent_id=agent_id,
            skill_version_id=verification.skill_id,
        )
        prompt = (
            f"用户问题：{question}\n"
            f"已验证的计算结果：{json.dumps(calculation, ensure_ascii=False)}\n"
            f"Skill Registry 状态：{verification.status or 'unknown'}\n"
            f"Skill 风险等级：{verification.risk_level or 'unknown'}\n"
            "请严格基于已验证的计算结果输出结构化答复。"
        )
        return agent.run(prompt).content


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过 Agent Manager 模型网关演示差旅报销 Skill")
    parser.add_argument("--base-url", default=os.getenv("AGENT_MANAGER_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--agent-id", default=os.getenv("AGENT_ID", "expense-gateway-demo"))
    parser.add_argument("--skill-path", type=Path, default=DEFAULT_SKILL_PATH)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_demo(
        base_url=args.base_url,
        agent_id=args.agent_id,
        skill_path=args.skill_path.expanduser().resolve(),
        question=args.question,
    )
    if isinstance(result, BaseModel):
        print(result.model_dump_json(indent=2, ensure_ascii=False))
    else:
        print(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"差旅报销网关演示失败：{exc}", file=sys.stderr)
        raise
