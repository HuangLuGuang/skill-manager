from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import uuid
import socket
import uuid
from base64 import b64decode, b64encode, urlsafe_b64encode
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from agent_manager.security_redaction import (
    is_sensitive_key as is_shared_sensitive_key,
)
from agent_manager.security_redaction import (
    normalized_key as shared_normalized_key,
)
from agent_manager.security_redaction import (
    redact_sensitive_text,
)

from .api_errors import ApiError
from .config import settings

ALLOWED_TARGET_SCHEMES = {"http", "https", "ws", "wss"}
FORBIDDEN_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}
FORBIDDEN_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.google.internal.",
    "instance-data",
    "instance-data.ec2.internal",
}
SECURITY_SEVERITIES = ("info", "low", "medium", "high", "critical")
FINDING_STATUSES = ("open", "accepted", "resolved", "false_positive")
TASK_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "timed_out", "blocked")
TASK_ACTIVE_STATUSES = ("pending", "running")
SUPPORTED_AGENT_PROVIDER_TYPES = (
    "dify",
    "coze",
    "coze-com",
    "openai",
    "deepseek",
    "fireworks",
    "groq",
    "litellm",
    "localai",
    "mistral",
    "ollama",
    "openrouter",
    "perplexity",
    "togetherai",
    "anthropic",
    "google",
    "cohere",
    "huggingface",
    "replicate",
    "http",
    "websocket",
)
AGENT_SCAN_SKILLS = (
    "data-leakage-detection",
    "tool-abuse-detection",
    "indirect-injection-detection",
    "authorization-bypass-detection",
    "web-exfiltration-detection",
    "agentic-supply-chain-detection",
    "unexpected-code-execution-detection",
    "inter-agent-comm-security-detection",
    "cascading-failure-detection",
    "human-agent-trust-exploit-detection",
)
MCP_GATEWAY_TARGET_TYPE = "mcp_gateway"
SECURITY_ASSET_TYPES = ("agent", "mcp", "llm", "ai_infrastructure")
SECURITY_CONNECTOR_TYPES = (
    "dify",
    "coze",
    "openai_compatible",
    "custom_http",
    "websocket",
    "mcp_gateway",
    "mcp_streamable_http",
    "mcp_source",
    "network_endpoint",
)
ASSET_CONNECTOR_TYPES = {
    "agent": {"dify", "coze", "openai_compatible", "custom_http", "websocket"},
    "mcp": {"mcp_gateway", "mcp_streamable_http", "mcp_source"},
    "llm": {"openai_compatible"},
    "ai_infrastructure": {"network_endpoint"},
}
SUPPORTED_SCAN_KINDS = (
    "control_plane_validation",
    "agent_risk_scan",
    "mcp_risk_scan",
    "llm_redteam_scan",
    "ai_infrastructure_vulnerability_scan",
    "dify_asset_inventory",
)
ASSET_SCAN_KINDS = {
    "agent": {"control_plane_validation", "agent_risk_scan", "dify_asset_inventory"},
    "mcp": {"mcp_risk_scan"},
    "llm": {"llm_redteam_scan"},
    "ai_infrastructure": {"ai_infrastructure_vulnerability_scan"},
}
SECURITY_CREDENTIAL_PURPOSES = (
    "agent_runtime",
    "dify_app_api",
    "dify_console_api",
    "dify_knowledge_api",
    "mcp_discovery",
)


def validate_dify_inventory_target_config(config: dict[str, Any], *, require_complete: bool = False) -> dict[str, Any]:
    normalized = validate_agent_target_config("dify", config, require_complete=False)
    # Preserve provider-specific, non-secret fields used by existing Dify Agent
    # scans. validate_agent_target_config already rejects credentials and unsafe
    # headers; this validator owns only the additive inventory fields below.
    for name in ("app_id", "workspace_id"):
        value = str(normalized.get(name) or "").strip()
        if require_complete and not value:
            raise ApiError(
                422, f"dify_inventory.{name}_required",
                f"Dify 资产采集必须配置 {name}", f"Dify inventory requires {name}",
            )
        if value:
            if len(value) > 128:
                raise ApiError(422, "dify_inventory.target_config_invalid", "Dify 标识过长", "Dify identifier is too long")
            normalized[name] = value
    console_base_url = str(normalized.get("console_base_url") or "").strip().rstrip("/")
    if require_complete and not console_base_url:
        raise ApiError(
            422, "dify_inventory.console_base_url_required",
            "Dify 资产采集必须配置 Console Base URL", "Dify inventory requires a Console Base URL",
        )
    if console_base_url:
        parsed = urlsplit(console_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ApiError(
                422, "dify_inventory.console_base_url_invalid",
                "Dify Console Base URL 无效", "The Dify Console Base URL is invalid",
            )
        normalized["console_base_url"] = console_base_url
    bindings = normalized.get("mcp_bindings", [])
    if not isinstance(bindings, list) or len(bindings) > 100:
        raise ApiError(422, "dify_inventory.mcp_bindings_invalid", "MCP 映射配置无效", "MCP bindings are invalid")
    seen: set[str] = set()
    clean_bindings = []
    for item in bindings:
        if not isinstance(item, dict):
            raise ApiError(422, "dify_inventory.mcp_bindings_invalid", "MCP 映射配置无效", "MCP bindings are invalid")
        provider_id = str(item.get("provider_id") or "").strip()
        server_id = item.get("server_id")
        if not provider_id or len(provider_id) > 256 or isinstance(server_id, bool) or not isinstance(server_id, int) or server_id < 1 or provider_id in seen:
            raise ApiError(422, "dify_inventory.mcp_bindings_invalid", "MCP 映射配置无效", "MCP bindings are invalid")
        seen.add(provider_id)
        clean_bindings.append({"provider_id": provider_id, "server_id": server_id})
    normalized["mcp_bindings"] = clean_bindings
    knowledge_bindings = normalized.get("knowledge_bindings", [])
    if not isinstance(knowledge_bindings, list) or len(knowledge_bindings) > 500:
        raise ApiError(422, "dify_inventory.knowledge_bindings_invalid", "知识库引用绑定无效", "Knowledge reference bindings are invalid")
    clean_knowledge_bindings = []
    seen_references: dict[str, str] = {}
    for item in knowledge_bindings:
        if not isinstance(item, dict):
            raise ApiError(422, "dify_inventory.knowledge_bindings_invalid", "知识库引用绑定无效", "Knowledge reference bindings are invalid")
        reference = str(item.get("dsl_reference") or "").strip()
        dataset_id = str(item.get("dataset_id") or "").strip()
        try:
            normalized_dataset_id = str(uuid.UUID(dataset_id))
        except (ValueError, AttributeError):
            raise ApiError(422, "dify_inventory.knowledge_bindings_invalid", "知识库引用绑定必须使用有效 Dataset UUID", "Knowledge bindings require a valid Dataset UUID") from None
        if not reference or len(reference) > 512:
            raise ApiError(422, "dify_inventory.knowledge_bindings_invalid", "知识库引用绑定无效", "Knowledge reference bindings are invalid")
        previous = seen_references.get(reference)
        if previous and previous != normalized_dataset_id:
            raise ApiError(422, "dify_inventory.knowledge_bindings_invalid", "同一 DSL 引用不能绑定多个 Dataset", "A DSL reference cannot bind to multiple Datasets")
        if not previous:
            seen_references[reference] = normalized_dataset_id
            clean_knowledge_bindings.append({"dsl_reference": reference, "dataset_id": normalized_dataset_id})
    normalized["knowledge_bindings"] = clean_knowledge_bindings
    redirect_hosts = normalized.get("allowed_redirect_hosts", [])
    if not isinstance(redirect_hosts, list) or len(redirect_hosts) > 16 or any(
        not isinstance(value, str) or not value.strip() or len(value) > 253 or "/" in value for value in redirect_hosts
    ):
        raise ApiError(422, "dify_inventory.redirect_allowlist_invalid", "重定向主机白名单无效", "Redirect host allowlist is invalid")
    normalized["allowed_redirect_hosts"] = list(dict.fromkeys(value.strip().lower() for value in redirect_hosts))
    return normalized
SECURITY_TARGET_ENVIRONMENTS = ("sandbox", "test", "staging", "production")
SECURITY_SCAN_CAPABILITIES = (
    "conversation",
    "multi_turn",
    "tool_read",
    "tool_write",
    "network_egress",
    "file_read",
    "file_write",
    "code_execution",
    "persistent_memory",
)
# Keep legacy targets and policies runnable after the additive P6-01 migration.
DEFAULT_SECURITY_SCAN_CAPABILITIES = SECURITY_SCAN_CAPABILITIES
# Backward-compatible import name retained for P1 callers and tests.
SUPPORTED_P1_SCAN_KINDS = SUPPORTED_SCAN_KINDS
WORKER_ENVELOPE_ALGORITHM = "x25519-hkdf-sha256-aesgcm-v1"
_SAFE_RESPONSE_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[(?:\d+|-1)\]|\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FORBIDDEN_CONFIG_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
_DANGEROUS_OBJECT_KEYS = {"__proto__", "constructor", "prototype"}
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(\\?[\"']?(?:authorization|api[_-]?key|token|password|secret)\\?[\"']?\s*[:=]\s*)"
        r"(\\?[\"'])(.*?)\2"
    ),
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[^\s,;\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)
_MCP_SECRET_VALUE_KEYS = {"const", "default", "enum", "example", "examples", "value"}


def legacy_target_classification(target_type: str) -> tuple[str, str]:
    value = str(target_type or "").strip().lower()
    if value == "mcp_gateway":
        return "mcp", "mcp_gateway"
    if value == "dify":
        return "agent", "dify"
    if value in {"coze", "coze-com"}:
        return "agent", "coze"
    if value == "http":
        return "agent", "custom_http"
    if value == "websocket":
        return "agent", "websocket"
    if value in SUPPORTED_AGENT_PROVIDER_TYPES:
        return "agent", "openai_compatible"
    raise ApiError(
        422,
        "agent_security.target_type_unsupported",
        "不支持的历史扫描目标接入类型",
        "Unsupported legacy scan target connector",
        params={"target_type": value},
    )


def validate_asset_connector(asset_type: str, connector_type: str) -> tuple[str, str]:
    asset = str(asset_type or "").strip().lower()
    connector = str(connector_type or "").strip().lower()
    if asset not in SECURITY_ASSET_TYPES:
        raise ApiError(
            422,
            "agent_security.asset_type_invalid",
            "扫描对象类型无效",
            "Invalid scan asset type",
            params={"asset_type": asset},
        )
    if connector not in SECURITY_CONNECTOR_TYPES or connector not in ASSET_CONNECTOR_TYPES[asset]:
        raise ApiError(
            422,
            "agent_security.asset_connector_mismatch",
            "扫描对象与接入方式不兼容",
            "The scan asset and connector types are incompatible",
            params={"asset_type": asset, "connector_type": connector},
        )
    return asset, connector


def legacy_target_type_for(asset_type: str, connector_type: str) -> str:
    asset, connector = validate_asset_connector(asset_type, connector_type)
    if connector in {"dify", "coze", "websocket", "mcp_gateway", "mcp_source"}:
        return connector
    if connector == "custom_http":
        return "http"
    if connector == "mcp_streamable_http":
        return "http"
    if connector in {"openai_compatible", "network_endpoint"}:
        return "openai" if asset in {"agent", "llm"} else "http"
    raise AssertionError("validated connector has no legacy mapping")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def new_resource_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()


def _secret_cipher() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(digest))


def protect_secret(value: str) -> str:
    if not value:
        raise ApiError(
            422,
            "agent_security.credential_secret_required",
            "凭证明文不能为空",
            "Credential secret is required",
        )
    return "enc:" + _secret_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def unprotect_secret(value: str | None) -> str | None:
    if not value or not value.startswith("enc:"):
        return None
    try:
        return _secret_cipher().decrypt(value[4:].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def validate_worker_public_key(value: str) -> tuple[str, str]:
    try:
        raw = b64decode(value, validate=True)
        X25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            422,
            "agent_security.worker_public_key_invalid",
            "Worker 公钥格式无效",
            "The worker public key is invalid",
        ) from exc
    if len(raw) != 32:
        raise ApiError(
            422,
            "agent_security.worker_public_key_invalid",
            "Worker 公钥格式无效",
            "The worker public key is invalid",
        )
    canonical = b64encode(raw).decode("ascii")
    return canonical, hashlib.sha256(raw).hexdigest()


def seal_secret_for_worker(
    secret: str,
    worker_public_key: str,
    *,
    worker_id: str,
    task_id: str,
    credential_id: str,
    expires_at: datetime,
) -> dict[str, str]:
    canonical_key, fingerprint = validate_worker_public_key(worker_public_key)
    recipient = X25519PublicKey.from_public_bytes(b64decode(canonical_key))
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(recipient)
    normalized_expiry = (
        expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
    )
    aad = f"{worker_id}|{task_id}|{credential_id}|{normalized_expiry.isoformat()}".encode()
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"agent-manager-security-worker-credential-v1",
    ).derive(shared)
    nonce = uuid.uuid4().bytes[:12]
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), aad)
    ephemeral_public = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "algorithm": WORKER_ENVELOPE_ALGORITHM,
        "ephemeral_public_key": b64encode(ephemeral_public).decode("ascii"),
        "nonce": b64encode(nonce).decode("ascii"),
        "ciphertext": b64encode(ciphertext).decode("ascii"),
        "aad": b64encode(aad).decode("ascii"),
        "recipient_fingerprint": fingerprint,
        "expires_at": normalized_expiry.isoformat(),
    }


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * min(len(value) - 8, 24)}{value[-4:]}"


def sanitize_untrusted_text(value: str, *, max_length: int = 16_384) -> str:
    text = str(value).replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(2)}"
                if match.lastindex == 3
                else f"{match.group(1)}[REDACTED]"
                if match.lastindex
                else "[REDACTED]"
            ),
            text,
        )
    text = html.escape(html.unescape(text), quote=False)
    if len(text) > max_length:
        text = text[:max_length] + "…[truncated]"
    return text


def sanitize_untrusted_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "[depth-limited]"
    if isinstance(value, str):
        return sanitize_untrusted_text(value, max_length=8_192)
    if isinstance(value, list):
        return [sanitize_untrusted_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in list(value.items())[:100]:
            safe_key = sanitize_untrusted_text(str(key), max_length=128)
            if safe_key.lower() in _DANGEROUS_OBJECT_KEYS:
                safe_key = f"[blocked-key:{safe_key}]"
            sanitized[safe_key] = sanitize_untrusted_value(item, depth=depth + 1)
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_untrusted_text(str(value), max_length=1_024)


def sanitize_mcp_metadata_text(value: str, *, max_length: int = 8_192) -> tuple[str, bool]:
    raw = str(value)
    # Use the common secret scrubber without truncating first, then add MCP-specific
    # PII/token families before applying the storage bound.
    safe = sanitize_untrusted_text(raw, max_length=max((len(raw) * 6) + 32, max_length + 32))
    safe = redact_sensitive_text(safe)
    truncated = len(safe) > max_length
    if truncated:
        safe = safe[:max_length] + "…[truncated]"
    return safe, truncated


def sanitize_mcp_metadata_value(value: Any, *, max_depth: int = 8, max_items: int | None = 100) -> tuple[Any, dict[str, int]]:
    stats = {
        "truncated_strings": 0,
        "dropped_items": 0,
        "depth_limited": 0,
        "redacted_sensitive_values": 0,
    }

    def normalized_key(value: Any) -> str:
        return shared_normalized_key(value)

    def is_sensitive_key(value: Any) -> bool:
        return is_shared_sensitive_key(value)

    def walk(item: Any, *, depth: int, sensitive_context: bool = False, force_redact: bool = False) -> Any:
        if force_redact:
            stats["redacted_sensitive_values"] += 1
            return "[REDACTED]"
        if depth >= max_depth:
            stats["depth_limited"] += 1
            return "[depth-limited]"
        if isinstance(item, str):
            safe, truncated = sanitize_mcp_metadata_text(item)
            stats["truncated_strings"] += int(truncated)
            return safe
        if isinstance(item, list):
            stats["dropped_items"] += max(0, len(item) - max_items) if max_items is not None else 0
            return [walk(value, depth=depth + 1, sensitive_context=sensitive_context) for value in item[:max_items]]
        if isinstance(item, dict):
            stats["dropped_items"] += max(0, len(item) - max_items) if max_items is not None else 0
            sanitized: dict[str, Any] = {}
            for raw_key, child in list(item.items())[:max_items]:
                raw_key_text = str(raw_key)
                safe_key, key_truncated = sanitize_mcp_metadata_text(raw_key_text, max_length=128)
                stats["truncated_strings"] += int(key_truncated)
                if safe_key.lower() in _DANGEROUS_OBJECT_KEYS:
                    safe_key = f"[blocked-key:{safe_key}]"
                key = normalized_key(raw_key)
                key_is_sensitive = is_sensitive_key(raw_key)
                redact_child = (key_is_sensitive and not isinstance(child, (dict, list))) or (
                    sensitive_context and key in _MCP_SECRET_VALUE_KEYS
                )
                if safe_key in sanitized:
                    stats["dropped_items"] += 1
                sanitized[safe_key] = walk(
                    child,
                    depth=depth + 1,
                    sensitive_context=sensitive_context or key_is_sensitive,
                    force_redact=redact_child,
                )
            return sanitized
        if item is None or isinstance(item, (bool, int, float)):
            return item
        safe, truncated = sanitize_mcp_metadata_text(str(item), max_length=1_024)
        stats["truncated_strings"] += int(truncated)
        return safe

    return walk(value, depth=0), stats


def _find_secret_config_paths(value: Any, secret_keys: set[str], *, path: str = "config") -> list[str]:
    if isinstance(value, dict):
        matches: list[str] = []
        for raw_key, item in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if key.lower() in secret_keys:
                matches.append(child_path)
            matches.extend(_find_secret_config_paths(item, secret_keys, path=child_path))
        return matches
    if isinstance(value, list):
        matches = []
        for index, item in enumerate(value):
            matches.extend(_find_secret_config_paths(item, secret_keys, path=f"{path}[{index}]"))
        return matches
    return []


def validate_agent_target_config(
    target_type: str,
    config: dict[str, Any],
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    if target_type == MCP_GATEWAY_TARGET_TYPE:
        if not isinstance(config, dict):
            raise ApiError(
                422, "agent_security.target_config_invalid", "目标配置必须是对象", "Target config must be an object"
            )
        if set(config) - {"gateway_id", "allow_insecure_transport"}:
            raise ApiError(
                422,
                "agent_security.mcp_target_config_invalid",
                "MCP Gateway 扫描目标只允许配置 gateway_id",
                "MCP Gateway scan targets only allow gateway_id configuration",
            )
        gateway_id = config.get("gateway_id")
        if isinstance(gateway_id, bool) or not isinstance(gateway_id, int) or gateway_id < 1:
            raise ApiError(
                422,
                "agent_security.mcp_gateway_id_invalid",
                "MCP Gateway ID 无效",
                "The MCP Gateway ID is invalid",
            )
        return {"gateway_id": gateway_id}
    if target_type not in SUPPORTED_AGENT_PROVIDER_TYPES:
        raise ApiError(
            422,
            "agent_security.target_type_unsupported",
            "扫描目标类型不在锁定版本支持范围内",
            "The scan target type is not supported by the locked upstream version",
            params={"target_type": target_type},
        )
    if not isinstance(config, dict):
        raise ApiError(
            422, "agent_security.target_config_invalid", "目标配置必须是对象", "Target config must be an object"
        )
    normalized = dict(config)
    secret_keys = {"apikey", "api_key", "authorization", "password", "secret", "token", "access_token"}
    secret_paths = _find_secret_config_paths(
        {key: value for key, value in normalized.items() if str(key).lower() != "headers"},
        secret_keys,
    )
    if secret_paths:
        raise ApiError(
            422,
            "agent_security.secret_config_forbidden",
            "认证信息必须使用目标凭据管理，不能写入普通配置",
            "Authentication secrets must use target credentials and cannot be stored in regular config",
            params={"paths": secret_paths[:20]},
        )
    if not isinstance(normalized.get("extra", {}), dict):
        raise ApiError(
            422,
            "agent_security.target_extra_invalid",
            "目标 extra 配置必须是对象",
            "Target extra config must be an object",
        )
    headers = normalized.get("headers", {})
    if not isinstance(headers, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()
    ):
        raise ApiError(
            422,
            "agent_security.target_headers_invalid",
            "目标请求头必须是字符串键值对象",
            "Target headers must be a string-to-string object",
        )
    forbidden = sorted(key for key in headers if key.lower() in _FORBIDDEN_CONFIG_HEADERS)
    if forbidden:
        raise ApiError(
            422,
            "agent_security.secret_header_forbidden",
            "认证信息必须使用目标凭据管理，不能写入普通配置",
            "Authentication secrets must use target credentials and cannot be stored in regular config",
            params={"headers": forbidden},
        )
    timeout_ms = int(normalized.get("timeout_ms", 30_000))
    if timeout_ms < 1_000 or timeout_ms > 120_000:
        raise ApiError(
            422,
            "agent_security.target_timeout_invalid",
            "目标超时必须在 1000 到 120000 毫秒之间",
            "Target timeout must be between 1000 and 120000 milliseconds",
        )
    normalized["timeout_ms"] = timeout_ms
    normalized["headers"] = headers
    endpoint = normalized.get("endpoint")
    if endpoint is not None:
        endpoint = str(endpoint)
        if not endpoint.startswith("/") or "://" in endpoint or ".." in endpoint:
            raise ApiError(
                422,
                "agent_security.target_endpoint_invalid",
                "目标 endpoint 必须是安全的相对路径",
                "The target endpoint must be a safe relative path",
            )
        normalized["endpoint"] = endpoint
    for field in ("session_request_path", "session_response_path"):
        value = str(normalized.get(field, "")).strip()
        if value and not _SAFE_RESPONSE_PATH.fullmatch(value):
            raise ApiError(
                422,
                "agent_security.session_path_invalid",
                "会话字段路径格式无效",
                "The session field path is invalid",
                params={"field": field},
            )
        if value:
            normalized.setdefault("extra", {})[field] = value

    if target_type == "http":
        method = str(normalized.get("method", "POST")).upper()
        if method not in {"POST", "PUT"}:
            raise ApiError(
                422,
                "agent_security.http_method_unsupported",
                "通用 HTTP Agent 只允许 POST 或 PUT",
                "Generic HTTP agents only support POST or PUT",
            )
        body = normalized.get("body", {"message": "{{prompt}}"})
        if "{{prompt}}" not in json_dumps(body):
            raise ApiError(
                422,
                "agent_security.prompt_placeholder_required",
                "通用 HTTP 请求体必须包含 {{prompt}} 占位符",
                "The generic HTTP request body must contain the {{prompt}} placeholder",
            )
        transform = str(normalized.get("transform_response", "")).strip()
        if require_complete and not transform:
            raise ApiError(
                422,
                "agent_security.response_transform_required",
                "通用 HTTP 目标必须配置响应转换路径",
                "Generic HTTP targets require a response transform path",
            )
        if transform and not _SAFE_RESPONSE_PATH.fullmatch(transform):
            raise ApiError(
                422,
                "agent_security.response_transform_invalid",
                "响应转换路径格式无效",
                "The response transform path is invalid",
            )
        normalized.update({"method": method, "body": body, "transform_response": transform})
    elif target_type == "websocket":
        template = normalized.get("message_template", {"message": "{{prompt}}"})
        if "{{prompt}}" not in json_dumps(template):
            raise ApiError(
                422,
                "agent_security.prompt_placeholder_required",
                "WebSocket 消息模板必须包含 {{prompt}} 占位符",
                "The WebSocket message template must contain the {{prompt}} placeholder",
            )
        normalized["message_template"] = template
    elif target_type in {"coze", "coze-com"} and require_complete:
        extra = normalized.get("extra", {})
        if not isinstance(extra, dict) or not str(extra.get("bot_id", "")).strip():
            raise ApiError(
                422,
                "agent_security.coze_bot_id_required",
                "Coze 目标必须配置 bot_id",
                "Coze targets require bot_id",
            )

    credential_header = str(normalized.get("credential_header", "X-API-Key")).strip()
    if any(char in credential_header for char in "\r\n:") or not credential_header:
        raise ApiError(
            422,
            "agent_security.credential_header_invalid",
            "凭据请求头名称无效",
            "The credential header name is invalid",
        )
    normalized["credential_header"] = credential_header
    credential_prefix = str(normalized.get("credential_prefix", ""))
    if len(credential_prefix) > 64 or any(char in credential_prefix for char in "\r\n"):
        raise ApiError(
            422,
            "agent_security.credential_prefix_invalid",
            "凭据前缀无效",
            "The credential prefix is invalid",
        )
    normalized["credential_prefix"] = credential_prefix
    return normalized


def _validate_nonsecret_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = config.get("headers", {})
    if not isinstance(headers, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()
    ):
        raise ApiError(
            422,
            "agent_security.target_headers_invalid",
            "目标请求头必须是字符串键值对象",
            "Target headers must be a string-to-string object",
        )
    forbidden = sorted(key for key in headers if key.lower() in _FORBIDDEN_CONFIG_HEADERS)
    secret_paths = _find_secret_config_paths(
        {key: value for key, value in config.items() if str(key).lower() != "headers"},
        {"apikey", "api_key", "authorization", "password", "secret", "token", "access_token"},
    )
    if forbidden or secret_paths:
        raise ApiError(
            422,
            "agent_security.secret_config_forbidden",
            "认证信息必须使用目标凭据管理，不能写入普通配置",
            "Authentication secrets must use target credentials and cannot be stored in regular config",
            params={"headers": forbidden, "paths": secret_paths[:20]},
        )
    return dict(headers)


def _validate_credential_binding(config: dict[str, Any]) -> tuple[str, str]:
    header = str(config.get("credential_header") or "Authorization").strip()
    prefix = str(config.get("credential_prefix") or "Bearer ")
    if (
        not header
        or len(header) > 128
        or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header)
        or len(prefix) > 128
        or "\r" in prefix
        or "\n" in prefix
    ):
        raise ApiError(
            422,
            "agent_security.target_headers_invalid",
            "目标凭据请求头配置无效",
            "The target credential header configuration is invalid",
        )
    return header, prefix


def validate_llm_target_config(config: dict[str, Any], *, require_complete: bool = False) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ApiError(422, "agent_security.target_config_invalid", "目标配置必须是对象", "Target config must be an object")
    allowed = {
        "model",
        "chat_completions_path",
        "api_protocol",
        "timeout_ms",
        "headers",
        "credential_header",
        "credential_prefix",
        "allow_insecure_transport",
    }
    extra = sorted(set(config) - allowed)
    if extra:
        raise ApiError(
            422,
            "agent_security.llm_target_config_invalid",
            "大模型目标包含不支持的配置字段",
            "The LLM target contains unsupported configuration fields",
            params={"fields": extra},
        )
    normalized = dict(config)
    normalized["headers"] = _validate_nonsecret_headers(normalized)
    model = str(normalized.get("model") or "").strip()
    if require_complete and not model:
        raise ApiError(
            422,
            "agent_security.llm_target_required",
            "大模型目标必须配置模型名称",
            "The LLM target requires a model name",
        )
    normalized["model"] = model
    path = str(normalized.get("chat_completions_path") or "/v1/chat/completions").strip()
    if not path.startswith("/") or "://" in path or ".." in path:
        raise ApiError(
            422,
            "agent_security.llm_target_config_invalid",
            "Chat Completions Path 必须是安全的相对路径",
            "Chat Completions Path must be a safe relative path",
        )
    normalized["chat_completions_path"] = path
    protocol = str(normalized.get("api_protocol") or "openai_chat_completions")
    if protocol != "openai_chat_completions":
        raise ApiError(
            422,
            "agent_security.llm_target_config_invalid",
            "第一版仅支持 OpenAI Chat Completions 协议",
            "The first release supports only OpenAI Chat Completions",
        )
    normalized["api_protocol"] = protocol
    timeout_ms = int(normalized.get("timeout_ms", 30_000))
    if timeout_ms < 1_000 or timeout_ms > 120_000:
        raise ApiError(
            422,
            "agent_security.target_timeout_invalid",
            "目标超时必须在 1000 到 120000 毫秒之间",
            "Target timeout must be between 1000 and 120000 milliseconds",
        )
    normalized["timeout_ms"] = timeout_ms
    normalized["credential_header"], normalized["credential_prefix"] = _validate_credential_binding(normalized)
    return normalized


def validate_infrastructure_target_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ApiError(422, "agent_security.target_config_invalid", "目标配置必须是对象", "Target config must be an object")
    allowed = {
        "endpoints",
        "headers",
        "timeout_ms",
        "credential_header",
        "credential_prefix",
        "allow_insecure_transport",
    }
    extra = sorted(set(config) - allowed)
    if extra:
        raise ApiError(
            422,
            "agent_security.infra_target_forbidden",
            "基础设施目标包含不支持的配置字段",
            "The infrastructure target contains unsupported configuration fields",
            params={"fields": extra},
        )
    normalized = dict(config)
    normalized["headers"] = _validate_nonsecret_headers(normalized)
    endpoints = normalized.get("endpoints")
    if endpoints is not None:
        if not isinstance(endpoints, list) or not endpoints or len(endpoints) > 32:
            raise ApiError(
                422,
                "agent_security.infra_target_required",
                "基础设施扫描需要 1 到 32 个明确服务 URL",
                "Infrastructure scans require between 1 and 32 explicit service URLs",
            )
        if any(not isinstance(value, str) or not value.strip() for value in endpoints):
            raise ApiError(
                422,
                "agent_security.infra_target_required",
                "基础设施扫描目标必须是非空 URL",
                "Infrastructure scan targets must be non-empty URLs",
            )
        normalized["endpoints"] = list(dict.fromkeys(value.strip() for value in endpoints))
    timeout_ms = int(normalized.get("timeout_ms", 30_000))
    if timeout_ms < 1_000 or timeout_ms > 120_000:
        raise ApiError(
            422,
            "agent_security.target_timeout_invalid",
            "目标超时必须在 1000 到 120000 毫秒之间",
            "Target timeout must be between 1000 and 120000 milliseconds",
        )
    normalized["timeout_ms"] = timeout_ms
    normalized["credential_header"], normalized["credential_prefix"] = _validate_credential_binding(normalized)
    return normalized


def validate_target_type_scheme(target_type: str, endpoint_url: str) -> None:
    if target_type == "mcp_source":
        if not endpoint_url.startswith("mcp-source://"):
            raise ApiError(422, "mcp_scan.source_invalid", "源码目标地址无效", "Invalid source target URL")
        return
    scheme = urlsplit(endpoint_url).scheme.lower()
    if target_type == MCP_GATEWAY_TARGET_TYPE:
        expected = {"mcp-gateway"}
    else:
        expected = {"ws", "wss"} if target_type == "websocket" else {"http", "https"}
    if scheme not in expected:
        raise ApiError(
            422,
            "agent_security.target_scheme_type_mismatch",
            "目标类型与 URL 协议不匹配",
            "The target type does not match the URL scheme",
            params={"target_type": target_type, "scheme": scheme},
        )


def normalize_cidrs(values: list[str]) -> list[str]:
    if len(values) > 32:
        raise ApiError(
            422,
            "agent_security.too_many_cidrs",
            "CIDR 白名单最多允许 32 项",
            "At most 32 CIDR allowlist entries are allowed",
        )
    normalized: list[str] = []
    for raw in values:
        try:
            network = ipaddress.ip_network(str(raw).strip(), strict=True)
        except ValueError as exc:
            raise ApiError(
                422,
                "agent_security.invalid_cidr",
                "CIDR 白名单格式无效",
                "The CIDR allowlist contains an invalid entry",
                params={"cidr": str(raw)},
            ) from exc
        minimum_prefix = 8 if network.version == 4 else 32
        if network.prefixlen < minimum_prefix:
            raise ApiError(
                422,
                "agent_security.cidr_too_broad",
                "CIDR 白名单范围过大",
                "The CIDR allowlist entry is too broad",
                params={"cidr": str(network), "minimum_prefix": minimum_prefix},
            )
        canonical = str(network)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _allowed_by_cidr(address: ipaddress.IPv4Address | ipaddress.IPv6Address, cidrs: list[str]) -> bool:
    return any(address in ipaddress.ip_network(value) for value in cidrs)


def _validate_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_cidrs: list[str],
) -> None:
    if address in FORBIDDEN_METADATA_IPS:
        raise ApiError(
            422,
            "agent_security.cloud_metadata_forbidden",
            "禁止使用云元数据地址作为扫描目标",
            "Cloud metadata addresses cannot be used as scan targets",
            params={"address": str(address)},
        )
    if address.is_global:
        return
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise ApiError(
            422,
            "agent_security.non_routable_address_forbidden",
            "环回、链路本地、组播、未指定或保留地址不能作为扫描目标",
            "Loopback, link-local, multicast, unspecified, and reserved addresses cannot be scan targets",
            params={"address": str(address)},
        )
    if address.is_private and _allowed_by_cidr(address, allowed_cidrs):
        return
    raise ApiError(
        422,
        "agent_security.private_address_forbidden",
        "内网、环回、链路本地或保留地址未被白名单授权",
        "Private, loopback, link-local, or reserved addresses are not allowlisted",
        params={"address": str(address)},
    )


def resolve_target_endpoint(
    endpoint_url: str,
    *,
    allowed_cidrs: list[str] | None = None,
    allow_insecure_transport: bool = False,
) -> list[str]:
    cidrs = normalize_cidrs(allowed_cidrs or [])
    parsed = urlsplit(endpoint_url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_TARGET_SCHEMES:
        raise ApiError(
            422,
            "agent_security.target_scheme_unsupported",
            "扫描目标只支持 HTTP、HTTPS、WebSocket 或安全 WebSocket",
            "Scan targets must use HTTP, HTTPS, WebSocket, or secure WebSocket",
            params={"scheme": scheme},
        )
    if scheme in {"http", "ws"} and not allow_insecure_transport:
        raise ApiError(
            422,
            "agent_security.insecure_transport_forbidden",
            "明文 HTTP/WebSocket 目标需要显式授权",
            "Plain HTTP/WebSocket targets require explicit authorization",
        )
    if parsed.username or parsed.password:
        raise ApiError(
            422,
            "agent_security.url_credentials_forbidden",
            "目标 URL 不能包含用户名或密码",
            "Target URLs cannot contain embedded credentials",
        )
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ApiError(422, "agent_security.target_host_required", "目标地址缺少主机名", "Target host is required")
    if hostname in FORBIDDEN_METADATA_HOSTS or hostname == "localhost":
        raise ApiError(
            422,
            "agent_security.target_host_forbidden",
            "禁止使用本机或云元数据主机名作为扫描目标",
            "Localhost and cloud metadata hostnames cannot be used as scan targets",
            params={"hostname": hostname},
        )

    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
        addresses = [literal]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ApiError(
                422,
                "agent_security.target_dns_failed",
                "扫描目标 DNS 解析失败",
                "The scan target could not be resolved",
                params={"hostname": hostname},
            ) from exc
        addresses = sorted({ipaddress.ip_address(record[4][0]) for record in records}, key=str)
    if not addresses:
        raise ApiError(
            422,
            "agent_security.target_dns_empty",
            "扫描目标没有可用的 DNS 记录",
            "The scan target has no usable DNS records",
            params={"hostname": hostname},
        )
    for address in addresses:
        _validate_address(address, cidrs)
    return [str(address) for address in addresses]


def verify_dns_pin(
    endpoint_url: str,
    expected_ips: list[str],
    *,
    allowed_cidrs: list[str] | None = None,
    allow_insecure_transport: bool = False,
) -> list[str]:
    current = resolve_target_endpoint(
        endpoint_url,
        allowed_cidrs=allowed_cidrs,
        allow_insecure_transport=allow_insecure_transport,
    )
    if set(current) != set(expected_ips):
        raise ApiError(
            409,
            "agent_security.dns_rebinding_detected",
            "目标 DNS 解析结果已变化，任务已阻止",
            "The target DNS resolution changed and the task was blocked",
            params={"expected": sorted(expected_ips), "actual": sorted(current)},
        )
    return current
