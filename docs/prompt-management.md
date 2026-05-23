# 提示词管理 (Prompt Management) 使用指南

提示词管理系统（Prompt Registry）是 Agent Manager 的核心组件之一，专门用于治理 AI Agent 的系统提示词（System Prompts）。它确保提示词在上线前经过安全审计，并在运行时通过签名验证防止篡改。

---

## 1. 核心流程

提示词的生命周期遵循以下严格的治理流程：

1.  **提交 (Submit)**：开发者提交提示词内容及所属 Agent ID。
2.  **安全扫描 (Vet)**：系统自动调用安全引擎进行正则扫描（注入检测、代码风险等）和 LLM 语义审计。
3.  **审核 (Review)**：
    *   **自动批准**：低风险提示词根据策略自动进入 `APPROVED` 状态。
    *   **人工审核**：中高风险提示词进入审核队列，需管理员手动“批准”或“驳回”。
4.  **签署 (Sign)**：批准后，系统计算提示词内容的不可伪造签名（HMAC-SHA256）。
5.  **部署 (Deploy)**：标记为可使用状态，并可选择导出到指定目录。
6.  **运行时验签 (Runtime Verify)**：Agent 加载提示词时，实时比对内容指纹。
7.  **停用 (Retire)**：紧急情况下撤销提示词权限，立即生效。

---

## 2. 管理台操作指南

### 2.1 提交新提示词
进入 **“提示词管理”** 页面，点击 **“提交新提示词”**：
- **名称**：具有辨识度的版本标识（如 `customer-service-v1.2`）。
- **内容**：完整的系统提示词文本。
- **Agent ID**：关联的智能体标识。

### 2.2 安全审计
在提示词详情页，你可以看到 **“安全扫描结果”**：
- **注入检测**：识别试图绕过系统指令（Instruction Override）的企图。
- **泄露检测**：识别试图窃取系统内部指令或敏感信息的模式。
- **角色审计**：LLM 会判断提示词是否赋予了 Agent 过高的权限或潜在的恶意人格。

如果启用了模型网关，提示词 LLM 审计请求会先经过隐私路由，再转发给上游模型供应商。这样可以在 `Pipeline Trace` 中看到内部 vetting 请求的四阶段处理过程，并避免把明文 PII 直接发给外部模型。

配置方式：

```bash
export AGENT_MANAGER_LLM_GATEWAY_URL="http://127.0.0.1:8000/v1/chat/completions"
export AGENT_MANAGER_LLM_GATEWAY_API_KEY="amk_xxx"
```

详细说明见 [model-gateway.md](model-gateway.md)。

### 2.3 审批上线
- 状态为 `VETTED` 的提示词需要管理员介入。
- 点击 **“通过审核”**，系统会固化内容并生成签名。

### 2.4 部署与导出
- 状态为 `APPROVED` 后，点击 **“部署上线”**。
- 如果配置了目标路径，提示词将以 `.txt` 文件形式导出，供 Agent 直接读取。

---

## 3. 开发者与 Agent 集成

Agent 在启动或加载 Prompt 时，应通过 API 与 Agent Manager 进行“验票”。

### 3.1 检查提示词状态
判断某个提示词是否允许被加载：
```http
GET /api/v1/runtime/can-load-prompt/{prompt_name}
```
**返回：** `allowed: true/false`。如果提示词已被 **RETIRED** 或 **REJECTED**，将返回 `false`。

### 3.2 验证内容一致性（防止篡改）
Agent 加载本地文件后，发送内容进行比对：
```http
GET /api/v1/runtime/verify-prompt?prompt_name=xxx&local_content=...
```
**返回：**
- `valid: true`：内容与审批时一致，可以放心使用。
- `valid: false`：**内容已被篡改！** 应拒绝加载。

---

## 4. 安全扫描项说明

| 风险类别 | 检测原理 | 说明 |
| :--- | :--- | :--- |
| **指令覆盖 (Override)** | 正则/语义 | 检测 `Ignore all previous...` 等试图剥离安全边界的指令 |
| **提示词泄露 (Leakage)** | 正则 | 检测试图打印或通过 API 暴露 System Prompt 的行为 |
| **代码注入 (Code Injection)** | 正则 | 检测提示词中嵌入的恶意脚本或 OS 命令 |
| **越狱 (Jailbreak)** | LLM 审计 | 检测 DAN 模式或恶意人格设定 |

---

## 5. 提示词与技能 (Skill) 的区别

- **技能 (Skill)**：是功能集合（代码、脚本、资源），通过 `SKILL.md` 驱动。
- **提示词 (Prompt)**：是行为指令（纯文本），驱动智能体的角色和决策逻辑。

两者在 Agent Manager 中都遵循“签名-验签”的治理逻辑，但提示词侧重于**语义安全**，技能侧重于**执行安全**。
