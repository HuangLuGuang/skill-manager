from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from main import run_demo


DEFAULT_SKILL_PATH = (
    Path("/Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow")
)

DEFAULT_QUESTION = (
    "请使用这个 git-workflow skill 的内容，"
    "先总结它的用途，"
    "再为“新增运行时本地签名校验接口”生成一个 conventional commit message，"
    "如果需要可以使用 skill 自带的 reference 或 script。"
)


def main() -> None:
    answer = run_demo(
        skill_name="git-workflow",
        skill_path=DEFAULT_SKILL_PATH,
        question=DEFAULT_QUESTION,
        base_url=os.getenv("SKILL_MANAGER_BASE_URL", "http://127.0.0.1:8080"),
        agent_id=os.getenv("AGENT_ID", "agno-git-workflow-demo"),
    )

    if isinstance(answer, BaseModel):
        print(answer.model_dump_json(indent=2, ensure_ascii=False))
        return

    print(answer)


if __name__ == "__main__":
    main()
