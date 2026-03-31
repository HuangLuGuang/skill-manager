from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import LocalSkills, Skills
from pydantic import BaseModel, Field


class SkillVerificationResult(BaseModel):
    allowed: bool
    reason: str
    skill_id: str | None = None
    skill_name: str
    status: str | None = None
    risk_level: str | None = None
    signature_match: bool = False


class SkillLoadResult(BaseModel):
    allowed: bool
    reason: str
    status: str | None = None
    risk_level: str | None = None


class ToolCheckResult(BaseModel):
    allowed: bool
    skill_name: str
    tool_name: str


class AgentAnswer(BaseModel):
    summary: str = Field(description="对 skill 的简要说明")
    security_decision: str = Field(description="说明该 skill 当前是否允许被加载，以及为什么")
    evidence: list[str] = Field(default_factory=list, description="支撑判断的关键信息")


class SkillManagerRuntimeClient:
    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def verify_skill_signature(
        self,
        skill_name: str,
        local_signature: str,
        agent_id: str,
        skill_id: str | None = None,
    ) -> SkillVerificationResult:
        response = self.http.post(
            "/api/v1/runtime/verify-skill-signature",
            json={
                "skill_name": skill_name,
                "skill_id": skill_id,
                "local_signature": local_signature,
                "agent_id": agent_id,
            },
        )
        response.raise_for_status()
        return SkillVerificationResult.model_validate(response.json())

    def can_load(self, skill_name: str, agent_id: str) -> SkillLoadResult:
        response = self.http.get(
            f"/api/v1/runtime/can-load/{skill_name}",
            params={"agent_id": agent_id},
        )
        response.raise_for_status()
        return SkillLoadResult.model_validate(response.json())

    def check_tool(self, skill_name: str, tool_name: str, agent_id: str) -> ToolCheckResult:
        response = self.http.get(
            "/api/v1/runtime/check-tool",
            params={"skill_name": skill_name, "tool_name": tool_name, "agent_id": agent_id},
        )
        response.raise_for_status()
        return ToolCheckResult.model_validate(response.json())


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_local_signature(skill_path: str | Path, signing_key: str | None = None) -> str:
    root = Path(skill_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Skill path is not a directory: {root}")

    parts: list[str] = []
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(root).as_posix()
            parts.append(f"{rel}:{file_sha256(file_path)}\n")

    content = "".join(parts).encode()
    if signing_key:
        return hmac.new(signing_key.encode(), content, hashlib.sha256).hexdigest()
    return hashlib.sha256(content).hexdigest()


def ensure_skill_can_load(
    client: SkillManagerRuntimeClient,
    skill_name: str,
    skill_path: Path,
    agent_id: str,
    skill_id: str | None = None,
) -> SkillVerificationResult:
    local_signature = compute_local_signature(
        skill_path,
        signing_key=os.getenv("SKILL_MANAGER_SIGNING_KEY"),
    )

    verify_result = client.verify_skill_signature(
        skill_name=skill_name,
        skill_id=skill_id,
        local_signature=local_signature,
        agent_id=agent_id,
    )
    if not verify_result.allowed:
        raise RuntimeError(f"Signature verification failed: {verify_result.reason}")

    load_result = client.can_load(skill_name=skill_name, agent_id=agent_id)
    if not load_result.allowed:
        raise RuntimeError(f"Runtime can-load rejected the skill: {load_result.reason}")

    return verify_result


@contextmanager
def staged_skills_root(skill_name: str, skill_path: Path):
    """
    Agno LocalSkills expects a root directory whose children are skill folders.
    Stage the target skill under a temporary root using the registry name.
    """
    with tempfile.TemporaryDirectory(prefix="agno-skill-root-") as temp_dir:
        skills_root = Path(temp_dir) / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        target = skills_root / skill_name
        try:
            os.symlink(skill_path, target, target_is_directory=True)
        except OSError:
            shutil.copytree(skill_path, target)
        yield skills_root


def map_agno_function_to_runtime_tool(function_name: str, args: dict) -> str | None:
    if function_name in {"get_skill_instructions", "get_skill_reference"}:
        return "Read"
    if function_name == "get_skill_script":
        execute = bool(args.get("execute"))
        return "Bash" if execute else "Read"
    return None


def make_skill_runtime_hook(client: SkillManagerRuntimeClient, skill_name: str, agent_id: str):
    def skill_runtime_hook(function_name: str, func: callable, args: dict):
        runtime_tool_name = map_agno_function_to_runtime_tool(function_name, args)
        if runtime_tool_name:
            check = client.check_tool(skill_name=skill_name, tool_name=runtime_tool_name, agent_id=agent_id)
            if not check.allowed:
                raise PermissionError(
                    f"Skill Manager blocked tool {runtime_tool_name!r} for skill {skill_name!r}"
                )
        return func(**args)

    return skill_runtime_hook


def build_agent(
    client: SkillManagerRuntimeClient,
    skill_name: str,
    skills_root: Path,
    agent_id: str,
) -> Agent:
    model_id = os.getenv("AGNO_MODEL_ID", "deepseek-chat")
    model_base_url = os.getenv("AGNO_MODEL_BASE_URL", "https://api.deepseek.com")
    model_api_key = os.getenv("AGNO_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    deepseek_role_map = {
        "system": "system",
        "developer": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }
    return Agent(
        name="技能安全演示 Agent",
        model=OpenAIChat(
            id=model_id,
            base_url=model_base_url,
            api_key=model_api_key,
            role_map=deepseek_role_map,
            supports_native_structured_outputs=False,
        ),
        skills=Skills(loaders=[LocalSkills(str(skills_root))]),
        tool_hooks=[make_skill_runtime_hook(client, skill_name, agent_id)],
        markdown=True,
        output_schema=AgentAnswer,
        instructions=[
            "你是一个负责解释和评估已加载 Agno skill 的中文助手。",
            "回答必须使用简体中文。",
            "回答前优先使用 skill 自带的工具查看 skill 内容。",
            "优先调用 get_skill_instructions，需要时再查看 reference 或 script。",
            "如果运行时治理会阻止某个工具调用，不要假装它已经执行成功。",
            "输出保持简洁，并严格遵守结构化输出格式。",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agno demo for guarded skill loading with Skill Manager")
    parser.add_argument("--skill-name", required=True, help="Registered skill name")
    parser.add_argument("--skill-path", required=True, help="Local path to the skill directory")
    parser.add_argument("--question", required=True, help="User question for the agent")
    parser.add_argument("--skill-id", default=None, help="Optional registry skill id")
    parser.add_argument("--agent-id", default=os.getenv("AGENT_ID", "agno-demo-agent"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("SKILL_MANAGER_BASE_URL", "http://127.0.0.1:8080"),
        help="Skill Manager API base URL",
    )
    return parser.parse_args()


def run_demo(
    *,
    skill_name: str,
    skill_path: str | Path,
    question: str,
    base_url: str,
    agent_id: str,
    skill_id: str | None = None,
) -> AgentAnswer | BaseModel | str:
    resolved_skill_path = Path(skill_path).resolve()
    client = SkillManagerRuntimeClient(base_url=base_url)

    verification = ensure_skill_can_load(
        client=client,
        skill_name=skill_name,
        skill_id=skill_id,
        skill_path=resolved_skill_path,
        agent_id=agent_id,
    )

    with staged_skills_root(skill_name, resolved_skill_path) as skills_root:
        agent = build_agent(
            client=client,
            skill_name=skill_name,
            skills_root=skills_root,
            agent_id=agent_id,
        )
        prompt = (
            f"问题：{question}\n"
            f"Skill 名称：{skill_name}\n"
            f"已验证状态：{verification.status or 'unknown'}\n"
            f"已验证风险等级：{verification.risk_level or 'unknown'}\n"
            "请先使用 skill 工具读取内容，再回答。"
            "请明确说明这个 skill 在加载前已经通过本地签名校验。"
        )
        result = agent.run(prompt)
        return result.content


def main() -> None:
    args = parse_args()
    answer = run_demo(
        skill_name=args.skill_name,
        skill_path=args.skill_path,
        question=args.question,
        base_url=args.base_url,
        agent_id=args.agent_id,
        skill_id=args.skill_id,
    )

    if isinstance(answer, BaseModel):
        print(answer.model_dump_json(indent=2, ensure_ascii=False))
        return

    print(answer)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Demo failed: {exc}")
