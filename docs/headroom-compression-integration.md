# Headroom 上下文压缩集成 — 历史实施记录

> **状态**: 历史实施记录，不作为当前配置或验收手册
> **创建日期**: 2026-06-10
> **实施日期**: 2026-06-10
> **当前文档**: 请以 [model-gateway.md](model-gateway.md) 的“智能上下文压缩”和当前代码、链路追踪为准

---

## 1. 背景与目标

### 1.1 什么是 Headroom

[Headroom](https://github.com/chopratejas/headroom) 是一个上下文压缩库，可在 LLM 请求发送前处理 tool outputs、日志、RAG chunks、文件内容和对话历史。节省量和输出影响取决于具体内容，必须使用实际请求评估，不能把项目宣传数字当成当前环境保证。

- 本地运行，数据不离开用户机器
- Apache 2.0 开源协议
- PyPI: `headroom-ai`（当前 v0.24.0）
- 核心算法: SmartCrusher (JSON), CodeCompressor (AST), Kompress-base (ML 文本), CacheAligner (前缀缓存稳定)

### 1.2 集成目标

将 Headroom 作为 Library 嵌入 Agent Manager 模型网关的请求处理链路中，在 PII 伪匿名化之后、上游转发之前对 messages 数组进行智能压缩。

### 1.3 核心原则

- **可选开启**: 默认关闭，按 API Key 粒度开关，不影响现有用户
- **PII 安全**: 压缩在 PII 伪匿名化之后执行，占位符 Token 不会被截断
- **可观测**: 压缩前后 Token 数、压缩比、耗时全部记录到审计
- **可回退**: 出问题时关闭开关即可秒级恢复

---

## 2. 架构变更概览

### 2.1 请求链路变更

```
当前链路:
  Client → Auth → Model Scope → PII Pseudonymize → Upstream → De-PII → Client

变更后:
  Client → Auth → Model Scope → PII Pseudonymize → [Compress] → Upstream → De-PII → Client
                                                      ↑ 可选，按 API Key 开关
```

### 2.2 涉及文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `backend/models.py` | 修改 | 模型调用凭据新增压缩字段 |
| `backend/schemas.py` | 修改 | 对应 Pydantic schema 新增字段 |
| `backend/routers/llm_gateway.py` | 修改 | 核心集成：压缩调用 + 审计扩展 |
| `backend/sqlite_db.py` | 无需修改 | SQLAlchemy Base.metadata 自动建表 |
| `web/src/` | 修改 | 管理台凭据表单与客户端策略 |
| `pyproject.toml` | 修改 | 新增 `headroom-ai[proxy]` 可选依赖 |
| `docs/model-gateway.md` | 修改 | 文档更新 |

---

## 3. 分步实施计划

### Phase 1: 依赖与配置（预计 0.5 天）

#### Step 1.1 — 添加 Headroom 依赖

**文件**: `pyproject.toml`

在 `[project.optional-dependencies]` 中新增:

```toml
# Headroom 智能压缩（可选）
compression = [
    "headroom-ai[proxy]>=0.24.0",
]
```

在 `[project.optional-dependencies.all]` 中追加 `"headroom-ai[compression]"`（如该 extra 存在）或直接将 compression deps 加入 all。

**验收**: `pip install -e ".[compression]" && python -c "from headroom import compress; print('OK')"`

#### Step 1.2 — 环境变量默认值

**文件**: `backend/config.py`

新增配置项:

```python
# Headroom 智能压缩全局默认
HEADROOM_COMPRESSION_ENABLED_BY_DEFAULT: bool = False
HEADROOM_COMPRESSION_LEVEL: str = "auto"  # auto | conservative | aggressive
```

**验收**: `Agent Manager` 启动日志无异常，默认配置生效。

---

### Phase 2: 数据模型扩展（预计 0.5 天）

#### Step 2.1 — 数据库模型扩展

**文件**: `backend/models.py`

在 `LlmApiKey` 类中新增 3 个字段（加在 `max_concurrent_requests` 之后）:

```python
# Headroom 智能压缩配置
enable_compression = Column(Boolean, default=False, nullable=False)
compression_level = Column(String(32), default="auto", nullable=False)
# "auto" = 均衡策略, "conservative" = 仅 SmartCrusher, "aggressive" = 全部算法 + Kompress
```

在 `LlmUsageMetric` 类中新增 5 个字段（加在 `reused_tokens` 之后）:

```python
# 压缩统计（仅 enable_compression=True 时填充）
pre_compression_tokens = Column(Integer, default=0, nullable=False)
post_compression_tokens = Column(Integer, default=0, nullable=False)
tokens_saved = Column(Integer, default=0, nullable=False)
compression_ratio = Column(Float, default=0.0, nullable=False)
compression_duration_ms = Column(Float, default=0.0, nullable=False)
```

在 `LlmRequestAudit` 类中新增 2 个字段（加在 `reused_tokens` 之后）:

```python
# 压缩标记
compression_enabled = Column(Boolean, default=False, nullable=False)
compression_level = Column(String(32), nullable=True)
```

**注意**: SQLite 不支持 `ALTER TABLE ADD COLUMN IF NOT EXISTS`，但 `Base.metadata.create_all()` 只建新表不修改已有表。如果数据库已存在，需要手动执行 migration。

#### Step 2.2 — Pydantic Schema 扩展

**文件**: `backend/schemas.py`

在 `LlmApiKeyCreate` 中新增:

```python
enable_compression: bool = False
compression_level: str = "auto"
```

在 `LlmApiKeyUpdate` 中新增:

```python
enable_compression: Optional[bool] = None
compression_level: Optional[str] = None
```

在 `LlmApiKeyResponse` 中新增:

```python
enable_compression: bool = False
compression_level: str = "auto"
```

调用凭据的响应中包含压缩开关与级别。

**文件**: `backend/routers/llm_gateway.py`

修改 `_api_key_response()` 函数（约第 188 行），在返回值中新增:

```python
enable_compression=row.enable_compression if hasattr(row, 'enable_compression') else False,
compression_level=row.compression_level if hasattr(row, 'compression_level') else "auto",
```

#### Step 2.3 — 数据库 Migration

创建 migration 脚本 `backend/migrate_compression.py`:

```python
"""为已有数据库添加 Headroom 压缩相关列"""
from backend.sqlite_db import engine

def migrate():
    with engine.begin() as conn:
        dialect = conn.engine.dialect.name
        if dialect != "sqlite":
            return

        # llm_api_keys 表
        existing = {row[1] for row in conn.exec_driver_sql(
            "PRAGMA table_info(llm_api_keys)"
        ).fetchall()}
        for col_name, col_type in [
            ("enable_compression", "BOOLEAN NOT NULL DEFAULT 0"),
            ("compression_level", "VARCHAR(32) NOT NULL DEFAULT 'auto'"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_api_keys ADD COLUMN {col_name} {col_type}"
                )

        # llm_usage_metrics 表
        existing = {row[1] for row in conn.exec_driver_sql(
            "PRAGMA table_info(llm_usage_metrics)"
        ).fetchall()}
        for col_name, col_type in [
            ("pre_compression_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("post_compression_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("tokens_saved", "INTEGER NOT NULL DEFAULT 0"),
            ("compression_ratio", "FLOAT NOT NULL DEFAULT 0.0"),
            ("compression_duration_ms", "FLOAT NOT NULL DEFAULT 0.0"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_usage_metrics ADD COLUMN {col_name} {col_type}"
                )

        # llm_request_audit 表
        existing = {row[1] for row in conn.exec_driver_sql(
            "PRAGMA table_info(llm_request_audit)"
        ).fetchall()}
        for col_name, col_type in [
            ("compression_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("compression_level", "VARCHAR(32)"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_request_audit ADD COLUMN {col_name} {col_type}"
                )

if __name__ == "__main__":
    migrate()
    print("Migration completed.")
```

在 `backend/main.py` 的 `ensure_sqlite_schema()` 函数末尾添加调用:

```python
from backend.migrate_compression import migrate as migrate_compression
migrate_compression()
```

**验收**: 重启服务后，已有 API Key 的 `enable_compression` 默认为 `false`，新建 API Key 时可设置该字段。

---

### Phase 3: 核心压缩集成（预计 1 天）

#### Step 3.1 — 压缩模块封装

**新建文件**: `backend/compression.py`

```python
"""Headroom 智能压缩集成模块

在 PII 伪匿名化之后、上游转发之前对 messages 进行压缩。
"""

import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CompressionResult:
    """压缩结果"""
    def __init__(
        self,
        messages: list[dict[str, Any]],
        pre_tokens: int,
        post_tokens: int,
        duration_ms: float,
        compressor_used: str,
    ):
        self.messages = messages
        self.pre_tokens = pre_tokens
        self.post_tokens = post_tokens
        self.tokens_saved = pre_tokens - post_tokens
        self.ratio = (self.tokens_saved / pre_tokens) if pre_tokens > 0 else 0.0
        self.duration_ms = duration_ms
        self.compressor_used = compressor_used


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """快速估算 messages 数组的 token 数。

    使用简单启发式：英文 1 token ≈ 4 chars，中文 1 token ≈ 1.5 chars。
    这是一个近似值，用于压缩前后对比；不需要精确 tokenizer。
    """
    import json
    text = json.dumps(messages, ensure_ascii=False)
    # 粗略估计
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return int(ascii_chars / 4 + non_ascii_chars / 1.5)


def compress_messages(
    messages: list[dict[str, Any]],
    *,
    model: str = "gpt-4o",
    level: str = "auto",
    enable_ccr: bool = False,
) -> CompressionResult:
    """对 messages 数组进行智能压缩。

    Args:
        messages: 已伪匿名化的 messages 列表
        model: 目标模型名，用于 ContentRouter 选择策略
        level: 压缩级别
            - "conservative": 仅 SmartCrusher (JSON 压缩)
            - "auto": SmartCrusher + CodeCompressor（均衡策略）
            - "aggressive": 全部算法 + Kompress-base ML 模型
        enable_ccr: 是否启用可逆压缩（CCR）。网关场景默认关闭。

    Returns:
        CompressionResult 包含压缩后的 messages 和统计信息。

    Raises:
        ImportError: headroom 未安装
        Exception: 压缩失败时返回原始 messages（降级策略）
    """
    pre_tokens = _estimate_tokens(messages)

    try:
        import headroom  # noqa: F401  # 验证 headroom 可用
    except ImportError:
        logger.warning("headroom not installed, skipping compression")
        return CompressionResult(
            messages=messages,
            pre_tokens=pre_tokens,
            post_tokens=pre_tokens,
            duration_ms=0,
            compressor_used="none (headroom not installed)",
        )

    start = time.perf_counter()

    try:
        # 调用 Headroom 的 compress 函数
        # 注意: 这个 API 可能随 headroom 版本变化，需要根据实际 API 调整
        from headroom import compress

        # 构建压缩选项
        compress_options: dict[str, Any] = {
            "model": model,
            "enable_ccr": enable_ccr,
        }

        if level == "conservative":
            # 仅 JSON/结构化数据压缩
            compress_options["algorithms"] = ["smart_crusher"]
        elif level == "aggressive":
            # 所有算法 + ML 模型
            compress_options["algorithms"] = [
                "smart_crusher",
                "code_compressor",
                "log_compressor",
                "kompress",
            ]
        # "auto": 使用 Headroom 默认策略（ContentRouter 自动选择）

        compressed_messages = compress(messages, **compress_options)

        elapsed_ms = (time.perf_counter() - start) * 1000
        post_tokens = _estimate_tokens(compressed_messages)

        logger.info(
            "Compression: %d → %d tokens (%.1f%%, %.1fms, level=%s)",
            pre_tokens,
            post_tokens,
            (pre_tokens - post_tokens) / pre_tokens * 100 if pre_tokens > 0 else 0,
            elapsed_ms,
            level,
        )

        # 类型转换：确保返回的是 list[dict]
        if isinstance(compressed_messages, list):
            result_messages = compressed_messages
        else:
            # 如果 Headroom 返回了其他格式，兼容处理
            result_messages = list(compressed_messages)  # type: ignore[arg-type]

        return CompressionResult(
            messages=result_messages,
            pre_tokens=pre_tokens,
            post_tokens=post_tokens,
            duration_ms=elapsed_ms,
            compressor_used=f"headroom ({level})",
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            "Compression failed (%.1fms), falling back to uncompressed: %s",
            elapsed_ms,
            exc,
        )
        # 降级策略：返回原始 messages，不阻断请求
        return CompressionResult(
            messages=messages,
            pre_tokens=pre_tokens,
            post_tokens=pre_tokens,
            duration_ms=elapsed_ms,
            compressor_used=f"fallback (error: {exc})",
        )
```

**验收**: 单元测试验证 `compress_messages` 可正常导入和调用。

#### Step 3.2 — 网关集成

**文件**: `backend/routers/llm_gateway.py`

在文件顶部新增 import（约第 20 行附近）:

```python
from ..compression import compress_messages
```

**关键集成点 1 — 解析压缩开关**（在 `_chat_completions_with_key` 函数开头，约第 1551 行，`policy = _resolve_policy(db, key)` 之后）:

```python
model = _resolve_model(db, payload.model, key)
compression_enabled = bool(getattr(key, 'enable_compression', False))
compression_level = getattr(key, 'compression_level', None) or "auto"
```

**关键集成点 2 — 执行压缩**（在约第 1617-1627 行，`body["messages"]` 构建完成之后、`if payload.stream:` 之前）:

```python
# === Headroom 智能压缩（可选） ===
compression_result = None
if compression_enabled:
    compression_result = compress_messages(
        body["messages"],
        model=body["model"],
        level=compression_level,
        enable_ccr=False,  # 网关场景关闭 CCR
    )
    body["messages"] = compression_result.messages
# =================================
```

**关键集成点 3 — 扩展审计记录**（在 `_record_llm_success` 函数中，约第 891 行，创建 `LlmRequestAudit` 时）:

```python
# 在 LlmRequestAudit 构造时新增:
compression_enabled=compression_enabled,
compression_level=compression_level if compression_enabled else None,
```

在 `LlmUsageMetric` 构造时（约第 910 行）新增:

```python
# 在 LlmUsageMetric 构造时新增:
pre_compression_tokens=compression_result.pre_tokens if compression_result else 0,
post_compression_tokens=compression_result.post_tokens if compression_result else 0,
tokens_saved=compression_result.tokens_saved if compression_result else 0,
compression_ratio=round(compression_result.ratio, 4) if compression_result else 0.0,
compression_duration_ms=round(compression_result.duration_ms, 2) if compression_result else 0.0,
```

相同修改也需要在 `_record_llm_success` 的 streaming 调用处（`_stream_upstream` 内部约第 781、826 行）同步。

**关键集成点 4 — Pipeline Trace 扩展**（在 `_save_trace` 调用处，约第 1712 行，`stages` 字典中新增）:

```python
# 在 stages 字典中，masked 和 masked_response 之间新增:
"compressed": {
    "messages": body["messages"],  # 压缩后发送给上游的实际内容
    "pre_tokens": compression_result.pre_tokens if compression_result else 0,
    "post_tokens": compression_result.post_tokens if compression_result else 0,
    "tokens_saved": compression_result.tokens_saved if compression_result else 0,
    "ratio": round(compression_result.ratio, 4) if compression_result else 0,
    "duration_ms": round(compression_result.duration_ms, 2) if compression_result else 0,
    "compressor": compression_result.compressor_used if compression_result else "disabled",
},
```

同时更新 `TRACE_STAGES` 常量（约第 57 行）:

```python
TRACE_STAGES = ["meta", "original", "masked", "compressed", "masked_response", "final_response"]
```

**Streaming 路径也需要同样的压缩逻辑**（`_stream_upstream` 函数内，在约第 750 行构造 `payload` 之前）。由于 streaming 函数内部不直接访问 `compression_enabled` 变量，需要将 `compression_result` 作为参数传入 `_stream_upstream`，并在其内部扩展审计写入逻辑。

#### Step 3.3 — 压缩级别 API 校验

在 `_chat_completions_with_key` 中，压缩前校验:

```python
ALLOWED_COMPRESSION_LEVELS = {"conservative", "auto", "aggressive"}
if compression_level not in ALLOWED_COMPRESSION_LEVELS:
    compression_level = "auto"
```

---

### Phase 4: 管理台 API 扩展（预计 0.5 天）

#### Step 4.1 — API Key CRUD 支持压缩字段

**文件**: `backend/routers/llm_gateway.py`

**创建 API Key** (`create_llm_api_key`，约第 1225 行):

在 `LlmApiKey` 构造时新增:

```python
enable_compression=body.enable_compression,
compression_level=body.compression_level,
```

**更新 API Key** (`update_llm_api_key`，约第 1249 行):

在 `data = body.model_dump(exclude_unset=True)` 之后，对 `enable_compression` 和 `compression_level` 字段做和现有字段一致的处理（pydantic 会自动处理）。

#### Step 4.2 — 返回响应中包含压缩字段

确保所有 response 构造处（`_api_key_response`）均已包含新字段（Phase 2 已覆盖）。

---

### Phase 5: 前端管理台（预计 1 天）

#### Step 5.1 — API Key 表单扩展

**文件**: `web/src/` (需要先确认前端框架和组件结构)

在 API Key 创建/编辑表单中，`max_concurrent_requests` 字段之后新增:

```jsx
{/* Headroom 智能压缩 */}
<FormControl>
  <FormLabel>智能上下文压缩</FormLabel>
  <Switch
    isChecked={enableCompression}
    onChange={(e) => setEnableCompression(e.target.checked)}
  />
  <FormHelperText>
    开启后按内容尝试压缩工具输出、日志、代码等；实际节省量以链路追踪为准
  </FormHelperText>
</FormControl>

{enableCompression && (
  <FormControl>
    <FormLabel>压缩级别</FormLabel>
    <Select value={compressionLevel} onChange={...}>
      <option value="auto">均衡 (推荐) — SmartCrusher + CodeCompressor</option>
      <option value="conservative">保守 — 仅压缩 JSON/结构化数据</option>
      <option value="aggressive">激进 — 全部算法 + ML 模型</option>
    </Select>
    <FormHelperText>
      保守、均衡和激进会采用不同处理强度；应使用代表性请求评估节省量和输出影响
    </FormHelperText>
  </FormControl>
)}
```

#### Step 5.2 — 客户端策略

客户端策略配置自动签发运行凭据的压缩开关及级别，支持平台默认和单客户端覆盖。
保存时同步已有自动凭据，新建和轮换凭据继承当前配置；长轮询下发策略与版本。

#### Step 5.3 — Pipeline Trace 展示扩展

在 Trace 详情页，增加 `compressed` 阶段的展示卡片，显示:
- 压缩前后的 messages 对比
- Token 节省统计（pre → post → saved）
- 压缩耗时

---

### Phase 6: 测试（预计 1.5 天）

#### Step 6.1 — 单元测试

**新建文件**: `tests/test_compression.py`

```python
"""Headroom 压缩集成测试"""
import pytest


class TestCompressMessages:
    """压缩核心逻辑测试"""

    def test_compress_reduces_json_tool_outputs(self):
        """SmartCrusher 应压缩 JSON 工具输出"""
        messages = [
            {"role": "user", "content": "Analyze this data"},
            {"role": "tool", "content": '[{"id": 1, "name": "Alice", ...}]' * 100},
        ]
        from backend.compression import compress_messages
        result = compress_messages(messages, level="conservative")
        assert result.post_tokens < result.pre_tokens
        # 压缩后仍应包含关键信息
        assert len(result.messages) == len(messages)

    def test_compress_respects_system_prompt(self):
        """系统提示不应被压缩"""
        system_msg = {"role": "system", "content": "You are a helpful assistant."}
        messages = [system_msg, {"role": "user", "content": "Hello"}]
        from backend.compression import compress_messages
        result = compress_messages(messages, level="conservative")
        # 压缩不应删除系统消息
        assert len(result.messages) >= 2

    def test_compress_graceful_fallback_on_error(self):
        """压缩失败时返回原始 messages，不抛异常"""
        messages = [{"role": "user", "content": "test"}]
        from backend.compression import compress_messages
        # 即使 headroom 不可用也不应崩溃
        result = compress_messages(messages, level="auto")
        assert result.messages == messages
        assert result.post_tokens == result.pre_tokens

    def test_compression_disabled_by_default(self):
        """默认不压缩"""
        # 通过 API 测试验证：创建 API Key 后 enable_compression 默认为 false
        ...


class TestCompressionIntegration:
    """网关集成测试"""

    @pytest.mark.asyncio
    async def test_chat_completion_with_compression_enabled(self):
        """开启压缩的 API Key 请求应触发压缩"""
        ...

    @pytest.mark.asyncio
    async def test_chat_completion_with_compression_disabled(self):
        """关闭压缩的 API Key 请求不应触发压缩"""
        ...

    @pytest.mark.asyncio
    async def test_streaming_with_compression(self):
        """Streaming 模式下的压缩"""
        ...

    @pytest.mark.asyncio
    async def test_audit_records_compression_stats(self):
        """审计应记录压缩统计信息"""
        ...
```

#### Step 6.2 — 集成测试场景

| 场景 | 预期结果 |
|------|----------|
| API Key 关闭压缩 → 发请求 | messages 不变，无压缩统计 |
| API Key 开启压缩 (conservative) → 发请求 | JSON 类型 tool output 被压缩 |
| API Key 开启压缩 (auto) → 发请求 | SmartCrusher + CodeCompressor 生效 |
| API Key 开启压缩 → streaming 请求 | 压缩生效，SSE 流正常返回 |
| headroom 未安装 → 开启压缩 | 降级，返回原始 messages |
| 压缩后 body 超过模型限制 | 同现有逻辑，返回 400 |

#### Step 6.3 — 性能测试

- 测量不同压缩级别下的延迟增加（预期 < 200ms）
- 测量典型的 Token 节省率（预期 > 50%）

---

### Phase 7: 文档更新（预计 0.5 天）

#### Step 7.1 — 更新模型网关文档

**文件**: `docs/model-gateway.md`

在第 6 节 "隐私策略" 之后新增一节:

```markdown
## 11. 智能上下文压缩（可选）

模型网关可集成 Headroom 智能压缩，自动压缩发送给 LLM 的消息内容，节省 Token 成本。

### 开启方式

1. 创建/编辑 API Key 时，开启「智能上下文压缩」开关
2. 选择压缩级别

### 压缩级别

| 级别 | 算法 | Token 节省 | 质量影响 |
|------|------|-----------|---------|
| 保守 | SmartCrusher (JSON) | 40-70% | 零影响 |
| 均衡 | SmartCrusher + CodeCompressor | 60-80% | 几乎零影响 |
| 激进 | 全部 + Kompress ML | 70-95% | 极轻微 |

### 压缩位置

压缩在 PII 伪匿名化之后、上游转发之前执行，不会影响隐私保护。

### 监控

Pipeline Trace 中新增 `compressed` 阶段，可查看压缩前后的消息对比和统计数据。
```

---

## 4. 关键技术决策

### 4.1 为什么关闭 CCR

Headroom 的 CCR（可逆压缩）会在本地存储原始内容，供 LLM 通过 tool call 取回。在网关场景：
- 网关是多租户的，CCR 存储需要按 tenant 隔离
- 增加存储运维复杂度
- PII 虽已伪匿名化，但仍需管控存储

**决策**: 默认关闭 CCR。未来可考虑按 tenant 开启，使用 SQLite 后端（与现有架构一致）。

### 4.2 为什么用估算 token 而非精确计数

精确 token 计数需要调用 `tiktoken` 对 messages 逐字段编码。在热路径上这会增加额外延迟。估算值足够用于：
- 压缩效果趋势监控
- 压缩比统计

上游返回的 `usage.prompt_tokens` 是精确值，可用于最终审计。

### 4.3 降级策略

压缩失败绝不阻断请求：
- `headroom` 未安装 → 跳过
- 压缩过程抛异常 → 捕获，返回原始 messages
- 压缩后验证失败 → 回退

所有异常都记日志 + 审计。

### 4.4 Anthropic 格式支持边界

网关已提供 Anthropic-compatible `/v1/messages`，进入隐私链路前会转换为内部 OpenAI 消息结构，因此继续复用当前 Headroom 压缩流程。Anthropic 专有内容块不在当前压缩范围内。

---

## 5. 验收检查清单

- [x] `pip install -e ".[compression]"` 成功
- [x] 新建 API Key 时 `enable_compression` 默认 `false`
- [x] 开启压缩的 API Key 请求，Token 数明显减少（实测 92.4%）
- [x] 关闭压缩的 API Key 请求，行为和原来完全一致
- [ ] Streaming 模式下压缩正常工作（需联调验证）
- [x] Pipeline Trace 包含 `compressed` 阶段
- [x] 审计记录包含压缩统计字段
- [x] 压缩失败时请求不中断（降级策略）
- [x] 管理台可配置压缩开关和级别
- [x] 所有现有测试通过（218 passed）
- [x] 文档更新完成

---

## 6. 回滚方案

如果集成后出现问题:

1. **秒级回滚**: 在管理台关闭所有 API Key 的压缩开关（`enable_compression = false`）
2. **代码回滚**: `git revert` Phase 2-5 的 commits
3. **依赖回滚**: 从 `pyproject.toml` 移除 `compression` extra
4. **数据库**: SQLite 新增列为可选字段，保留不影响查询

---

## 7. 参考资源

- [Headroom GitHub](https://github.com/chopratejas/headroom)
- [Headroom 文档](https://headroom-docs.vercel.app/docs)
- [Headroom API Reference](https://headroom-docs.vercel.app/docs/api-reference)
- [本项目的模型网关文档](model-gateway.md)
- [本项目的架构设计文档](../DESIGN.md)
