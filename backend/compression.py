"""Headroom 智能压缩集成模块

在 PII 伪匿名化之后、上游转发之前对 messages 进行压缩。
压缩失败绝不阻断请求，降级返回原始 messages。

Version: v3 (transforms + CCR-safe upstream content)

Usage:
    from backend.compression import compress_messages

    result = compress_messages(messages, model="gpt-4o", level="auto")
    body["messages"] = result.messages
"""

from __future__ import annotations

__version__ = "3"

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 允许的压缩级别
ALLOWED_COMPRESSION_LEVELS = frozenset({"conservative", "auto", "aggressive"})

_CCR_TOKEN_PATTERN = re.compile(r"<<ccr:[^>\r\n]+>>", re.IGNORECASE)
_CCR_HINT_SUFFIX_PATTERN = re.compile(
    r"\s*\[[^\[\]\r\n]*(?:Retrieve more|Retrieve original):\s*hash="
    r"[^\[\]\r\n]*\]\s*$",
    re.IGNORECASE,
)


def _sanitize_ccr_text(value: str) -> tuple[str, bool]:
    """Remove Headroom-only retrieval markers from upstream model content."""
    lowered = value.lower()
    if (
        "<<ccr:" not in lowered
        and "retrieve more: hash=" not in lowered
        and "retrieve original: hash=" not in lowered
    ):
        return value, False

    # SmartCrusher renders row-drop metadata as a synthetic final JSON item.
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        filtered = [
            item
            for item in parsed
            if not (isinstance(item, dict) and "_ccr_dropped" in item)
        ]
        if len(filtered) != len(parsed):
            return json.dumps(filtered, ensure_ascii=False, separators=(",", ":")), True

    cleaned = _CCR_HINT_SUFFIX_PATTERN.sub("", value)
    cleaned = _CCR_TOKEN_PATTERN.sub("", cleaned).strip()
    return cleaned, cleaned != value


def _content_is_meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return len(re.sub(r"\s+", "", value)) >= 32
    if isinstance(value, list):
        return any(_content_is_meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(
            key != "_ccr_dropped" and _content_is_meaningful(item)
            for key, item in value.items()
        )
    return value is not None


def _sanitize_ccr_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return _sanitize_ccr_text(value)
    if isinstance(value, list):
        changed = False
        result = []
        for item in value:
            if isinstance(item, dict) and "_ccr_dropped" in item:
                changed = True
                continue
            sanitized, item_changed = _sanitize_ccr_value(item)
            result.append(sanitized)
            changed = changed or item_changed
        return result, changed
    if isinstance(value, dict):
        changed = False
        result = {}
        for key, item in value.items():
            if key == "_ccr_dropped":
                changed = True
                continue
            sanitized, item_changed = _sanitize_ccr_value(item)
            result[key] = sanitized
            changed = changed or item_changed
        return result, changed
    return value, False


def _remove_unresolvable_ccr_markers(
    original_messages: list[dict[str, Any]],
    compressed_messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Strip CCR markers and restore content when only a marker remains."""
    sanitized_messages: list[dict[str, Any]] = []
    markers_removed = False
    used_fallback = False

    for index, message in enumerate(compressed_messages):
        sanitized_message = dict(message)
        sanitized_content, changed = _sanitize_ccr_value(message.get("content"))
        if changed:
            markers_removed = True
            if _content_is_meaningful(sanitized_content):
                sanitized_message["content"] = sanitized_content
            elif index < len(original_messages):
                sanitized_message = dict(original_messages[index])
                used_fallback = True
        sanitized_messages.append(sanitized_message)

    return sanitized_messages, markers_removed, used_fallback


def _count_messages(messages: list[dict[str, Any]]) -> int:
    from headroom.tokenizer import Tokenizer  # type: ignore[import-untyped]
    from headroom.tokenizers import get_tokenizer  # type: ignore[import-untyped]

    return Tokenizer(get_tokenizer("gpt-4o"), "gpt-4o").count_messages(messages)


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

        # 类型安全：确保返回 list[dict]
        compressed_messages: list[dict[str, Any]]
        if isinstance(result.messages, list):
            compressed_messages = list(result.messages)
        else:
            compressed_messages = [dict(m) if isinstance(m, dict) else {"content": str(m)} for m in result.messages]  # type: ignore[union-attr]

        # ``headroom.compress`` 的公开 CompressConfig 不包含 enable_ccr；
        # 传入同名 kwarg 会被静默忽略。网关又没有注入 headroom_retrieve，
        # 因此必须在发往远程模型前删除无法解析的 CCR 引用。若压缩结果只剩
        # 引用，则恢复该条原文，避免模型收到不可用上下文。
        compressed_messages, markers_removed, used_ccr_fallback = _remove_unresolvable_ccr_markers(
            messages,
            compressed_messages,
        )
        transforms_applied = list(result.transforms_applied) if result.transforms_applied else []
        if markers_removed:
            transforms_applied.append("gateway:ccr_marker_removed")
        if used_ccr_fallback:
            transforms_applied.append("gateway:ccr_fallback_original")

        post_tokens = _count_messages(compressed_messages) if markers_removed else result.tokens_after
        tokens_saved = max(0, result.tokens_before - post_tokens)
        compression_ratio = tokens_saved / result.tokens_before if result.tokens_before else 0.0

        logger.info(
            "Compression complete: %d→%d tokens (%.1f%%, %.0fms, level=%s, transforms=%s)",
            result.tokens_before,
            post_tokens,
            compression_ratio * 100,
            elapsed_ms,
            level,
            transforms_applied,
        )

        # 诊断日志：当压缩未生效时，分析消息结构帮助排查
        if tokens_saved == 0 and result.tokens_before > 100:
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
                transforms_applied,
            )

        return CompressionResult(
            messages=compressed_messages,
            pre_tokens=result.tokens_before,
            post_tokens=post_tokens,
            tokens_saved=tokens_saved,
            ratio=round(compression_ratio, 4) if compression_ratio else 0.0,
            duration_ms=round(elapsed_ms, 2),
            transforms_applied=transforms_applied,
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
