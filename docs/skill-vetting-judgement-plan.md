# Skill 检测综合判定实施计划

本文件跟踪 Skill 检测从“最高风险一票决定”升级为“风险信号分类 + 判定模式 + LLM 综合研判 + 可解释结论”的实现进度。

## 目标

- 降低误报：LOW 和运行环境噪声不再把 Skill 判成可疑。
- 保持安全底线：明确阻断项不可被 LLM 或宽松模式降级。
- 提升解释性：当规则、深度扫描、Sandbox 与最终结论不一致时，页面能说明原因。

## 判定模型

### 风险信号分类

- `blocking`：明确阻断项，例如下载后执行、凭据窃取、数据外传、绕过 Agent Manager 校验、策略禁止权限。
- `risk`：需要研判的风险项，例如动态执行、系统命令、网络访问、敏感文件访问。
- `noise`：不直接影响最终风险的信号，例如依赖缺失、样例未跑通、解析失败、低可分析性提示。

### 判定模式

- `strict` 严格模式：优先降低漏报风险。非阻断 HIGH 也会判为恶意或强制审核。
- `balanced` 平衡模式（推荐）：明确阻断项拒绝；非阻断 HIGH/MEDIUM 进入审核；LLM 可解释降级非阻断风险。
- `permissive` 宽松模式：优先减少误报。非阻断 MEDIUM 只提示；HIGH 进入审核，LLM 可解释降级。

### LLM 综合研判

启用 LLM 时，将规则分析、深度扫描、Sandbox、本地静态分析结果和 Skill 摘要传给 LLM。LLM 可以：

- 升级风险：发现工具漏掉的真实恶意链路。
- 降级非阻断风险：必须给出 `downgrade_reason` 或报告说明。
- 不可降级阻断项：阻断项始终保持 `malicious`。

## 实施任务

- [x] 写入本计划文档。
- [x] 后端策略增加 `judgement_mode`，默认 `balanced`。
- [x] 后端新增风险信号分类，写入 `scan_report.risk_classification`。
- [x] 后端按判定模式合成 `pre_llm_risk_level`。
- [x] 后端允许 LLM 降级非阻断风险，并记录 `risk_reconciliation.downgrade_reason`。
- [x] 前端策略配置增加“判定模式”选择。
- [x] Skill 详情增加“综合研判结论”和差异解释。
- [x] 补充测试：LOW 不升可疑、HIGH 非阻断待审核、blocking 不可降级、LLM 可降级非阻断。

## 验收命令

```bash
uv run pytest tests/test_vetting.py -q
npm run build
```
