# AI-Infra-Guard Upstream Modifications

Vendored source: Tencent AI-Infra-Guard `v4.6.0`, commit
`e8931cc68001b66ad024fd87ef07394e9e96524a`.

Agent Manager keeps the locked Provider catalog, Agent Adapter, MCP Scan source and requirements files byte-identical
to upstream except for the following Agent Scan integration patches, which are marked in source:

- `agent-scan/agent_scan/utils/logging.py`：文件日志改为默认关闭；只有显式配置可写目录并设置
  `AIG_AGENT_SCAN_FILE_LOGS=1` 才启用。原因是扫描 Worker 使用只读根文件系统，且原始响应不能默认
  落入普通日志。
- `agent-scan/agent_scan/core/agent.py`、`core/detection_execution.py`：为每个 detection skill 保存完成、
  异常、实际 dialogue 调用和候选 Finding 数；为候选漏洞附加程序生成的 opaque source reference，并在 Reviewer
  后只通过 Worker 持有的映射恢复 `source_skill`。
- `agent-scan/agent_scan/core/base_agent.py`、`utils/tool_context.py`：把程序生成的 Worker `stage_id` 传到
  受控 Provider seam，使异常 Worker 已经发出的目标调用也能按规则计数。
- `agent-scan/agent_scan/core/report/models.py`、`core/report/report.py`：在内部报告解析链中保留 opaque
  `source_ref`，供 Worker 做受控来源解析。
- `agent-scan/agent_scan/prompt/system/agent_security_reviewer.md`：要求 Reviewer 原样保留 `source_ref`，且不跨
  不同来源引用合并 Finding。

P3 does not patch upstream MCP Scan. `mcp_adapter.py` reads the locked description-sanitizer constants from
`mcp-scan/mcp_scan/utils/mcp_tools.py` and maps Gateway metadata into the platform Finding model. The upstream
dynamic path is intentionally not invoked because it exposes `call_mcp_tool` and performs real exploit calls;
P3 enforces metadata-only analysis with zero `tools/call` requests.

The upstream `LICENSE` and `NOTICE` are copied into the Worker image under `/app/licenses/`, together with an
SPDX 2.3 package SBOM generated at image build time.
