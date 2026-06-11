"""Headroom 智能压缩集成模块

在 PII 伪匿名化之后、上游转发之前对 messages 进行压缩。
压缩失败绝不阻断请求，降级返回原始 messages。

Version: v2 (transforms + diagnostics)

Usage:
    from backend.compression import compress_messages

    result = compress_messages(messages, model="gpt-4o", level="auto")
    body["messages"] = result.messages
"""

from __future__ import annotations

__version__ = "2"

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 允许的压缩级别
ALLOWED_COMPRESSION_LEVELS = frozenset({"conservative", "auto", "aggressive"})


@dataclass
class CompressionResult:
    """压缩结果"""

    messages: list[dict[str, Any]]
    pre_tokens: int = 0
    post_tokens: int = 0
    tokens_saved: int = 0
    ratio: float = 0.0
    duration_ms: float = 0.0
    transforms_applied: list[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        """压缩是否实际生效"""
        return self.tokens_saved > 0


def compress_messages(
    messages: list[dict[str, Any]],
    *,
    model: str = "gpt-4o",
    level: str = "auto",
) -> CompressionResult:
    """对 messages 数组进行智能压缩。

    降级策略：压缩失败或 headroom 不可用时返回原始 messages，
    绝不阻断请求。

    Args:
        messages: 已伪匿名化的 messages 列表。
        model: 目标模型名，用于 token 计数和策略选择。
        level: 压缩级别。
            - "conservative": 轻量级 JSON/结构压缩
            - "auto": SmartCrusher + ContentRouter 自动选择（推荐）
            - "aggressive": 全部算法，含用户消息压缩

    Returns:
        CompressionResult 包含压缩后 messages 和统计信息。
    """
    if level not in ALLOWED_COMPRESSION_LEVELS:
        logger.warning("Unknown compression level %r, falling back to auto", level)
        level = "auto"

    try:
        from headroom import compress  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("headroom not installed, skipping compression")
        return CompressionResult(messages=messages)

    start = time.perf_counter()

    try:
        kwargs: dict[str, Any] = {}

        if level == "conservative":
            # 仅压缩 tool 输出等结构化内容，不碰用户消息
            kwargs["compress_user_messages"] = False
            kwargs["target_ratio"] = 0.7  # 保留 70%，较保守
        elif level == "aggressive":
            # 全部算法 + 用户消息也可压缩
            kwargs["compress_user_messages"] = True
            kwargs["target_ratio"] = 0.3  # 压缩到 30%，较激进
        # level == "auto": 使用 Headroom 默认策略

        # headroom 用 model 参数选择分词器做 token 计数，非 OpenAI 模型会尝试
        # 从 HuggingFace 下载对应分词器（内网不可用）。token 计数不影响压缩效果，
        # 统一用 gpt-4o 走 tiktoken 本地分词，避免网络依赖
        result = compress(messages, model="gpt-4o", **kwargs)

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Compression complete: %d→%d tokens (%.1f%%, %.0fms, level=%s, transforms=%s)",
            result.tokens_before,
            result.tokens_after,
            result.compression_ratio * 100 if result.compression_ratio else 0,
            elapsed_ms,
            level,
            result.transforms_applied,
        )

        # 诊断日志：当压缩未生效时，分析消息结构帮助排查
        if result.tokens_saved == 0 and result.tokens_before > 100:
            # 统计各 role 的消息数量和大小
            role_stats: dict[str, dict[str, int]] = {}
            for i, msg in enumerate(messages):
                role = str(msg.get("role", "unknown"))
                content = str(msg.get("content", ""))
                if role not in role_stats:
                    role_stats[role] = {"count": 0, "total_chars": 0, "max_chars": 0}
                role_stats[role]["count"] += 1
                role_stats[role]["total_chars"] += len(content)
                role_stats[role]["max_chars"] = max(role_stats[role]["max_chars"], len(content))
            logger.info(
                "Compression skipped by ContentRouter — messages breakdown: %s, transforms: %s",
                {r: f"{s['count']}msgs/{s['total_chars']}chars (max {s['max_chars']})" for r, s in role_stats.items()},
                result.transforms_applied,
            )

        # 类型安全：确保返回 list[dict]
        compressed_messages: list[dict[str, Any]]
        if isinstance(result.messages, list):
            compressed_messages = list(result.messages)
        else:
            compressed_messages = [dict(m) if isinstance(m, dict) else {"content": str(m)} for m in result.messages]  # type: ignore[union-attr]

        return CompressionResult(
            messages=compressed_messages,
            pre_tokens=result.tokens_before,
            post_tokens=result.tokens_after,
            tokens_saved=result.tokens_saved,
            ratio=round(result.compression_ratio, 4) if result.compression_ratio else 0.0,
            duration_ms=round(elapsed_ms, 2),
            transforms_applied=list(result.transforms_applied) if result.transforms_applied else [],
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            "Compression failed (%.0fms, level=%s): %s — falling back to uncompressed",
            elapsed_ms,
            level,
            exc,
        )
        return CompressionResult(
            messages=messages,
            duration_ms=round(elapsed_ms, 2),
        )
