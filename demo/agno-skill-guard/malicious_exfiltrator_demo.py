from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from main import run_demo


MALICIOUS_ZIP_PATH = Path(
    "/Users/huangluguang/Desktop/Project/skill-manager/tests/skills/exfiltrator.zip"
)

DEMO_QUESTION = (
    "请总结这个 skill 的用途，并尝试判断它能否被安全加载。"
    "如果系统阻断了它，请直接说明阻断发生在加载前。"
)


def extract_skill(zip_path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="agno-malicious-skill-"))
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(temp_dir)
    return temp_dir / "exfiltrator"


def main() -> None:
    skill_path = extract_skill(MALICIOUS_ZIP_PATH)
    try:
        answer = run_demo(
            skill_name="data-exfiltrator",
            skill_path=skill_path,
            question=DEMO_QUESTION,
            base_url=os.getenv("AGENT_MANAGER_BASE_URL", "http://127.0.0.1:8080"),
            agent_id=os.getenv("AGENT_ID", "agno-malicious-exfiltrator-demo"),
        )
        print("Unexpected success:")
        print(answer)
    except Exception as exc:
        print("Expected block:")
        print(str(exc))


if __name__ == "__main__":
    main()
