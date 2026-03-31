from __future__ import annotations

import argparse
import os
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import LocalSkills, Skills
from pydantic import BaseModel, Field


SKILLS_ROOT = Path(__file__).parent / "skills"


class DiscoveryAnswer(BaseModel):
    summary: str = Field(description="对扫描任务和结果的摘要")
    scan_targets: list[str] = Field(default_factory=list, description="实际扫描的目标")
    open_port_count: int = Field(default=0, description="端口开放数量")
    confirmed_count: int = Field(default=0, description="确认的 OpenClaw 实例数量")
    suspicious_count: int = Field(default=0, description="疑似实例数量")
    findings: list[str] = Field(default_factory=list, description="发现的 OpenClaw 实例或疑似目标")
    next_steps: list[str] = Field(default_factory=list, description="后续排查建议")


def build_agent() -> Agent:
    deepseek_role_map = {
        "system": "system",
        "developer": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }
    return Agent(
        name="OpenClaw 发现 Agent",
        model=OpenAIChat(
            id=os.getenv("AGNO_MODEL_ID", "deepseek-chat"),
            base_url=os.getenv("AGNO_MODEL_BASE_URL", "https://api.deepseek.com"),
            api_key=os.getenv("AGNO_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
            role_map=deepseek_role_map,
            supports_native_structured_outputs=False,
        ),
        skills=Skills(loaders=[LocalSkills(str(SKILLS_ROOT))]),
        output_schema=DiscoveryAnswer,
        markdown=True,
        instructions=[
            "你是一个负责发现 OpenClaw 部署的安全分析助手。",
            "回答必须使用简体中文。",
            "必须先执行扫描脚本，再基于脚本返回的 JSON 结果作答。",
            "如果没有成功拿到脚本返回的 JSON，就不要编造扫描结果。",
            "回答中必须包含 scan_targets、open_port_count、confirmed_count、suspicious_count。",
            "只针对内网目标进行扫描建议和结果解释。",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agno OpenClaw discovery demo")
    parser.add_argument("--target", default=os.getenv("OPENCLOW_TARGET", "127.0.0.1:18789"))
    parser.add_argument("--port", default=os.getenv("OPENCLOW_PORTS", "18789"))
    parser.add_argument("--timeout", default=os.getenv("OPENCLOW_TIMEOUT", "3"))
    parser.add_argument("--concurrency", default=os.getenv("OPENCLOW_CONCURRENCY", "20"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agent = build_agent()
    prompt = (
        "请使用 openclaw-network-discovery skill 扫描目标并总结结果。\n"
        f"目标: {args.target}\n"
        f"端口: {args.port}\n"
        f"超时: {args.timeout}\n"
        f"并发: {args.concurrency}\n"
        "要求：\n"
        "1. 先读取 skill 说明，必要时读取 reference\n"
        "2. 必须执行以下脚本调用，不允许跳过：\n"
        f"   get_skill_script(\"openclaw-network-discovery\", \"discover_openclaw.py\", execute=True, args=[\"--target\", \"{args.target}\", \"--port\", \"{args.port}\", \"--timeout\", \"{args.timeout}\", \"--concurrency\", \"{args.concurrency}\"])\n"
        "3. 你的回答必须严格基于脚本返回的 JSON，不要凭空推断\n"
        "4. 输出 scan_targets、open_port_count、confirmed_count、suspicious_count、findings、next_steps\n"
    )
    result = agent.run(prompt)
    answer = result.content
    if isinstance(answer, BaseModel):
        print(answer.model_dump_json(indent=2, ensure_ascii=False))
        return
    print(answer)


if __name__ == "__main__":
    main()
