"""Headroom 压缩集成测试"""

import sys
import types

import pytest


class TestCompressMessages:
    """compress_messages 核心逻辑测试"""

    @pytest.mark.skip(reason="monkeypatching __import__ causes pytest recursion; fallback verified manually")
    def test_fallback_when_headroom_unavailable(self):
        """headroom 不可用时返回原始 messages"""
        pass

    def test_invalid_level_falls_back_to_auto(self):
        """无效压缩级别应回退到 auto"""
        from backend.compression import compress_messages

        messages = [{"role": "user", "content": "Hello"}]
        # 不存在的 level，不应崩溃
        result = compress_messages(messages, model="gpt-4o", level="invalid_level")
        assert result is not None
        assert isinstance(result.messages, list)

    def test_compression_result_attributes(self):
        """CompressionResult 属性正确"""
        from backend.compression import CompressionResult

        result = CompressionResult(
            messages=[{"role": "user", "content": "test"}],
            pre_tokens=100,
            post_tokens=50,
            tokens_saved=50,
            ratio=0.5,
            duration_ms=10.0,
            transforms_applied=["smart_crusher"],
        )
        assert result.applied is True
        assert result.tokens_saved == 50
        assert result.ratio == 0.5

    def test_compression_result_not_applied_when_zero_saved(self):
        """无节省时 applied 为 False"""
        from backend.compression import CompressionResult

        result = CompressionResult(
            messages=[{"role": "user", "content": "test"}],
            tokens_saved=0,
        )
        assert result.applied is False

    def test_empty_messages_handled(self):
        """空 messages 不崩溃"""
        from backend.compression import compress_messages

        result = compress_messages([], model="gpt-4o", level="auto")
        assert result.messages == []

    def test_system_message_preserved(self):
        """系统消息不被压缩破坏"""
        from backend.compression import compress_messages

        system_msg = {"role": "system", "content": "You are a helpful assistant."}
        messages = [system_msg, {"role": "user", "content": "Hello world"}]
        result = compress_messages(messages, model="gpt-4o", level="auto")
        # 至少应该保留相同数量的消息
        assert len(result.messages) >= 2

    def test_compress_with_conservative_level(self):
        """conservative 级别不崩溃"""
        from backend.compression import compress_messages

        messages = [{"role": "user", "content": "Test"}, {"role": "tool", "content": '{"key": "value"}' * 10}]
        result = compress_messages(messages, model="gpt-4o", level="conservative")
        assert isinstance(result.messages, list)
        assert len(result.messages) >= 2

    def test_allowed_levels_constant(self):
        """ALLOWED_COMPRESSION_LEVELS 包含预期值"""
        from backend.compression import ALLOWED_COMPRESSION_LEVELS

        assert "auto" in ALLOWED_COMPRESSION_LEVELS
        assert "conservative" in ALLOWED_COMPRESSION_LEVELS
        assert "aggressive" in ALLOWED_COMPRESSION_LEVELS

    def test_gateway_compression_disables_ccr_placeholders(self, monkeypatch):
        """网关压缩不应把内容替换成 ccr:* 占位符。"""
        calls = []

        class FakeResult:
            messages = [{"role": "user", "content": "full skill content"}]
            tokens_before = 100
            tokens_after = 90
            tokens_saved = 10
            compression_ratio = 0.1
            transforms_applied = ["fake"]

        def fake_compress(messages, **kwargs):
            calls.append(kwargs)
            return FakeResult()

        fake_headroom = types.SimpleNamespace(compress=fake_compress)
        monkeypatch.setitem(sys.modules, "headroom", fake_headroom)

        from backend.compression import compress_messages

        result = compress_messages([{"role": "user", "content": "full skill content"}], level="auto")

        assert result.messages[0]["content"] == "full skill content"
        assert calls
        assert calls[0]["enable_ccr"] is False


class TestCompressionIntegration:
    """网关集成测试 — 验证压缩流程不破坏请求链路"""

    @pytest.mark.skip(reason="integration placeholder; covered by tests/test_llm_gateway.py")
    def test_chat_completion_with_compression_disabled(self):
        """未开启压缩的请求与原来行为一致"""
        pass

    @pytest.mark.skip(reason="integration placeholder; covered by tests/test_llm_gateway.py")
    def test_chat_completion_headers_include_compression_info(self):
        """响应头应包含压缩相关信息"""
        pass
