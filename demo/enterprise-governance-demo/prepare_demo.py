import requests
import json
import os
import sys
from pathlib import Path

# Configuration
BASE_URL = os.environ.get("AGENT_MANAGER_BASE_URL", "http://localhost:8000")
DEMO_DIR = Path(__file__).parent

def print_step(msg):
    print(f"\n[DEMO STEP] {msg}")

def submit_prompt(name, filename):
    print(f"   Submitting prompt: {name}...")
    content = (DEMO_DIR / "prompts" / filename).read_text()
    payload = {
        "name": name,
        "content": content,
        "agent_id": "advisor-bot",
        "description": f"Demo prompt for {name}"
    }
    res = requests.post(f"{BASE_URL}/api/v1/prompts/submit", json=payload)
    data = res.json()
    print(f"   => Result: Status={data.get('status')}, Risk={data.get('risk_level')}")
    return data

def submit_skill(path):
    print(f"   Submitting skill: {path.name}...")
    # Using CLI for skill submission as it handles packaging
    import subprocess
    cmd = [
        "uv", "run", "agent-manager", "submit", str(path),
        "--behavioral", "--sandbox", "--llm"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"   => Successfully submitted {path.name}")
    else:
        print(f"   => Error submitting: {result.stderr}")

def main():
    print_step("Initializing Enterprise Governance Demo...")
    
    # 1. Prompts
    print_step("Demonstrating Prompt Governance")
    submit_prompt("safe-advisor", "safe-advisor.txt")
    submit_prompt("malicious-advisor", "malicious-advisor.txt")
    
    # 2. Skills
    print_step("正在演示技能治理")
    submit_skill(DEMO_DIR / "skills" / "welfare-tools")
    submit_skill(DEMO_DIR / "skills" / "data-logger")
    
    print_step("Demo data prepared. Please visit the dashboard to show the results to the customer.")
    print(f"Dashboard URL: {BASE_URL.replace('api', '')}")

if __name__ == "__main__":
    main()
