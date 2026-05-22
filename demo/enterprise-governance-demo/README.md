# 企业级 AI 治理闭环演示 (Lingxi Scenario)

本 Demo 展示了 Agent Manager 如何为企业提供“从准入到运行”的全链路 AI 安全治理，涵盖了 **提示词 (Prompts)** 和 **技能 (Skills)** 两大核心治理对象。

---

## 演示主线
**“准入前深度审计 -> 批准时数字签名 -> 加载前双重验签 -> 运行中行为可溯”**

---

## 演示流程 (4 步走)

### 第一步：环境初始化与样本提交
运行一键准备脚本。该脚本会模拟开发者向系统提交安全与恶意的样例，并自动触发安全扫描引擎。
```bash
python3 demo/enterprise-governance-demo/prepare_demo.py
```
- **看点**：控制台将展示实时提交进度，包括后端对 Prompt 注入的识别结果。

### 第二步：管理台深度巡检 (Web UI)
打开浏览器访问 [http://localhost:8000](http://localhost:8000)：
1.  **提示词管理**：
    -   展示 `malicious-advisor` 为什么被标记为 `CRITICAL` 风险（命中指令覆盖）。
    -   批准 `safe-advisor` 上线。
2.  **技能注册表**：
    -   查看 `data-logger` 的恶意代码审计报告（识别到环境变量扫描和外部外发行为）。
    -   查看 `welfare-tools` 的 Sandbox 动态执行信号。

### 第三步：全量审计追踪 (Audit Log)
在管理台点击 **“审计日志”**：
- 展示系统捕捉到的每一次“恶意注入尝试”和“非法加载拦截”。
- 强调企业合规性：谁在什么时候提交了什么，扫描结论是什么，谁批准的。

### 第四步：闭环 Agent 运行演示
在终端运行受控 Agent 脚本，模拟真实生产环境下的加载校验。

**1. 运行安全场景 (Safe)**
```bash
python3 demo/enterprise-governance-demo/run_agent_demo.py safe
```
- **看点**：展示 Agent 在启动前成功通过了提示词和技能的双重验签，并正常提供中文行政咨询服务。

**2. 运行拦截场景 (Malicious)**
```bash
python3 demo/enterprise-governance-demo/run_agent_demo.py malicious
```
- **看点**：展示 Agent 检测到提示词未通过审核，立即主动阻断加载并安全退出，防止风险指令执行。

---

## 核心价值点 (向客户强调)
1.  **语义 + 执行双重拦截**：不仅能拦住带毒的代码，还能拦住带毒的对话指令。
2.  **电子签名防篡改**：本地文件一旦被私自篡改，Agent 毫秒级识别并拒载。
3.  **治理原子化**：治理逻辑与 Agent 业务逻辑完全解耦，零成本接入现有 Agent 框架。

