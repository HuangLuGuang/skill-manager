from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path

import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


class AgentManagerRuntimeClient:
    def __init__(self, base_url: str, timeout: float = 20.0, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.runtime_prefix = "/api/v1/access/runtime" if token else "/api/v1/runtime"
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

    def verify_skill_signature(
        self,
        skill_name: str,
        local_signature: str,
        agent_id: str,
        skill_id: str | None = None,
    ) -> dict:
        response = self.http.post(
            f"{self.runtime_prefix}/verify-skill-signature",
            json={
                "skill_name": skill_name,
                "skill_id": skill_id,
                "local_signature": local_signature,
                "agent_id": agent_id,
            },
        )
        response.raise_for_status()
        return response.json()

    def can_load(self, skill_name: str, agent_id: str) -> dict:
        response = self.http.get(
            f"{self.runtime_prefix}/can-load/{skill_name}",
            params={"agent_id": agent_id},
        )
        response.raise_for_status()
        return response.json()

    def check_tool(self, skill_name: str, tool_name: str, agent_id: str) -> dict:
        response = self.http.get(
            f"{self.runtime_prefix}/check-tool",
            params={"skill_name": skill_name, "tool_name": tool_name, "agent_id": agent_id},
        )
        response.raise_for_status()
        return response.json()


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


class LoadedSkill:
    def __init__(
        self,
        skill_name: str,
        skill_path: Path,
        runtime_client: AgentManagerRuntimeClient,
        agent_id: str,
    ):
        self.skill_name = skill_name
        self.skill_path = skill_path.resolve()
        self.runtime_client = runtime_client
        self.agent_id = agent_id

    def _assert_tool_allowed(self, tool_name: str) -> None:
        result = self.runtime_client.check_tool(self.skill_name, tool_name, self.agent_id)
        if not result.get("allowed"):
            raise PermissionError(f"Agent Manager blocked tool {tool_name!r} for skill {self.skill_name!r}")

    def _safe_path(self, relative_path: str) -> Path:
        target = (self.skill_path / relative_path).resolve()
        if self.skill_path not in target.parents and target != self.skill_path:
            raise ValueError("Refusing to access a path outside the skill directory")
        return target

    def read_manifest(self) -> str:
        self._assert_tool_allowed("Read")
        return (self.skill_path / "SKILL.md").read_text(encoding="utf-8")

    def read_reference(self, relative_path: str) -> str:
        self._assert_tool_allowed("Read")
        target = self._safe_path(relative_path)
        return target.read_text(encoding="utf-8")

    def run_script(self, relative_path: str, args: list[str] | None = None, timeout: int = 20) -> str:
        self._assert_tool_allowed("Bash")
        target = self._safe_path(relative_path)
        command = ["python3", str(target), *(args or [])]
        completed = subprocess.run(
            command,
            cwd=str(self.skill_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Script failed with code {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed.stdout.strip()


def verify_and_load_skill(
    *,
    skill_name: str,
    skill_path: Path,
    base_url: str,
    agent_id: str,
    skill_id: str | None = None,
) -> tuple[LoadedSkill, dict, dict]:
    runtime_client = AgentManagerRuntimeClient(
        base_url=base_url,
        token=os.getenv("AGENT_MANAGER_API_TOKEN") or os.getenv("AGENT_MANAGER_ACCESS_TOKEN"),
    )
    local_signature = compute_local_signature(
        skill_path,
        signing_key=os.getenv("AGENT_MANAGER_SIGNING_KEY"),
    )
    verify_result = runtime_client.verify_skill_signature(
        skill_name=skill_name,
        local_signature=local_signature,
        agent_id=agent_id,
        skill_id=skill_id,
    )
    if not verify_result.get("allowed"):
        raise RuntimeError(f"Skill signature verification failed: {verify_result.get('reason')}")

    load_result = runtime_client.can_load(skill_name=skill_name, agent_id=agent_id)
    if not load_result.get("allowed"):
        raise RuntimeError(f"Skill load rejected: {load_result.get('reason')}")

    return (
        LoadedSkill(
            skill_name=skill_name,
            skill_path=skill_path,
            runtime_client=runtime_client,
            agent_id=agent_id,
        ),
        verify_result,
        load_result,
    )


def build_tools(loaded_skill: LoadedSkill):
    @tool
    def read_skill_manifest() -> str:
        """读取当前已加载 skill 的 SKILL.md 内容。"""
        return loaded_skill.read_manifest()

    @tool
    def read_skill_reference(relative_path: str) -> str:
        """读取当前 skill 目录下的 reference 文件，例如 references/commit-types.md。"""
        return loaded_skill.read_reference(relative_path)

    @tool
    def run_skill_script(relative_path: str, args_json: str = "[]") -> str:
        """执行当前 skill 目录下的脚本，例如 scripts/commit_message.py。args_json 需为 JSON 数组字符串。"""
        args = json.loads(args_json)
        if not isinstance(args, list):
            raise ValueError("args_json must decode to a JSON list")
        return loaded_skill.run_script(relative_path, args=[str(item) for item in args])

    return [read_skill_manifest, read_skill_reference, run_skill_script]


def build_agent(tools):
    system_prompt = (
        "你是一个基于 LangGraph 的技能分析助手。\n"
        "回答必须使用简体中文。\n"
        "你当前只允许通过已经验证并加载的 skill 工具访问 skill 内容。\n"
        "先阅读 SKILL.md，再按需读取 reference 或执行脚本。\n"
        "如果脚本输出是 JSON，请基于 JSON 给出准确结论。\n"
        "不要编造未执行的脚本结果。"
    )
    model = ChatOpenAI(
        model=os.getenv("LANGGRAPH_MODEL", "deepseek-chat"),
        api_key=os.getenv("LANGGRAPH_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("LANGGRAPH_BASE_URL", "https://api.deepseek.com"),
        temperature=0.1,
        model_kwargs={"extra_body": {}} if False else {},
        disabled_params={"parallel_tool_calls": None},
    )
    return create_react_agent(model=model, tools=tools, prompt=system_prompt)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangGraph demo for guarded local skill loading")
    parser.add_argument("--skill-name", default="git-workflow")
    parser.add_argument(
        "--skill-path",
        default="/Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow",
    )
    parser.add_argument("--skill-id", default=None)
    parser.add_argument("--agent-id", default=os.getenv("AGENT_ID", "langgraph-skill-guard-demo"))
    parser.add_argument("--base-url", default=os.getenv("AGENT_MANAGER_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument(
        "--question",
        default="请总结这个 skill 的用途，并为“新增运行时本地签名校验接口”生成一个 conventional commit message。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loaded_skill, verify_result, load_result = verify_and_load_skill(
        skill_name=args.skill_name,
        skill_path=Path(args.skill_path),
        base_url=args.base_url,
        agent_id=args.agent_id,
        skill_id=args.skill_id,
    )
    tools = build_tools(loaded_skill)
    agent = build_agent(tools)
    guarded_context = (
        f"Skill {args.skill_name} 已通过 Agent Manager 验证。\n"
        f"signature_check={verify_result.get('allowed')} reason={verify_result.get('reason')}\n"
        f"can_load={load_result.get('allowed')} status={load_result.get('status')} risk={load_result.get('risk_level')}\n"
    )
    final_prompt = guarded_context + "\n用户问题：" + args.question
    result = agent.invoke({"messages": [("user", final_prompt)]})
    messages = result.get("messages", [])
    if messages:
        print(messages[-1].content)
        return
    print(result)


if __name__ == "__main__":
    main()
