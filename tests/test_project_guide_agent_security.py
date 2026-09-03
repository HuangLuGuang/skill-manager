from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_p7_project_guide_describes_enabled_capabilities_and_business_flows():
    guide = (ROOT / "docs/project-guide.md").read_text(encoding="utf-8")

    for required in (
        "### 2.1 当前产品能力地图",
        "### 2.2 三条核心业务流程",
        "Skill 准入链",
        "Agent / MCP 测评链",
        "运行治理与证据链",
        "页面功能默认开启",
        "### 12.8 智能体安全",
        "扫描管理",
        "安全能力基线",
        "调用轨迹",
        "轨迹能力基线",
        "任务成功或零 Finding 都不自动等于“安全”",
        "完整平台离线安装、真实 Compose 服务的中断",
    ):
        assert required in guide

    assert "# 6.1 提交" not in guide
    assert guide.index("### 6.8 统一调用轨迹后端") < guide.index("### 6.9 MCP Server 和 Tool 风险扫描")
    assert guide.index("### 6.9 MCP Server 和 Tool 风险扫描") < guide.index("### 6.10 安全扫描管理界面")
    assert guide.index("### 6.10 安全扫描管理界面") < guide.index("### 6.11 统一调用轨迹界面")


def test_agent_security_baseline_copy_does_not_claim_trace_ui_is_future_work():
    messages = (ROOT / "web/src/i18n/index.js").read_text(encoding="utf-8")
    assert "完整调用轨迹可视化将在后续阶段提供" not in messages
    assert "complete trace visualization will arrive in a later phase" not in messages
    assert "扫描管理和统一调用轨迹双视图均已启用" in messages
    assert "Scan management and unified dual-view traces are enabled" in messages


def test_p7_model_gateway_doc_covers_trace_correlation_headers_and_privacy_boundaries():
    document = (ROOT / "docs/model-gateway.md").read_text(encoding="utf-8")

    for required in (
        "### 3.1 统一轨迹事件与关联契约",
        "### 3.2 响应关联与诊断头",
        "`model.request`",
        "`model.response`",
        "`model.error`",
        "`trace_id`",
        "`session_id`",
        "`turn_id`、`step_id`",
        "`call_id`",
        "`parent_call_id`",
        "`request_id`",
        "`x-request-id`",
        "`x-conversation-id`",
        "当前模型入口不读取 `X-Trace-ID`",
        "### 11.1 隐私链路与统一轨迹不是同一份数据",
        "原始 Payload 与事件索引分离并加密保存",
        "5 分钟有效、只能消费一次",
        "PDF 只支持脱敏级别",
    ):
        assert required in document


def test_p7_external_agent_doc_routes_sdk_adapters_credentials_and_failure_modes():
    document = (ROOT / "docs/external-agent-integration.md").read_text(encoding="utf-8")

    for required in (
        "通常有六类方式",
        "### 接入方式选择",
        "Agent Manager Client",
        "Universal Skill Verifier",
        "Runtime Trace SDK + Governance API",
        "Gateway-only",
        "最小权限凭证不能混用",
        "from agent_manager.runtime_trace import RuntimeTraceClient",
        "model_metadata = trace.gateway_metadata",
        "mcp_metadata = trace.gateway_metadata",
        "`redacted_payload`",
        "安全放行接口网络失败时必须失败关闭",
        "## MCP Gateway",
        "## Current Gaps",
        "W3C `traceparent` / OpenTelemetry 自动桥接",
    ):
        assert required in document

    assert "通常有四种模式" not in document
    assert "## Mode 4: MCP Gateway" not in document
    assert "支持 streaming 响应的增量反替换" not in document
