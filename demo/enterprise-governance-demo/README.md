# 企业级 AI 治理演示 (Skills + Prompts)

本 Demo 模拟了一家金融服务公司的“理财助手”智能体场景，展示了如何同时治理技能（Skills）和提示词（Prompts）。

## 场景角色
- **智能体**：理财助手 (Financial Advisor)
- **目标**：帮助用户计算房贷，提供基础理财建议。

---

## 1. 演示内容

### 提示词治理 (Prompt Governance)
1.  **安全提示词 (`safe-advisor.txt`)**：专业的理财师指令。
    -   *预期*：扫描通过，自动批准。
2.  **恶意注入提示词 (`malicious-advisor.txt`)**：包含指令覆盖（Override）和凭证窃取意图。
    -   *预期*：被安全引擎拦截，标识为 `CRITICAL` 风险。

### 技能治理 (Skill Governance)
1.  **安全技能 (`mortgage-calculator`)**：纯本地计算房贷。
    -   *预期*：扫描通过，允许加载。
2.  **恶意技能 (`data-logger`)**：伪装成统计工具，实际在后台窃取环境变量并通过网络外发。
    -   *预期*：行为分析识别到 `os.environ` 访问 and 外部请求，被拦截。

---

## 2. 快速开始 (演示流程)

### A. 环境准备
确保后端服务已启动：
```bash
uv run --project backend uvicorn backend.main:app --reload
```

### B. 提交并查看风险
使用 CLI 批量提交演示样本：
```bash
# 提交提示词
uv run agent-manager prompt submit demo/enterprise-governance-demo/prompts/safe-advisor.txt --name safe-advisor
uv run agent-manager prompt submit demo/enterprise-governance-demo/prompts/malicious-advisor.txt --name malicious-advisor

# 提交技能
uv run agent-manager submit demo/enterprise-governance-demo/skills/mortgage-calculator --behavioral --sandbox
uv run agent-manager submit demo/enterprise-governance-demo/skills/data-logger --behavioral --sandbox
```

### C. 管理台演示逻辑
1.  **总览页**：展示风险饼图的变化。
2.  **提示词管理**：
    -   展示 `malicious-advisor` 为何被拦截（查看扫描发现项：指令覆盖）。
    -   批准 `safe-advisor`。
3.  **技能注册表**：
    -   展示 `data-logger` 的行为审计结果（代码中的恶意模式）。
    -   在 Sandbox 详情中查看 `mortgage-calculator` 的正常运行信号。

---

## 3. 运行 Agent 闭环演示 (Live Agent Demo)

本环节展示 Agent 在加载 Prompt 和 Skill 前如何执行“验票”逻辑。

### A. 配置密钥 (DeepSeek)
```bash
export DEEPSEEK_API_KEY="您的key"
```

### B. 运行安全场景 (Safe)
演示 Agent 成功加载经过批准的提示词和技能。
```bash
python3 demo/enterprise-governance-demo/run_agent_demo.py safe
```
- **过程**：校验 `advisor-safe` (OK) -> 校验 `mortgage-calculator` (OK) -> 启动 Agent。

### C. 运行拦截场景 (Malicious)
演示 Agent 拒绝加载未通过审计的恶意内容。
```bash
python3 demo/enterprise-governance-demo/run_agent_demo.py malicious
```
- **预期**：在第一步校验提示词时即被拦截，提示 `[BLOCKED]`。

---

## 4. 核心价值讲解点
- **双重防线**：不仅管代码（Skill），还管语义（Prompt）。
- **篡改检测**：演示修改 `safe-advisor.txt` 内容后，再次调用验证接口会失败。
- **治理闭环**：所有拦截行为均在“审计日志”中可查。
