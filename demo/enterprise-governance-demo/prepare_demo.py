import requests
import json
import os
import sys
import time
import subprocess
from pathlib import Path

# Configuration
BASE_URL = os.environ.get("AGENT_MANAGER_BASE_URL", "http://localhost:8000")
DEMO_DIR = Path(__file__).parent

def print_step(msg):
    print(f"\n>>> {msg} <<<")

def wait_for_prompt(prompt_id, name):
    print(f"   [审计] 正在执行异步安全审计...", end="", flush=True)
    # Use CLI to avoid authentication issues for polling if needed, 
    # but since this script is for local demo setup, we use CLI for everything.
    for _ in range(30):
        cmd = ["uv", "run", "agent-manager", "prompt", "list", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            prompts = json.loads(result.stdout)
            match = next((p for p in prompts if p["prompt_id"] == prompt_id), None)
            if match and match.get("status") != "PENDING":
                print(f"\r   => 审计完成。状态: {match.get('status')}, 安全评级: {match.get('risk_level') or 'SAFE'}")
                return match
        print(".", end="", flush=True)
        time.sleep(1)
    print("\n   [警告] 审计超时，请稍后在控制台查看。")
    return None

def submit_prompt(name, filename):
    print(f"   正在同步安全策略 (Prompt): {name}...")
    file_path = DEMO_DIR / "prompts" / filename
    # Use CLI instead of REST to handle authentication via direct DB access
    cmd = [
        "uv", "run", "agent-manager", "prompt", "submit", str(file_path),
        "--name", name, "--json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   [失败] 提交提示词失败: {result.stderr}")
        return None
    
    try:
        data = json.loads(result.stdout)
        return wait_for_prompt(data["prompt_id"], name)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"   [错误] 解析提交结果失败: {e}")
        return None

def wait_for_skill(skill_id, name):
    print(f"   [审计] 正在执行深度行为分析与沙箱验证...", end="", flush=True)
    for _ in range(60):
        # Use CLI to poll status
        cmd = ["uv", "run", "agent-manager", "list", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            skills = json.loads(result.stdout)
            match = next((s for s in skills if s["skill_id"] == skill_id), None)
            if match and match.get("status") != "PENDING":
                print(f"\r   => 审计完成。状态: {match.get('status')}, 综合风险: {match.get('risk_level') or 'LOW'}")
                return match
        print(".", end="", flush=True)
        time.sleep(1)
    print("\n   [警告] 审计超时，请稍后在控制台查看。")
    return None

def submit_skill(path):
    print(f"   正在通过安全网关提交技能: {path.name}...")
    # Use --no-cache to ensure fresh results for the demo
    cmd = [
        "uv", "run", "agent-manager", "submit", str(path),
        "--behavioral", "--sandbox", "--llm", "--no-cache", "--json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return wait_for_skill(data["skill_id"], path.name)
        except (json.JSONDecodeError, KeyError):
            print(f"   => 提交成功，但解析返回结果失败。")
    else:
        print(f"   => 接入失败: {result.stderr}")

def main():
    print_step("1. 初始化企业级 AI 治理环境")
    
    print_step("2. 配置核心指令准入策略 (Prompts)")
    submit_prompt("safe-advisor", "safe-advisor.txt")
    submit_prompt("malicious-advisor", "malicious-advisor.txt")
    
    print_step("3. 配置企业技能准入策略 (Skills)")
    submit_skill(DEMO_DIR / "skills" / "welfare-tools")
    submit_skill(DEMO_DIR / "skills" / "data-logger")
    
    print_step("4. 系统治理环境配置完成")
    print(f"   后续操作：")
    print(f"   - 登录治理控制台查看审计报告: {BASE_URL.replace('/api', '')}")
    print(f"   - 启动受控 Agent 业务实例: python3 run_agent_demo.py safe")

if __name__ == "__main__":
    main()
