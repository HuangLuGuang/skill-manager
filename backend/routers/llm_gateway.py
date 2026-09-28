import hashlib
import ipaddress
import json
import logging
import math
import random
import re
import secrets
import time
import uuid
from base64 import b64decode, b64encode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime, timedelta
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session, object_session
from sqlalchemy.exc import IntegrityError

from .. import auth, models, schemas
from ..anthropic_compat import (
    anthropic_stream_event_to_openai,
    anthropic_to_openai_request,
    anthropic_to_openai_response,
    openai_stream_to_anthropic,
    openai_to_anthropic_request,
    openai_to_anthropic_response,
)
from ..api_errors import ApiError, request_locale
from ..model_verification import record_probe
from ..gemini_compat import gemini_to_chat, chat_to_gemini, chat_stream_to_gemini
from ..compression import compress_messages
from ..config import settings
from ..gateway_skill_context import (
    GatewaySkillAssessment,
    declared_skill_context,
    evaluate_gateway_skill_context,
)
from ..request_leases import LeaseLimitExceeded, acquire_lease, release_lease
from ..responses_compat import (
    openai_stream_to_responses,
    openai_to_responses_response,
    response_tool_kinds,
    responses_to_openai_request,
)
from ..responses_upstream import ResponsesStreamAdapter, openai_to_responses_request, responses_to_openai_response
from ..runtime_trace_schemas import RuntimeTraceInternalEvent
from ..services import gateway_sessions
from ..services.runtime_traces import best_effort_trace_publisher, ingest_transaction, publish_events_best_effort
from ..sqlite_db import get_db
from .access_tokens import resolve_access_token

admin_router = APIRouter(prefix="/v1", tags=["llm-gateway-admin"])
runtime_router = APIRouter(tags=["llm-gateway"])

DEFAULT_ENTITY_TYPES = [
    "PERSON",
    "CN_ID_CARD",
    "CN_MOBILE",
    "CN_LANDLINE",
    "CN_BANK_CARD",
    "EMAIL_ADDRESS",
    "IP_ADDRESS",
    "CN_LICENSE_PLATE",
    "CN_USCC",
    "CN_ADDRESS",
    "EMPLOYEE_ID",
    "CUSTOMER_ID",
    "ACCOUNT_ID",
]
DEFAULT_ENTITY_PATTERNS = {
    "PERSON": "",
    "CN_ID_CARD": r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
    "CN_MOBILE": r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)",
    "CN_LANDLINE": "",
    "CN_BANK_CARD": r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)",
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "IP_ADDRESS": r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])",
    "CN_LICENSE_PLATE": r"(?<![A-Z0-9\u4e00-\u9fff])[\u4eac\u6d25\u6caa\u6e1d\u5180\u8c6b\u4e91\u8fbd\u9ed1\u6e58\u7696\u9c81\u65b0\u82cf\u6d59\u8d63\u9102\u6842\u7518\u664b\u8499\u9655\u5409\u95fd\u8d35\u7ca4\u9752\u85cf\u5ddd\u5b81\u743c][A-HJ-NP-Z](?:[DF][A-HJ-NP-Z0-9]\d{4}|\d{5}[DF]|[A-HJ-NP-Z0-9]{5})(?![A-Z0-9])",
    "CN_USCC": r"(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])",
    "CN_ADDRESS": "",
    "EMPLOYEE_ID": r"\b(?:EMP|Employee|员工)[-_:# ]?[A-Za-z0-9]{4,}\b",
    "CUSTOMER_ID": r"\b(?:CUST|Customer|客户)[-_:# ]?[A-Za-z0-9]{4,}\b",
    "ACCOUNT_ID": r"\b(?:ACCT|Account|账号)[-_:# ]?[A-Za-z0-9]{4,}\b",
}
DEFAULT_ENTITY_RULES = {name: DEFAULT_ENTITY_PATTERNS.get(name, "") for name in DEFAULT_ENTITY_TYPES}
PLACEHOLDER_PRESERVATION_SYSTEM_PROMPT = (
    "Each token like <PERSON:p_abc> or <CN_MOBILE:mobile_xyz> is encoded private data. "
    "Treat these tokens as the real values and preserve them naturally in the answer. "
    "Do not explain that they are placeholders."
)
TRACE_STAGES = ["meta", "prompt_security", "original", "masked", "compressed", "masked_response", "final_response"]
MESSAGE_TEXT_FIELDS = ("content", "reasoning_content")


def _runtime_trace_context(metadata: dict[str, str], conversation_id: str) -> dict[str, str | None]:
    return {
        "trace_id": metadata.get("trace_id"),
        "session_id": metadata.get("session_id") or conversation_id,
        "turn_id": metadata.get("turn_id"),
        "step_id": metadata.get("step_id"),
        "call_id": metadata.get("call_id"),
        "parent_call_id": metadata.get("parent_call_id"),
    }


@best_effort_trace_publisher
def _publish_model_runtime_trace(
    db: Session,
    *,
    key,
    trace_context: dict[str, str | None],
    tenant_id: str,
    request_id: str,
    model_name: str,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
    redacted_request: dict[str, Any] | None = None,
    redacted_response: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    prompt_security: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    upstream_duration_ms: float | None = None,
    ttft_ms: float | None = None,
    error: str | None = None,
    blocked: bool = False,
) -> None:
    agent_id = key.bound_agent_id if isinstance(key, models.AccessToken) else None
    trace_tenant_id = tenant_id
    if isinstance(key, models.AccessToken):
        if key.group_id is not None:
            trace_tenant_id = str(key.group_id)
        elif tenant_id == "group-default":
            trace_tenant_id = "default"
    common = {
        "trace_id": trace_context.get("gateway_trace_id") or (trace_context.get("trace_id") if agent_id else None),
        "tenant_id": trace_tenant_id,
        "agent_id": agent_id,
        "session_id": str(trace_context.get("session_id") or request_id),
        "owner_user_id": getattr(key, "user_id", None),
        "owner_group_id": getattr(key, "group_id", None),
        "source": "model_gateway",
        "turn_id": trace_context.get("turn_id"),
        "step_id": trace_context.get("step_id"),
        "request_id": request_id,
        "call_id": trace_context.get("call_id"),
        "parent_call_id": trace_context.get("parent_call_id"),
    }
    risk_codes = [str(item) for item in (prompt_security or {}).get("risk_codes", [])]
    prompt_severity = str((prompt_security or {}).get("risk_level") or "").lower()
    prompt_severity = prompt_severity if prompt_severity in {"low", "medium", "high", "critical"} else None
    request_duration_ms = max(0.0, duration_ms) if duration_ms is not None else None
    model_duration_ms = max(0.0, upstream_duration_ms) if upstream_duration_ms is not None else None
    performance = {
        key: round(value, 2)
        for key, value in {
            "request_duration_ms": request_duration_ms,
            "upstream_duration_ms": model_duration_ms,
            "platform_duration_ms": (
                max(0.0, request_duration_ms - model_duration_ms)
                if request_duration_ms is not None and model_duration_ms is not None
                else None
            ),
            "ttft_ms": max(0.0, ttft_ms) if ttft_ms is not None else None,
        }.items()
        if value is not None
    }
    events = []
    if request_payload is not None:
        events.append(
            RuntimeTraceInternalEvent(
                **common,
                type="model.request",
                status="blocked" if blocked else "submitted",
                severity=prompt_severity,
                risk_codes=risk_codes,
                payload={"model": model_name, "request": request_payload, "prompt_security": prompt_security or {}},
                redacted_payload={"model": model_name, "request": redacted_request or {}, "prompt_security": prompt_security or {}},
            )
        )
    if error is not None:
        events.append(
            RuntimeTraceInternalEvent(
                **common,
                type="model.error",
                status="blocked" if blocked else "error",
                severity=prompt_severity,
                duration_ms=request_duration_ms,
                risk_codes=risk_codes,
                payload={"model": model_name, "error": error, "prompt_security": prompt_security or {}, "performance": performance},
                redacted_payload={"model": model_name, "error": "[upstream-error]", "prompt_security": prompt_security or {}, "performance": performance},
            )
        )
    elif response_payload is not None:
        events.append(
            RuntimeTraceInternalEvent(
                **common,
                type="model.response",
                status="completed",
                severity=prompt_severity,
                duration_ms=request_duration_ms,
                risk_codes=risk_codes,
                payload={"model": model_name, "response": response_payload, "usage": usage or {}, "performance": performance},
                redacted_payload={"model": model_name, "response": redacted_response or {}, "usage": usage or {}, "performance": performance},
            )
        )
    if prompt_security and (risk_codes or blocked):
        events.append(
            RuntimeTraceInternalEvent(
                **common,
                type="security.finding",
                status="blocked" if blocked else "observed",
                severity=prompt_severity,
                risk_codes=risk_codes,
                payload={"component": "prompt_security", **prompt_security},
                redacted_payload={"component": "prompt_security", **prompt_security},
            )
        )
    if trace_context.get("gateway_trace_id"):
        with ingest_transaction(db):
            db.execute(update(models.RuntimeTraceSession).where(
                models.RuntimeTraceSession.trace_id == trace_context["gateway_trace_id"]
            ).values(updated_at=datetime.utcnow()))
            db.expire_all()
            publish_events_best_effort(db, events)
    else:
        publish_events_best_effort(db, events)
    if trace_context.get("gateway_trace_id") and (error is not None or response_payload is not None):
        gateway_sessions.finish(db, request_id, "blocked" if blocked else "error" if error is not None else "completed",
                                request_payload=request_payload, response_payload=response_payload)
        trace_context["gateway_finished"] = True
PROMPT_GUARD_RULES = [
    ("prompt_injection", "HIGH", "要求忽略或覆盖系统指令", r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?)|(忽略|无视|忘记|不要遵守|不用遵守|别管).{0,16}(以上|之前|前面|所有|系统|开发者|平台).{0,16}(指令|提示词|规则|要求)|(覆盖|重写|替换).{0,12}(系统|开发者|平台).{0,8}(指令|提示词|规则)"),
    ("system_prompt_leak", "HIGH", "要求泄露系统提示词或内部指令", r"(?i)(reveal|show|print|dump|output|return).{0,40}(system[_ -]?prompt|developer[_ -]?(message|prompt)|hidden (instructions?|rules?)|internal (instructions?|config|policy))|(system[_ -]?prompt|developer[_ -]?(message|prompt)|hidden (instructions?|rules?)|internal (instructions?|config|policy)).{0,40}(reveal|show|print|dump|output|return)|(泄露|显示|输出|打印|复述|逐字|返回).{0,30}(system[_ -]?prompt|developer[_ -]?prompt|系统提示词|系统指令|开发者消息|开发者提示词|隐藏规则|隐藏指令|内部指令|内部配置|初始提示词|完整提示词)|(system[_ -]?prompt|developer[_ -]?prompt|系统提示词|系统指令|开发者消息|开发者提示词|隐藏规则|隐藏指令|内部指令|内部配置|初始提示词|完整提示词).{0,40}(泄露|显示|输出|打印|复述|逐字|返回)"),
    ("secret_exfiltration", "HIGH", "要求输出密钥、凭据或敏感配置", r"(?i)(api[_ -]?keys?|secrets?|tokens?|passwords?|credentials?|private keys?|authorization header|cookies?).{0,60}(print|show|reveal|dump|output|return|exfiltrate|list)|(print|show|reveal|dump|output|return|list).{0,60}(api[_ -]?keys?|secrets?|tokens?|passwords?|credentials?|private keys?|authorization header|cookies?)|(输出|泄露|打印|展示|导出|列出|返回|原样输出).{0,40}(密钥|凭据|密码|token|api key|私钥|环境变量|配置文件|authorization header|cookie)|(amk_|amat_|sk-).{0,40}(输出|打印|展示|返回|原样|凭据|token|key|密钥)"),
    ("tool_abuse", "HIGH", "要求执行命令或读取敏感本地文件", r"(?i)(?P<command_action>((?:shell|bash|cmd|terminal)\b|命令行)[^.!?;。！？\r\n\\]{0,30}(\b(?:execute|exec|run)\b|执行|调用))|(\benv\b|cat\s+~?/?\\.ssh/id_rsa|/etc/passwd|\\.env|~/.config)|读取.{0,40}(/etc/passwd|\\.env|~/.config|账号|密钥)"),
    ("encoded_instruction", "MEDIUM", "要求解码并执行隐藏指令", r"(?i)(base64|decode|解码).{0,20}(execute|run|follow|执行|运行|遵循)"),
    ("safety_bypass", "MEDIUM", "要求绕过安全限制或审计", r"(?i)(bypass|disable|turn off|ignore).{0,30}(safety|policy|guardrail|audit|filter|moderation)|(绕过|关闭|禁用|跳过|规避).{0,20}(安全|策略|审计|过滤|限制|风控|防护|检测)"),
    ("role_override", "MEDIUM", "要求模型切换为不受限制的角色", r"(?i)(developer mode|dan mode|jailbreak|act as).{0,40}(no restrictions?|unfiltered|ignore)|(开发者模式|越狱模式|无限制模式|DAN模式|扮演).{0,24}(无视规则|不受限制|绕过限制|没有限制)"),
    ("tool_output_instruction", "MEDIUM", "工具返回内容夹带新的执行指令", r"(?i)(tool output|observation|retrieved content).{0,80}(ignore|follow these instructions|system prompt)|(工具返回|检索内容|网页内容|文档内容|搜索结果).{0,40}(忽略|执行以下|遵循以下|按以下指令|新的系统指令)"),
]
RISK_ORDER = {"none": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
COMMON_CN_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平"
    "黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝董"
    "梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌"
    "霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚"
    "程邢裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧"
    "隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀浦尚农"
    "温别庄晏柴瞿阎连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡"
    "国文寇广禄阙东殴殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
    "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
COMMON_CN_COMPOUND_SURNAMES = "欧阳|司马|上官|诸葛|东方|尉迟|公孙|慕容|令狐|长孙|宇文|司徒|司空|夏侯|皇甫"
CN_NAME_STOPWORDS = {
    "万份", "万手", "万市值", "成交额", "成交量", "全面", "空头", "步骤",
}
LEGACY_ENTITY_ALIASES = {
    "CN_PERSON": "PERSON",
    "PHONE_NUMBER": "CN_MOBILE",
    "CREDIT_CARD": "CN_BANK_CARD",
    "ID_CARD": "CN_ID_CARD",
}
REMOVED_ENTITY_TYPES = {"US_SSN"}


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _normalize_entity_types(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in values if isinstance(values, list) else DEFAULT_ENTITY_TYPES:
        entity_type = str(value)
        if entity_type in REMOVED_ENTITY_TYPES:
            continue
        entity_type = LEGACY_ENTITY_ALIASES.get(entity_type, entity_type)
        if entity_type not in normalized:
            normalized.append(entity_type)
    return normalized or list(DEFAULT_ENTITY_TYPES)


def _effective_entity_rules(value: str | None) -> dict[str, str]:
    stored = _json_loads(value, {})
    rules = dict(DEFAULT_ENTITY_RULES)
    if not isinstance(stored, dict):
        return rules
    for key, pattern in stored.items():
        if key in REMOVED_ENTITY_TYPES or key in LEGACY_ENTITY_ALIASES or key == "PERSON" or not pattern:
            continue
        rules[key] = pattern
    return rules


def _strip_undefined_values(value: Any) -> Any:
    if isinstance(value, str) and value in {"[undefined]", "undefined"}:
        return None
    if isinstance(value, list):
        cleaned = [_strip_undefined_values(item) for item in value]
        return [item for item in cleaned if item is not None]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized = _strip_undefined_values(item)
            if normalized is not None:
                cleaned[key] = normalized
        return cleaned
    return value


def _text_from_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _prompt_guard_mode(key) -> str:
    mode = str(getattr(key, "prompt_guard_mode", "off") or "off").lower()
    return mode if mode in {"off", "log", "warn", "block"} else "off"


PROMPT_CONTENT_SOURCES = {"system", "user", "assistant", "tool", "rag", "file", "web"}
UNTRUSTED_PROMPT_SOURCES = {"tool", "rag", "file", "web"}


def _message_content_sources(messages: list[dict[str, Any]], metadata: dict[str, Any] | None) -> list[str]:
    declared = (metadata or {}).get("content_sources")
    result = []
    for index, message in enumerate(messages):
        role = str(message.get("role") or "user").lower()
        fallback = role if role in {"system", "user", "assistant", "tool"} else "user"
        value = None
        if isinstance(declared, list) and index < len(declared):
            value = declared[index]
        elif isinstance(declared, dict):
            value = declared.get(str(index), declared.get(index))
        source = str(value or fallback).lower()
        result.append(source if source in PROMPT_CONTENT_SOURCES else fallback)
    return result


def _direct_prompt_rule_match(rule_id: str, pattern: str, text: str):
    compiled = re.compile(pattern)
    position = 0
    while (match := compiled.search(text, position)) is not None:
        if rule_id == "tool_abuse" and match.groupdict().get("command_action"):
            # A negated execution statement is diagnostic text. Other matches
            # in the same output, including sensitive paths, remain eligible.
            if re.search(r"(?i)\b(?:cannot|can['’]t|could not|do not|does not|must not|should not|not)\s+(?:be\s+)?(?:execute|exec|run)\b$|(?:不能|无法|不可|不要|禁止)(?:被)?(?:执行|调用)$", match.group()):
                position = match.start() + 1
                continue
        return match
    return None


def _prompt_rule_match(rule_id: str, pattern: str, text: str):
    direct = _direct_prompt_rule_match(rule_id, pattern, text)
    if direct or rule_id != "encoded_instruction":
        return direct
    # A long path, digest or ordinary encoded data is not an instruction.
    # Decode bounded, complete Base64 tokens as text only; never execute them.
    for candidate in re.finditer(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/_=-])", text):
        token = candidate.group()
        if len(token) > 8192:
            continue
        normalized = token.replace("-", "+").replace("_", "/")
        try:
            raw = b64decode(normalized + "=" * (-len(normalized) % 4), validate=True)
            if b64encode(raw).decode().rstrip("=") != normalized.rstrip("="):
                continue
            decoded = raw.decode("utf-8")
        except (ValueError, Base64Error, UnicodeError):
            continue
        if any(_direct_prompt_rule_match(other_id, other_pattern, decoded)
               for other_id, _, _, other_pattern in PROMPT_GUARD_RULES):
            return candidate
    return None


def _scan_prompt_security(
    messages: list[dict[str, Any]],
    *,
    mode: str,
    llm_review: bool = False,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    findings: list[dict[str, Any]] = []
    max_risk = "none"
    if mode != "off":
        for index, message in enumerate(messages):
            text = _text_from_message_content(message.get("content"))
            if not text:
                continue
            for rule_id, severity, reason, pattern in PROMPT_GUARD_RULES:
                match = _prompt_rule_match(rule_id, pattern, text)
                if not match:
                    continue
                if RISK_ORDER[severity] > RISK_ORDER[max_risk]:
                    max_risk = severity
                start, end = match.span()
                snippet = text[max(0, start - 30): min(len(text), end + 30)]
                findings.append({
                    "rule": rule_id,
                    "severity": severity,
                    "reason": reason,
                    "role": message.get("role") or "unknown",
                    "source": sources[index] if sources and index < len(sources) else (message.get("role") or "unknown"),
                    "message_index": index,
                    "snippet": snippet[:240],
                })
        combined = "\n".join(_text_from_message_content(message.get("content")) for message in messages)
        existing_rules = {item["rule"] for item in findings}
        for rule_id, severity, reason, pattern in PROMPT_GUARD_RULES:
            if rule_id in existing_rules:
                continue
            match = _prompt_rule_match(rule_id, pattern, combined)
            if not match:
                continue
            if RISK_ORDER[severity] > RISK_ORDER[max_risk]:
                max_risk = severity
            start, end = match.span()
            findings.append({
                "rule": rule_id,
                "severity": severity,
                "reason": f"跨消息组合命中：{reason}",
                "role": "combined",
                "source": "mixed",
                "message_index": None,
                "snippet": combined[max(0, start - 30): min(len(combined), end + 30)][:240],
            })
    action = "off"
    blocked = False
    if mode == "log":
        action = "record"
    elif mode == "warn":
        action = "warn" if findings else "pass"
    elif mode == "block":
        untrusted_medium = any(
            item["severity"] == "MEDIUM" and item.get("source") in UNTRUSTED_PROMPT_SOURCES
            for item in findings
        )
        blocked = max_risk == "HIGH" or untrusted_medium
        action = "block" if blocked else ("warn" if findings else "pass")
    return {
        "enabled": mode != "off",
        "mode": mode,
        "llm_review_enabled": bool(llm_review),
        "llm_review_used": False,
        "risk_level": max_risk,
        "action": action,
        "blocked": blocked,
        "findings": findings[:20],
        "findings_count": len(findings),
        "sources": sources or [],
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _mask_secret(value: str | None) -> str | None:
    value = _unprotect_secret(value)
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _secret_cipher() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(digest))


def _protect_secret(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("enc:"):
        return value
    return "enc:" + _secret_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _unprotect_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("enc:"):
        return value
    try:
        return _secret_cipher().decrypt(value[4:].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_api_key() -> str:
    return f"amk_{secrets.token_urlsafe(32)}"


def _now() -> datetime:
    return datetime.utcnow()


def _provider_response(row: models.ModelProvider) -> schemas.ModelProviderResponse:
    return schemas.ModelProviderResponse(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        api_format=getattr(row, "api_format", "openai"),
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        api_key_configured=bool(row.api_key),
        api_key_masked=_mask_secret(row.api_key),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_privacy_audit_user(current_user: models.User = Depends(auth.get_current_active_user)) -> models.User:
    if current_user.role not in {"admin", "super_admin", "privacy_auditor"}:
        raise HTTPException(status_code=403, detail="权限不足")
    return current_user


def _model_response(db: Session, row: models.ModelEndpoint) -> schemas.ModelEndpointResponse:
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == row.provider_id).first()
    return schemas.ModelEndpointResponse(
        id=row.id,
        provider_id=row.provider_id,
        provider_name=provider.name if provider else None,
        name=row.name,
        upstream_name=row.upstream_name or row.name,
        display_name=row.display_name,
        enabled=row.enabled,
        context_window=row.context_window,
        max_output_tokens=row.max_output_tokens,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _api_key_response(row: models.LlmApiKey, token: str | None = None) -> schemas.LlmApiKeyResponse:
    return schemas.LlmApiKeyResponse(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        token=token,
        user_id=row.user_id,
        group_id=row.group_id,
        allowed_models=_json_loads(row.allowed_models_json, []),
        status=row.status,
        expires_at=row.expires_at,
        max_body_kb=row.max_body_kb,
        max_concurrent_requests=row.max_concurrent_requests,
        enable_compression=getattr(row, "enable_compression", False),
        compression_level=getattr(row, "compression_level", "auto"),
        prompt_guard_mode=getattr(row, "prompt_guard_mode", "off"),
        prompt_guard_llm_review=getattr(row, "prompt_guard_llm_review", False),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


def _api_key_query_for_user(db: Session, current_user: models.User):
    return db.query(models.LlmApiKey).filter(models.LlmApiKey.user_id == current_user.id)


def _key_prefix(key) -> str:
    return getattr(key, "key_prefix", None) or getattr(key, "token_prefix", None) or ""


def _key_owner_meta(db: Session, key) -> dict[str, Any]:
    user = db.query(models.User).filter(models.User.id == key.user_id).first() if key.user_id else None
    if key.group_id:
        groups = db.query(models.UserGroup).filter(models.UserGroup.id == key.group_id).all()
    elif key.user_id:
        groups = (
            db.query(models.UserGroup)
            .join(models.UserGroupMember, models.UserGroup.id == models.UserGroupMember.group_id)
            .filter(models.UserGroupMember.user_id == key.user_id, models.UserGroup.is_active.is_(True))
            .order_by(models.UserGroup.id.asc())
            .all()
        )
    else:
        groups = []
    agent = None
    if isinstance(key, models.AccessToken) and key.bound_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == key.bound_agent_id).first()
    if not groups and agent:
        if agent and agent.department_group_id:
            groups = db.query(models.UserGroup).filter(models.UserGroup.id == agent.department_group_id).all()
    return {
        "api_key_id": key.id,
        "api_key_prefix": _key_prefix(key),
        "api_key_name": key.name,
        "api_key_user_id": key.user_id,
        "api_key_username": user.username if user else None,
        "api_key_group_id": key.group_id,
        "api_key_group_ids": [group.id for group in groups],
        "api_key_group_names": [group.name for group in groups],
        "credential_type": key.token_type if isinstance(key, models.AccessToken) else "legacy_llm_api_key",
        "agent_id": key.bound_agent_id if isinstance(key, models.AccessToken) else None,
        "agent_name": agent.name if agent else None,
        "agent_status": agent.status if agent else None,
        "agent_identity_source": "credential_binding" if agent else None,
    }


def _audit_identity_fields(key) -> dict[str, Any]:
    return {
        "credential_type": key.token_type if isinstance(key, models.AccessToken) else "legacy_llm_api_key",
        "agent_id": key.bound_agent_id if isinstance(key, models.AccessToken) else None,
    }


def _policy_response(row: models.PrivacyPolicy, *, default_policy_id: int | None = None) -> schemas.PrivacyPolicyResponse:
    return schemas.PrivacyPolicyResponse(
        id=row.id,
        name=row.name,
        enabled=row.enabled,
        is_default=row.id == default_policy_id,
        group_id=row.group_id,
        entity_types=_normalize_entity_types(_json_loads(row.entity_types_json, DEFAULT_ENTITY_TYPES)),
        entity_rules=_effective_entity_rules(getattr(row, "entity_rules_json", None)),
        detect_system_messages=row.detect_system_messages,
        allow_bypass=row.allow_bypass,
        mapping_ttl_days=row.mapping_ttl_days,
        dp_enabled=row.dp_enabled,
        dp_epsilon=row.dp_epsilon,
        dp_min_count=row.dp_min_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _group_response(db: Session, row: models.UserGroup) -> schemas.UserGroupResponse:
    members = db.query(models.UserGroupMember).filter(models.UserGroupMember.group_id == row.id).all()
    policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == row.id).first()
    return schemas.UserGroupResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        user_ids=[item.user_id for item in members],
        privacy_policy_id=policy.id if policy else None,
        privacy_policy_name=policy.name if policy else None,
        created_at=row.created_at,
    )


def _user_group_ids(db: Session, user_id: int) -> list[int]:
    rows = db.query(models.UserGroupMember).filter(models.UserGroupMember.user_id == user_id).order_by(models.UserGroupMember.group_id.asc()).all()
    return [row.group_id for row in rows]


def _user_response(db: Session, row: models.User) -> schemas.User:
    return schemas.User(
        id=row.id,
        username=row.username,
        email=row.email,
        is_active=row.is_active,
        role=row.role,
        group_ids=_user_group_ids(db, row.id),
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


def _sync_user_groups(db: Session, user_id: int, group_ids: list[int]) -> None:
    clean_group_ids = []
    for group_id in group_ids:
        if group_id in clean_group_ids:
            continue
        if not db.query(models.UserGroup).filter(models.UserGroup.id == group_id).first():
            raise HTTPException(status_code=404, detail="用户组不存在")
        clean_group_ids.append(group_id)
    db.query(models.UserGroupMember).filter(models.UserGroupMember.user_id == user_id).delete()
    for group_id in clean_group_ids:
        db.add(models.UserGroupMember(user_id=user_id, group_id=group_id))


def _sync_group_members(db: Session, group_id: int, user_ids: list[int]) -> None:
    db.query(models.UserGroupMember).filter(models.UserGroupMember.group_id == group_id).delete()
    for user_id in sorted(set(user_ids)):
        if db.query(models.User).filter(models.User.id == user_id).first():
            db.add(models.UserGroupMember(user_id=user_id, group_id=group_id))


def _bind_group_policy(db: Session, group_id: int, policy_id: int | None) -> None:
    if policy_id is None:
        db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == group_id).update({"group_id": None})
        return
    policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="隐私策略不存在")
    if policy.id == _get_default_policy(db).id:
        raise HTTPException(status_code=400, detail="系统默认隐私策略不能绑定用户组")
    if policy.group_id is not None and policy.group_id != group_id:
        raise HTTPException(status_code=400, detail="隐私策略已绑定其他用户组")
    db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == group_id).update({"group_id": None})
    policy.group_id = group_id


def _get_default_policy(db: Session) -> models.PrivacyPolicy:
    policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id.is_(None)).first()
    if policy:
        return policy
    policy = models.PrivacyPolicy(
        name="默认隐私策略",
        enabled=True,
        group_id=None,
        entity_types_json=_json_dumps(DEFAULT_ENTITY_TYPES),
        entity_rules_json=_json_dumps(DEFAULT_ENTITY_RULES),
        detect_system_messages=False,
        allow_bypass=False,
        mapping_ttl_days=7,
        dp_enabled=True,
        dp_epsilon=1.0,
        dp_min_count=5,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def _resolve_policy(db: Session, key) -> models.PrivacyPolicy:
    candidate_group_ids: list[int] = []
    if key.group_id is not None:
        candidate_group_ids.append(key.group_id)
    elif key.user_id is not None:
        memberships = (
            db.query(models.UserGroupMember)
            .join(models.UserGroup, models.UserGroup.id == models.UserGroupMember.group_id)
            .filter(models.UserGroupMember.user_id == key.user_id, models.UserGroup.is_active.is_(True))
            .order_by(models.UserGroupMember.id.asc())
            .all()
        )
        candidate_group_ids.extend(item.group_id for item in memberships)
    elif isinstance(key, models.AccessToken) and key.bound_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == key.bound_agent_id).first()
        if agent and agent.department_group_id:
            candidate_group_ids.append(agent.department_group_id)
    for group_id in candidate_group_ids:
        policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == group_id).first()
        if policy:
            return policy
    return _get_default_policy(db)


def _resolve_api_key(db: Session, authorization: str | None, request: Request | None = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 LLM API Key")
    raw = authorization[len("Bearer "):].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="缺少 LLM API Key")
    key_hash = _hash_token(raw)
    key = db.query(models.LlmApiKey).filter(models.LlmApiKey.key_hash == key_hash).first()
    if key:
        if key.status != "active":
            raise HTTPException(status_code=401, detail="LLM API Key 无效或已禁用")
        if key.expires_at and key.expires_at < _now():
            raise HTTPException(status_code=401, detail="LLM API Key 已过期")
        key.last_used_at = _now()
        return key
    return resolve_access_token(
        db,
        authorization,
        required_scope="model:chat",
        request=request,
        allowed_token_types={"model_gateway", "agent_runtime"},
    )


async def _check_request_size(request: Request, key: models.LlmApiKey) -> None:
    raw_body = await request.body()
    max_bytes = max(1, key.max_body_kb) * 1024
    if len(raw_body) > max_bytes:
        raise HTTPException(status_code=413, detail=f"请求体超过 API Key 限制: {key.max_body_kb} KB")


def _acquire_key_slot(key: models.LlmApiKey) -> None:
    session = object_session(key)
    bind = session.get_bind() if session is not None else None
    subject_type = "access_token" if isinstance(key, models.AccessToken) else "llm_api_key"
    try:
        lease_id = acquire_lease(
            subject_type,
            key.id,
            "model_chat",
            key.max_concurrent_requests,
            **({"bind": bind} if bind is not None else {}),
        )
    except LeaseLimitExceeded:
        raise HTTPException(status_code=429, detail="API Key 并发请求数已达上限")
    leases = getattr(key, "_request_lease_ids", None)
    if leases is None:
        leases = []
        key._request_lease_ids = leases
    leases.append((lease_id, bind))


def _release_key_slot(key: models.LlmApiKey) -> None:
    leases = getattr(key, "_request_lease_ids", None) or []
    lease = leases.pop() if leases else None
    if lease:
        lease_id, bind = lease
        release_lease(lease_id, **({"bind": bind} if bind is not None else {}))


def _resolve_model(db: Session, requested_model: str | None, key) -> models.ModelEndpoint:
    allowed_models = _json_loads(key.allowed_models_json, [])
    if isinstance(key, models.AccessToken) and key.token_type == "agent_runtime" and not allowed_models and key.bound_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == key.bound_agent_id).first()
        if agent and agent.default_model:
            allowed_models = [agent.default_model]
    model_name = requested_model
    if not model_name:
        default_model = db.query(models.ModelEndpoint).filter(
            models.ModelEndpoint.enabled.is_(True),
            models.ModelEndpoint.is_default.is_(True),
        ).first()
        model_name = default_model.name if default_model else (allowed_models[0] if allowed_models else None)
    if not model_name:
        raise HTTPException(status_code=400, detail="请求缺少 model，且未配置默认模型")
    if allowed_models and model_name not in allowed_models:
        raise HTTPException(status_code=403, detail=f"API Key 不允许访问模型: {model_name}")
    model = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.name == model_name).first()
    if not model or not model.enabled:
        raise HTTPException(status_code=404, detail=f"模型不存在或未启用: {model_name}")
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == model.provider_id).first()
    if not provider or not provider.enabled:
        raise HTTPException(status_code=400, detail="模型供应商不存在或未启用")
    return model


def _normalize_value(entity_type: str, value: str) -> str:
    value = value.strip()
    if entity_type in {"EMAIL_ADDRESS", "URL"}:
        return value.lower()
    if entity_type in {"CN_MOBILE", "CN_LANDLINE", "CN_BANK_CARD", "CN_ID_CARD", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "ID_CARD"}:
        return re.sub(r"\D+", "", value)
    return re.sub(r"\s+", " ", value).lower()


def _valid_cn_id_card(value: str) -> bool:
    value = value.upper()
    if not re.fullmatch(r"\d{17}[\dX]", value):
        return False
    if value[:2] not in {
        "11", "12", "13", "14", "15", "21", "22", "23", "31", "32", "33", "34", "35", "36", "37",
        "41", "42", "43", "44", "45", "46", "50", "51", "52", "53", "54", "61", "62", "63", "64", "65",
        "71", "81", "82",
    }:
        return False
    try:
        datetime.strptime(value[6:14], "%Y%m%d")
    except ValueError:
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    return checks[sum(int(digit) * weight for digit, weight in zip(value[:17], weights)) % 11] == value[-1]


def _valid_luhn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 16 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(map(int, digits)):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _valid_uscc(value: str) -> bool:
    charset = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    weights = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
    value = value.upper()
    if len(value) != 18 or any(char not in charset for char in value):
        return False
    expected = charset[(31 - sum(charset.index(char) * weight for char, weight in zip(value[:17], weights)) % 31) % 31]
    return value[-1] == expected


def _valid_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _add_matches(entities, entity_type: str, matches, *, score: float, group: int = 0, validator=None) -> None:
    for match in matches:
        value = match.group(group)
        if validator and not validator(value):
            continue
        entities.append({
            "entity_type": entity_type,
            "start": match.start(group),
            "end": match.end(group),
            "score": score,
        })


def _detect_entities(text: str, allowed_types: set[str], entity_rules: dict[str, str] | None = None) -> list[dict[str, Any]]:
    patterns = {**DEFAULT_ENTITY_PATTERNS, **{k: v for k, v in (entity_rules or {}).items() if v}}
    entities: list[dict[str, Any]] = []
    validated_types = {"PERSON", "CN_ID_CARD", "CN_MOBILE", "CN_LANDLINE", "CN_BANK_CARD", "IP_ADDRESS", "CN_USCC", "CN_ADDRESS"}
    for entity_type, pattern in patterns.items():
        if entity_type not in allowed_types or entity_type in validated_types or not pattern:
            continue
        try:
            matches = re.finditer(pattern, text)
        except re.error:
            continue
        _add_matches(entities, entity_type, matches, score=0.85)

    validated_rules = (
        ("CN_ID_CARD", 0.99, _valid_cn_id_card),
        ("CN_MOBILE", 0.96, None),
        ("CN_BANK_CARD", 0.95, _valid_luhn),
        ("IP_ADDRESS", 0.98, _valid_ip_address),
        ("CN_USCC", 0.99, _valid_uscc),
    )
    for entity_type, score, validator in validated_rules:
        pattern = patterns.get(entity_type)
        if entity_type not in allowed_types or not pattern:
            continue
        try:
            matches = re.finditer(pattern, text, re.IGNORECASE)
        except re.error:
            continue
        _add_matches(entities, entity_type, matches, score=score, validator=validator)

    if "PERSON" in allowed_types:
        cn_name_core = rf"(?:(?:{COMMON_CN_COMPOUND_SURNAMES})[\u4e00-\u9fff]{{1,2}}|[{COMMON_CN_SURNAMES}][\u4e00-\u9fff]{{1,2}})"
        direct_context = r"(?:我叫|叫我|名叫|名字叫|用户叫|候选人叫|客户叫|孩子叫|孩子名叫|小孩叫|小孩名叫)\s*"
        labeled_context = r"(?:姓名|名字|用户姓名|候选人姓名|联系人|负责人|客户姓名|法人|孩子姓名|小孩姓名)(?:(?:是|为)\s*|[：:\s]+)"
        context_pattern = rf"(?:{direct_context}|{labeled_context})({cn_name_core})"
        for match in re.finditer(context_pattern, text):
            if match.group(1) in CN_NAME_STOPWORDS:
                continue
            entities.append(
                {
                    "entity_type": "PERSON",
                    "start": match.start(1),
                    "end": match.end(1),
                    "score": 0.9,
                }
            )
        suffix_pattern = rf"({cn_name_core})(?=先生|女士|老师|经理|总监|主任|同学|医生|律师|这个人|此人)"
        for match in re.finditer(suffix_pattern, text):
            if match.group(1) in CN_NAME_STOPWORDS:
                continue
            entities.append(
                {
                    "entity_type": "PERSON",
                    "start": match.start(1),
                    "end": match.end(1),
                    "score": 0.88,
                }
            )

    if "CN_LANDLINE" in allowed_types:
        pattern = r"(?:座机|固定电话|联系电话|电话|Tel)[：:\s]*((?:0\d{2,3}[- ]?)?[2-9]\d{6,7}(?:-\d{1,6})?)"
        _add_matches(entities, "CN_LANDLINE", re.finditer(pattern, text, re.IGNORECASE), score=0.93, group=1)

    if "CN_ADDRESS" in allowed_types:
        pattern = r"(?:收货地址|家庭住址|注册地址|通讯地址|联系地址|地址|住址)[：:\s]*([^\n，,;；。.!！?？]{6,80})"
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            markers = re.findall(r"省|自治区|市|区|县|镇|街道|路|街|巷|村|小区|大厦|号|室", value)
            if len(markers) < 2:
                continue
            leading = len(match.group(1)) - len(match.group(1).lstrip())
            entities.append({
                "entity_type": "CN_ADDRESS",
                "start": match.start(1) + leading,
                "end": match.start(1) + leading + len(value),
                "score": 0.9,
            })

    entities.sort(key=lambda item: (item["start"], -item["score"], -(item["end"] - item["start"])))
    accepted: list[dict[str, Any]] = []
    for candidate in entities:
        if any(not (candidate["end"] <= item["start"] or candidate["start"] >= item["end"]) for item in accepted):
            continue
        accepted.append(candidate)
    return accepted


def _token_for(tenant_id: str, conversation_id: str, entity_type: str, normalized_value: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{conversation_id}:{entity_type}:{normalized_value}".encode()).hexdigest()
    prefix = {
        "PERSON": "p",
        "CN_ID_CARD": "id",
        "CN_MOBILE": "mobile",
        "CN_LANDLINE": "tel",
        "CN_BANK_CARD": "bank",
        "EMAIL_ADDRESS": "em",
        "IP_ADDRESS": "ip",
        "CN_LICENSE_PLATE": "plate",
        "CN_USCC": "uscc",
        "CN_ADDRESS": "addr",
        "EMPLOYEE_ID": "emp",
        "CUSTOMER_ID": "cust",
        "ACCOUNT_ID": "acct",
    }.get(entity_type, "x")
    return f"<{entity_type}:{prefix}_{digest[:10]}>"


def _pseudonymize_text(
    db: Session,
    *,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    request_id: str,
    text: str,
    entity_types: set[str],
    entity_rules: dict[str, str],
    ttl_days: int,
) -> tuple[str, list[models.PseudonymMapping], int, int, dict[str, int]]:
    entities = _detect_entities(text, entity_types, entity_rules)
    replacements: list[tuple[int, int, str]] = []
    mappings: list[models.PseudonymMapping] = []
    created_count = 0
    reused_count = 0
    detected_counts: dict[str, int] = {}
    expires_at = _now() + timedelta(days=ttl_days)
    for entity in entities:
        entity_type = entity["entity_type"]
        raw = text[entity["start"]:entity["end"]]
        normalized = _normalize_value(entity_type, raw)
        detected_counts[entity_type] = detected_counts.get(entity_type, 0) + 1
        existing = db.query(models.PseudonymMapping).filter(
            models.PseudonymMapping.tenant_id == tenant_id,
            models.PseudonymMapping.conversation_id == conversation_id,
            models.PseudonymMapping.entity_type == entity_type,
            models.PseudonymMapping.normalized_value == normalized,
            models.PseudonymMapping.expires_at >= _now(),
        ).first()
        if existing:
            existing.updated_at = _now()
            existing.expires_at = expires_at
            token = existing.token
            reused_count += 1
            mappings.append(existing)
        else:
            token = _token_for(tenant_id, conversation_id, entity_type, normalized)
            mapping = models.PseudonymMapping(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                token=token,
                entity_type=entity_type,
                original_value=raw,
                normalized_value=normalized,
                request_id=request_id,
                created_by=user_ref,
                expires_at=expires_at,
            )
            db.add(mapping)
            db.flush()
            mappings.append(mapping)
            created_count += 1
        replacements.append((entity["start"], entity["end"], token))
    rewritten = text
    for start, end, token in sorted(replacements, key=lambda item: item[0], reverse=True):
        rewritten = rewritten[:start] + token + rewritten[end:]
    return rewritten, mappings, created_count, reused_count, detected_counts


def _redact_known_values(
    messages: list[dict[str, Any]],
    mappings: list[models.PseudonymMapping],
    *,
    skip_fields: dict[int, set[str]] | None = None,
) -> list[dict[str, Any]]:
    sorted_mappings = sorted(mappings, key=lambda item: len(item.original_value or ""), reverse=True)
    skip_fields = skip_fields or {}
    result: list[dict[str, Any]] = []
    for idx, message in enumerate(messages):
        if message.get("role") not in {"assistant", "tool"}:
            result.append(dict(message))
            continue
        copied = dict(message)
        for field in MESSAGE_TEXT_FIELDS:
            if field in skip_fields.get(idx, set()) or field not in copied:
                continue
            copied[field] = _replace_text_content(copied.get(field), sorted_mappings, to_token=True)
        if "tool_calls" in copied and "tool_calls" not in skip_fields.get(idx, set()):
            copied["tool_calls"] = _replace_tool_call_arguments(copied["tool_calls"], sorted_mappings, to_token=True)
        result.append(copied)
    return result


def _replace_text_content(value: Any, mappings: list[models.PseudonymMapping], *, to_token: bool) -> Any:
    def replace_text(text: str) -> str:
        result = text
        for mapping in mappings:
            before = mapping.original_value if to_token else mapping.token
            after = mapping.token if to_token else mapping.original_value
            result = result.replace(before, after)
        return result

    if isinstance(value, str):
        return replace_text(value)
    if isinstance(value, list):
        replaced = []
        for item in value:
            if isinstance(item, dict):
                copied = dict(item)
                if isinstance(copied.get("text"), str):
                    copied["text"] = replace_text(copied["text"])
                replaced.append(copied)
            else:
                replaced.append(item)
        return replaced
    return value


def _replace_tool_call_arguments(value: Any, mappings: list[models.PseudonymMapping], *, to_token: bool) -> Any:
    if not isinstance(value, list):
        return value
    result = []
    for tool_call in value:
        copied = dict(tool_call)
        function = dict(copied.get("function") or {})
        if isinstance(function.get("arguments"), str):
            function["arguments"] = _replace_text_content(function["arguments"], mappings, to_token=to_token)
        copied["function"] = function
        result.append(copied)
    return result


def _pseudonymize_content(
    db: Session,
    *,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    request_id: str,
    content: Any,
    entity_types: set[str],
    entity_rules: dict[str, str],
    ttl_days: int,
) -> tuple[Any, list[models.PseudonymMapping], int, int, dict[str, int]]:
    def merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
        for entity_type, count in source.items():
            target[entity_type] = target.get(entity_type, 0) + count

    mappings: list[models.PseudonymMapping] = []
    created_total = 0
    reused_total = 0
    detected_counts: dict[str, int] = {}

    def pseudonymize_text(text: str) -> str:
        nonlocal created_total, reused_total
        rewritten, new_mappings, created, reused, counts = _pseudonymize_text(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            request_id=request_id,
            text=text,
            entity_types=entity_types,
            entity_rules=entity_rules,
            ttl_days=ttl_days,
        )
        mappings.extend(new_mappings)
        created_total += created
        reused_total += reused
        merge_counts(detected_counts, counts)
        return rewritten

    if isinstance(content, str):
        rewritten_content = pseudonymize_text(content)
    elif isinstance(content, list):
        rewritten_items = []
        for item in content:
            if isinstance(item, dict):
                copied = dict(item)
                if isinstance(copied.get("text"), str):
                    copied["text"] = pseudonymize_text(copied["text"])
                rewritten_items.append(copied)
            else:
                rewritten_items.append(item)
        rewritten_content = rewritten_items
    else:
        rewritten_content = content

    return rewritten_content, mappings, created_total, reused_total, detected_counts


def _depseudonymize_text(text: str | None, mappings: list[models.PseudonymMapping]) -> str | None:
    if text is None:
        return None
    result = text
    for mapping in sorted(mappings, key=lambda item: len(item.token or ""), reverse=True):
        result = result.replace(mapping.token, mapping.original_value)
    return result


def _split_stream_safe_text(text: str, tokens: list[str]) -> tuple[str, str]:
    for start in range(len(text)):
        suffix = text[start:]
        if suffix and any(token.startswith(suffix) for token in tokens):
            return text[:start], suffix
    return text, ""


def _save_trace(
    db: Session,
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    model: str,
    bypass_pii: bool,
    stages: dict[str, Any],
    ttl_days: int,
) -> None:
    expires_at = _now() + timedelta(days=ttl_days)
    for stage in TRACE_STAGES:
        if stage not in stages:
            continue
        db.add(
            models.LlmPipelineTrace(
                request_id=request_id,
                stage=stage,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                model=model,
                bypass_pii=bypass_pii,
                payload_json=_json_dumps(stages[stage]),
                expires_at=expires_at,
            )
        )


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _anthropic_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    return f"{base}/messages"


def _responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/responses") else f"{base}/responses"


def _upstream_error_summary(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
        for field in ("message", "msg"):
            if payload.get(field):
                return str(payload[field])[:500]
    return response.text.strip()[:500] or f"HTTP {response.status_code}"


def _is_valid_provider_test_response(api_format: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if api_format == "responses_api":
        try:
            message = responses_to_openai_response(payload)["choices"][0]["message"]
            return bool(message.get("content") or message.get("refusal") or message.get("tool_calls"))
        except (ValueError, KeyError, TypeError, AttributeError):
            return False
    if api_format == "anthropic":
        return isinstance(payload.get("content"), list) and any(
            isinstance(part, dict) and (part.get("text") or part.get("type") == "tool_use")
            for part in payload["content"]
        )
    return isinstance(payload.get("choices"), list) and any(
        isinstance(choice, dict) and isinstance(choice.get("message"), dict) and
        any(choice["message"].get(field) for field in ("content", "refusal", "tool_calls"))
        for choice in payload["choices"]
    )


def _upstream_request(provider: models.ModelProvider, payload: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, str]]:
    api_format = getattr(provider, "api_format", "openai") or "openai"
    payload = dict(payload)
    anthropic_options = payload.pop("anthropic_options", {})
    headers = {"content-type": "application/json"}
    api_key = _unprotect_secret(provider.api_key)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
        if api_format == "anthropic":
            headers["x-api-key"] = api_key
    if api_format == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        upstream_payload = openai_to_anthropic_request(payload)
        upstream_payload.update(anthropic_options)
        return _anthropic_url(provider.base_url), upstream_payload, headers
    if api_format == "responses_api":
        try:
            if anthropic_options:
                payload["anthropic_options"] = anthropic_options
            return _responses_url(provider.base_url), openai_to_responses_request(payload), headers
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiError(422, "model_provider.unsupported_parameters", "当前供应商协议不支持请求中的参数或内容", "The provider protocol does not support the request parameters or content") from None
    return _chat_url(provider.base_url), payload, headers


async def _call_upstream(db: Session, model: models.ModelEndpoint, payload: dict[str, Any]) -> dict[str, Any]:
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == model.provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="模型供应商不存在")
    url, upstream_payload, headers = _upstream_request(provider, {**payload, "model": model.upstream_name or model.name})
    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        response = await client.post(url, json=upstream_payload, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"上游模型接口失败: {response.status_code} {response.text[:500]}")
    if getattr(provider, "api_format", "openai") == "responses_api":
        try:
            result = responses_to_openai_response(response.json())
            result["model"] = model.name
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiError(502, "model_provider.invalid_response", "供应商返回了无效或失败的响应", "Provider returned an invalid or failed response") from None
    result = response.json()
    if (getattr(provider, "api_format", "openai") or "openai") == "anthropic":
        result = anthropic_to_openai_response(result)
    result["model"] = model.name
    return result


def _stream_choices_snapshot(
    parts_by_index: dict[int, dict[str, list[str]]],
    tool_calls_by_key: dict[tuple[int, int], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    indexes = set(parts_by_index)
    indexes.update(index for index, _tool_index in (tool_calls_by_key or {}))
    for index in sorted(indexes):
        choice: dict[str, Any] = {"index": index}
        for field, parts in parts_by_index.get(index, {}).items():
            choice[field] = "".join(parts)
        tool_calls = []
        for (choice_index, _tool_index), snapshot in sorted((tool_calls_by_key or {}).items()):
            if choice_index != index:
                continue
            normalized = json.loads(json.dumps(snapshot))
            function = normalized.get("function") or {}
            argument_parts = function.pop("arguments_parts", [])
            function["arguments"] = "".join(argument_parts)
            normalized["function"] = function
            tool_calls.append(normalized)
        if tool_calls:
            choice["tool_calls"] = tool_calls
        choices.append(choice)
    return choices


def _stream_chunk_has_output(chunk: dict[str, Any]) -> bool:
    """Return true only when a stream chunk carries a user-visible model token."""
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if any(isinstance(delta.get(field), str) and delta.get(field) for field in MESSAGE_TEXT_FIELDS):
            return True
        for tool_call in delta.get("tool_calls") or []:
            arguments = (tool_call.get("function") or {}).get("arguments")
            if isinstance(arguments, str) and arguments:
                return True
    return False


async def _upstream_sse_data(upstream: httpx.Response, api_format: str):
    event = "message"
    responses_adapter = ResponsesStreamAdapter() if api_format == "responses_api" else None
    async for line in upstream.aiter_lines():
        if not line:
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if responses_adapter is not None:
            if data == "[DONE]" and responses_adapter.completed:
                continue
            try:
                parsed = json.loads(data)
                for converted in responses_adapter.convert(parsed):
                    yield converted if isinstance(converted, str) else json.dumps(converted, ensure_ascii=False)
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ApiError(502, "model_provider.invalid_stream", "供应商流式响应无效或失败", "Provider stream was invalid or failed") from None
            continue
        if api_format != "anthropic":
            yield data
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        for converted in anthropic_stream_event_to_openai(event, parsed):
            yield converted if isinstance(converted, str) else json.dumps(converted, ensure_ascii=False)
    if responses_adapter is not None and not responses_adapter.completed:
        raise ApiError(502, "model_provider.incomplete_stream", "供应商流式响应提前结束", "Provider stream ended before completion")


async def _stream_upstream(
    db: Session,
    model: models.ModelEndpoint,
    payload: dict[str, Any],
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    key: models.LlmApiKey,
    bypass_pii: bool,
    all_mappings: list[models.PseudonymMapping],
    detected_counts: dict[str, int],
    created_total: int,
    reused_total: int,
    policy: models.PrivacyPolicy,
    original_messages: list[dict[str, Any]],
    upstream_messages: list[dict[str, Any]],
    compression_enabled: bool = False,
    compression_level: str = "auto",
    compression_result: Any = None,
    prompt_security: dict[str, Any] | None = None,
    skill_assessment: GatewaySkillAssessment | None = None,
    request_started_at: float | None = None,
    trace_context: dict[str, str | None] | None = None,
):
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == model.provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="模型供应商不存在")
    url, upstream_payload, headers = _upstream_request(provider, {**payload, "model": model.upstream_name or model.name})
    api_format = getattr(provider, "api_format", "openai") or "openai"

    masked_parts: dict[int, dict[str, list[str]]] = {}
    final_parts: dict[int, dict[str, list[str]]] = {}
    pending_parts: dict[tuple[int, str], str] = {}
    pending_tool_parts: dict[tuple[int, int], str] = {}
    masked_tool_calls: dict[tuple[int, int], dict[str, Any]] = {}
    final_tool_calls: dict[tuple[int, int], dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    mapping_tokens = [mapping.token for mapping in all_mappings if mapping.token]

    async def event_generator():
        nonlocal usage
        started_at = request_started_at or time.perf_counter()
        upstream_started_at = time.perf_counter()
        first_output_at: float | None = None
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=upstream_payload,
                    headers=headers,
                    timeout=provider.timeout_seconds,
                ) as upstream:
                    if upstream.status_code >= 400:
                        error_body = await upstream.aread()
                        raise HTTPException(
                            status_code=502,
                            detail=f"上游模型接口失败: {upstream.status_code} {error_body[:500].decode('utf-8', errors='replace')}",
                        )
                    async for data in _upstream_sse_data(upstream, api_format):
                        if data == "[DONE]":
                            for (index, field), pending in sorted(pending_parts.items()):
                                if not pending:
                                    continue
                                final_content = pending if bypass_pii else (_depseudonymize_text(pending, all_mappings) or "")
                                final_parts.setdefault(index, {}).setdefault(field, []).append(final_content)
                                yield (
                                    "data: "
                                    + json.dumps(
                                        {"choices": [{"index": index, "delta": {field: final_content}}]},
                                        ensure_ascii=False,
                                    )
                                    + "\n\n"
                                )
                            pending_parts.clear()
                            for (choice_index, tool_index), pending in sorted(pending_tool_parts.items()):
                                if not pending:
                                    continue
                                final_arguments = pending if bypass_pii else (_depseudonymize_text(pending, all_mappings) or "")
                                final_tool_calls.setdefault(
                                    (choice_index, tool_index),
                                    {"index": tool_index, "function": {"arguments_parts": []}},
                                )["function"].setdefault("arguments_parts", []).append(final_arguments)
                                yield "data: " + json.dumps({
                                    "choices": [{
                                        "index": choice_index,
                                        "delta": {"tool_calls": [{"index": tool_index, "function": {"arguments": final_arguments}}]},
                                    }],
                                }, ensure_ascii=False) + "\n\n"
                            pending_tool_parts.clear()
                            _record_llm_success(
                                db,
                                request_id=request_id,
                                tenant_id=tenant_id,
                                conversation_id=conversation_id,
                                user_ref=user_ref,
                                key=key,
                                model_name=model.name,
                                bypass_pii=bypass_pii,
                                usage=usage,
                                detected_counts=detected_counts,
                                created_total=created_total,
                                reused_total=reused_total,
                                policy=policy,
                                original_messages=original_messages,
                                upstream_messages=upstream_messages,
                                masked_choices=_stream_choices_snapshot(masked_parts, masked_tool_calls),
                                final_choices=_stream_choices_snapshot(final_parts, final_tool_calls),
                                compression_enabled=compression_enabled,
                                compression_level=compression_level,
                                compression_result=compression_result,
                                compressed_messages=payload["messages"],
                                prompt_security=prompt_security,
                                skill_assessment=skill_assessment,
                                request_duration_ms=(time.perf_counter() - started_at) * 1000,
                                upstream_duration_ms=(time.perf_counter() - upstream_started_at) * 1000,
                                ttft_ms=(first_output_at - started_at) * 1000 if first_output_at is not None else None,
                                trace_context=trace_context,
                            )
                            yield "data: [DONE]\n\n"
                            return
                        try:
                            chunk = json.loads(data)
                            if "model" in chunk:
                                chunk["model"] = model.name
                        except json.JSONDecodeError:
                            yield f"data: {data}\n\n"
                            continue
                        if isinstance(chunk.get("usage"), dict):
                            usage.update(chunk["usage"])
                            usage["total_tokens"] = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
                        if first_output_at is None and _stream_chunk_has_output(chunk):
                            first_output_at = time.perf_counter()
                        for choice in chunk.get("choices", []) or []:
                            index = int(choice.get("index") or 0)
                            delta = choice.get("delta") or {}
                            for field in MESSAGE_TEXT_FIELDS:
                                content = delta.get(field)
                                if not isinstance(content, str) or not content:
                                    continue
                                pending_key = (index, field)
                                combined = pending_parts.get(pending_key, "") + content
                                emit_masked, pending = _split_stream_safe_text(combined, mapping_tokens)
                                pending_parts[pending_key] = pending
                                masked_parts.setdefault(index, {}).setdefault(field, []).append(content)
                                final_content = emit_masked if bypass_pii else (_depseudonymize_text(emit_masked, all_mappings) or "")
                                final_parts.setdefault(index, {}).setdefault(field, []).append(final_content)
                                delta[field] = final_content
                                choice["delta"] = delta
                            for tool_call in delta.get("tool_calls") or []:
                                function = tool_call.get("function") or {}
                                tool_index = int(tool_call.get("index") or 0)
                                pending_key = (index, tool_index)
                                for snapshots in (masked_tool_calls, final_tool_calls):
                                    snapshot = snapshots.setdefault(
                                        pending_key,
                                        {"index": tool_index, "function": {"arguments_parts": []}},
                                    )
                                    for key_name in ("id", "type"):
                                        if tool_call.get(key_name) is not None:
                                            snapshot[key_name] = tool_call[key_name]
                                    if function.get("name") is not None:
                                        snapshot["function"]["name"] = function["name"]
                                arguments = function.get("arguments")
                                if not isinstance(arguments, str) or not arguments:
                                    continue
                                masked_tool_calls[pending_key]["function"]["arguments_parts"].append(arguments)
                                combined = pending_tool_parts.get(pending_key, "") + arguments
                                emit_masked, pending = _split_stream_safe_text(combined, mapping_tokens)
                                pending_tool_parts[pending_key] = pending
                                final_arguments = (
                                    emit_masked
                                    if bypass_pii
                                    else (_depseudonymize_text(emit_masked, all_mappings) or "")
                                )
                                final_tool_calls[pending_key]["function"]["arguments_parts"].append(final_arguments)
                                function["arguments"] = final_arguments
                                tool_call["function"] = function
                            choice["delta"] = delta
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            _record_llm_success(
                db,
                request_id=request_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                user_ref=user_ref,
                key=key,
                model_name=model.name,
                bypass_pii=bypass_pii,
                usage=usage,
                detected_counts=detected_counts,
                created_total=created_total,
                reused_total=reused_total,
                policy=policy,
                original_messages=original_messages,
                upstream_messages=upstream_messages,
                masked_choices=_stream_choices_snapshot(masked_parts, masked_tool_calls),
                final_choices=_stream_choices_snapshot(final_parts, final_tool_calls),
                compression_enabled=compression_enabled,
                compression_level=compression_level,
                compression_result=compression_result,
                compressed_messages=payload["messages"],
                prompt_security=prompt_security,
                skill_assessment=skill_assessment,
                request_duration_ms=(time.perf_counter() - started_at) * 1000,
                upstream_duration_ms=(time.perf_counter() - upstream_started_at) * 1000,
                ttft_ms=(first_output_at - started_at) * 1000 if first_output_at is not None else None,
                trace_context=trace_context,
            )
        except HTTPException as exc:
            _record_llm_error(
                db,
                request_id=request_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                user_ref=user_ref,
                key=key,
                model_name=model.name,
                bypass_pii=bypass_pii,
                error=str(exc.detail),
                compression_enabled=compression_enabled,
                compression_level=compression_level,
                skill_assessment=skill_assessment,
                request_duration_ms=(time.perf_counter() - started_at) * 1000,
                upstream_duration_ms=(time.perf_counter() - upstream_started_at) * 1000,
                trace_context=trace_context,
            )
            yield f"data: {json.dumps({'error': {'message': str(exc.detail), 'type': 'upstream_error'}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            _release_key_slot(key)

    return event_generator()


def _laplace_noise(epsilon: float) -> float:
    u = random.random() - 0.5
    return -math.copysign(math.log(1 - 2 * abs(u)) / epsilon, u)


def _record_llm_success(
    db: Session,
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    key: models.LlmApiKey,
    model_name: str,
    bypass_pii: bool,
    usage: dict[str, Any],
    detected_counts: dict[str, int],
    created_total: int,
    reused_total: int,
    policy: models.PrivacyPolicy,
    original_messages: list[dict[str, Any]],
    upstream_messages: list[dict[str, Any]],
    masked_choices: list[dict[str, Any]],
    final_choices: list[dict[str, Any]],
    compression_enabled: bool = False,
    compression_level: str = "auto",
    compression_result: Any = None,
    compressed_messages: list[dict[str, Any]] | None = None,
    prompt_security: dict[str, Any] | None = None,
    skill_assessment: GatewaySkillAssessment | None = None,
    request_duration_ms: float = 0.0,
    upstream_duration_ms: float = 0.0,
    ttft_ms: float | None = None,
    trace_context: dict[str, str | None] | None = None,
) -> None:
    owner_meta = _key_owner_meta(db, key)
    platform_duration_ms = max(0.0, request_duration_ms - upstream_duration_ms)
    db.add(
        models.LlmRequestAudit(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            group_id=key.group_id,
            api_key_id=key.id,
            **_audit_identity_fields(key),
            **(skill_assessment or GatewaySkillAssessment()).audit_fields(),
            model=model_name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            detected_counts_json=_json_dumps(detected_counts),
            created_tokens=created_total,
            reused_tokens=reused_total,
            compression_enabled=compression_enabled,
            compression_level=compression_level if compression_enabled else None,
            request_duration_ms=round(request_duration_ms, 2),
            upstream_duration_ms=round(upstream_duration_ms, 2),
            platform_duration_ms=round(platform_duration_ms, 2),
            prompt_guard_result_json=_json_dumps(prompt_security or {}),
        )
    )
    db.add(
        models.LlmUsageMetric(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            group_id=key.group_id,
            api_key_id=key.id,
            model=model_name,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            pii_hits_json=_json_dumps(detected_counts),
            created_tokens=created_total,
            reused_tokens=reused_total,
            pre_compression_tokens=compression_result.pre_tokens if compression_result else 0,
            post_compression_tokens=compression_result.post_tokens if compression_result else 0,
            tokens_saved=(min(compression_result.tokens_saved, int(usage.get("prompt_tokens") or 0)) if compression_result else 0),
            compression_ratio=compression_result.ratio if compression_result else 0.0,
            compression_duration_ms=compression_result.duration_ms if compression_result else 0.0,
        )
    )
    _save_trace(
        db,
        request_id=request_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        model=model_name,
        bypass_pii=bypass_pii,
        ttl_days=policy.mapping_ttl_days,
        stages={
            "meta": {
                "request_id": request_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "model": model_name,
                "bypass_pii": bypass_pii,
                **owner_meta,
                **(skill_assessment or GatewaySkillAssessment()).trace_fields(),
                "created_at": int(time.time()),
                "request_duration_ms": round(request_duration_ms, 2),
                "upstream_duration_ms": round(upstream_duration_ms, 2),
                "platform_duration_ms": round(platform_duration_ms, 2),
                "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "prompt_security_risk": (prompt_security or {}).get("risk_level", "none"),
                "prompt_security_action": (prompt_security or {}).get("action", "off"),
            },
            "prompt_security": prompt_security or {},
            "original": {"messages": original_messages},
            "masked": {"messages": upstream_messages},
            "compressed": {
                "messages": compressed_messages if compressed_messages else upstream_messages,
                "enabled": compression_enabled,
                "level": compression_level if compression_enabled else None,
                "pre_tokens": compression_result.pre_tokens if compression_result else 0,
                "post_tokens": compression_result.post_tokens if compression_result else 0,
                "tokens_saved": compression_result.tokens_saved if compression_result else 0,
                "ratio": compression_result.ratio if compression_result else 0,
                "duration_ms": compression_result.duration_ms if compression_result else 0,
            },
            "masked_response": {"choices": masked_choices},
            "final_response": {"choices": final_choices},
        },
    )
    db.commit()
    _publish_model_runtime_trace(
        db,
        key=key,
        trace_context=trace_context or {"session_id": conversation_id},
        tenant_id=tenant_id,
        request_id=request_id,
        model_name=model_name,
        request_payload={"messages": original_messages},
        redacted_request={"messages": upstream_messages},
        response_payload={"choices": final_choices},
        redacted_response={"choices": masked_choices},
        usage=usage,
        prompt_security=prompt_security,
        duration_ms=request_duration_ms,
        upstream_duration_ms=upstream_duration_ms,
        ttft_ms=ttft_ms,
    )


def _record_llm_error(
    db: Session,
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    key: models.LlmApiKey,
    model_name: str,
    bypass_pii: bool,
    error: str,
    compression_enabled: bool = False,
    compression_level: str = "auto",
    skill_assessment: GatewaySkillAssessment | None = None,
    request_duration_ms: float = 0.0,
    upstream_duration_ms: float = 0.0,
    trace_context: dict[str, str | None] | None = None,
) -> None:
    platform_duration_ms = max(0.0, request_duration_ms - upstream_duration_ms)
    db.add(
        models.LlmRequestAudit(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            group_id=key.group_id,
            api_key_id=key.id,
            **_audit_identity_fields(key),
            **(skill_assessment or GatewaySkillAssessment()).audit_fields(),
            model=model_name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            status="error",
            error=error,
            compression_enabled=compression_enabled,
            compression_level=compression_level if compression_enabled else None,
            request_duration_ms=round(request_duration_ms, 2),
            upstream_duration_ms=round(upstream_duration_ms, 2),
            platform_duration_ms=round(platform_duration_ms, 2),
        )
    )
    db.commit()
    _publish_model_runtime_trace(
        db,
        key=key,
        trace_context=trace_context or {"session_id": conversation_id},
        tenant_id=tenant_id,
        request_id=request_id,
        model_name=model_name,
        error=error,
        duration_ms=request_duration_ms,
        upstream_duration_ms=upstream_duration_ms,
    )


def _record_prompt_guard_block(
    db: Session,
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    user_ref: str,
    key,
    model_name: str,
    bypass_pii: bool,
    policy: models.PrivacyPolicy,
    original_messages: list[dict[str, Any]],
    prompt_security: dict[str, Any],
    skill_assessment: GatewaySkillAssessment | None,
    request_duration_ms: float,
    trace_context: dict[str, str | None] | None = None,
) -> None:
    owner_meta = _key_owner_meta(db, key)
    db.add(
        models.LlmRequestAudit(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            group_id=key.group_id,
            api_key_id=key.id,
            **_audit_identity_fields(key),
            **(skill_assessment or GatewaySkillAssessment()).audit_fields(),
            model=model_name,
            traffic_type="prompt_blocked",
            detected_counts_json="{}",
            prompt_guard_result_json=_json_dumps(prompt_security),
            status="blocked",
            error="Prompt 防护阻断高风险请求",
            request_duration_ms=round(request_duration_ms, 2),
            upstream_duration_ms=0.0,
            platform_duration_ms=round(request_duration_ms, 2),
        )
    )
    _save_trace(
        db,
        request_id=request_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        model=model_name,
        bypass_pii=bypass_pii,
        ttl_days=policy.mapping_ttl_days,
        stages={
            "meta": {
                "request_id": request_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "model": model_name,
                "bypass_pii": bypass_pii,
                **owner_meta,
                **(skill_assessment or GatewaySkillAssessment()).trace_fields(),
                "created_at": int(time.time()),
                "request_duration_ms": round(request_duration_ms, 2),
                "upstream_duration_ms": 0.0,
                "platform_duration_ms": round(request_duration_ms, 2),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "prompt_security_risk": prompt_security.get("risk_level", "none"),
                "prompt_security_action": prompt_security.get("action", "block"),
            },
            "prompt_security": prompt_security,
            "original": {"messages": original_messages},
        },
    )
    db.commit()
    _publish_model_runtime_trace(
        db,
        key=key,
        trace_context=trace_context or {"session_id": conversation_id},
        tenant_id=tenant_id,
        request_id=request_id,
        model_name=model_name,
        request_payload={"messages": original_messages},
        redacted_request={"messages": []},
        prompt_security=prompt_security,
        duration_ms=request_duration_ms,
        upstream_duration_ms=0.0,
        error="prompt_security_blocked",
        blocked=True,
    )


@admin_router.get("/users", response_model=list[schemas.User])
async def list_users(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return [_user_response(db, row) for row in db.query(models.User).order_by(models.User.id.asc()).all()]


@admin_router.post("/users", response_model=schemas.User)
async def create_managed_user(
    body: schemas.UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    from ..iam import create_account
    return create_account(db, request, current_user, body.model_dump())


@admin_router.put("/users/{user_id}", response_model=schemas.User)
async def update_managed_user(
    user_id: int,
    body: schemas.UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = body.model_dump(exclude_unset=True)
    from ..iam import update_account
    return update_account(db, request, current_user, user, data)


@admin_router.get("/groups", response_model=list[schemas.UserGroupResponse])
async def list_groups(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return [_group_response(db, row) for row in db.query(models.UserGroup).order_by(models.UserGroup.id.asc()).all()]


@admin_router.post("/groups", response_model=schemas.UserGroupResponse)
async def create_group(
    body: schemas.UserGroupCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.UserGroup).filter(models.UserGroup.name == body.name).first():
        raise HTTPException(status_code=400, detail="用户组已存在")
    group = models.UserGroup(name=body.name, description=body.description)
    db.add(group)
    db.flush()
    _sync_group_members(db, group.id, body.user_ids)
    if body.privacy_policy_id is not None:
        _bind_group_policy(db, group.id, body.privacy_policy_id)
    db.commit()
    db.refresh(group)
    return _group_response(db, group)


@admin_router.put("/groups/{group_id}", response_model=schemas.UserGroupResponse)
async def update_group(
    group_id: int,
    body: schemas.UserGroupUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    group = db.query(models.UserGroup).filter(models.UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在")
    data = body.model_dump(exclude_unset=True)
    user_ids = data.pop("user_ids", None)
    privacy_policy_id = data.pop("privacy_policy_id", None)
    for field, value in data.items():
        setattr(group, field, value)
    if user_ids is not None:
        _sync_group_members(db, group.id, user_ids)
    if "privacy_policy_id" in body.model_fields_set:
        _bind_group_policy(db, group.id, privacy_policy_id)
    db.commit()
    db.refresh(group)
    return _group_response(db, group)


@admin_router.get("/model-providers", response_model=list[schemas.ModelProviderResponse])
async def list_model_providers(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return [_provider_response(row) for row in db.query(models.ModelProvider).order_by(models.ModelProvider.id.asc()).all()]


@admin_router.post("/model-providers", response_model=schemas.ModelProviderResponse)
async def create_model_provider(
    body: schemas.ModelProviderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.ModelProvider).filter(models.ModelProvider.name == body.name).first():
        raise HTTPException(status_code=400, detail="模型供应商已存在")
    data = body.model_dump()
    data["api_key"] = _protect_secret(data.get("api_key"))
    row = models.ModelProvider(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _provider_response(row)


@admin_router.put("/model-providers/{provider_id}", response_model=schemas.ModelProviderResponse)
async def update_model_provider(
    provider_id: int,
    body: schemas.ModelProviderUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelProvider).filter(models.ModelProvider.id == provider_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    data = body.model_dump(exclude_unset=True)
    clear_api_key = data.pop("clear_api_key", False)
    if clear_api_key:
        row.api_key = None
    for field, value in data.items():
        if field == "api_key" and value is None:
            continue
        if field == "api_key":
            value = _protect_secret(value)
        setattr(row, field, value)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _provider_response(row)


@admin_router.delete("/model-providers/{provider_id}")
async def delete_model_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.ModelEndpoint).filter(models.ModelEndpoint.provider_id == provider_id).first():
        raise HTTPException(status_code=400, detail="请先删除或迁移该供应商下的模型")
    row = db.query(models.ModelProvider).filter(models.ModelProvider.id == provider_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@admin_router.get("/model-providers/{provider_id}/models")
async def discover_provider_models(
    provider_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelProvider).filter(models.ModelProvider.id == provider_id).first()
    if not row:
        raise ApiError(404, "model.provider_not_found", "模型供应商不存在", "Model provider not found")
    base = row.base_url.rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/responses"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    _, _, headers = _upstream_request(row, {"model": "", "messages": []})
    found = {}
    params = {}
    try:
        async with httpx.AsyncClient(timeout=min(row.timeout_seconds, 15)) as client:
            for _ in range(100):
                response = await client.get(f"{base}/models", headers=headers, params=params)
                if not 200 <= response.status_code < 300:
                    raise ApiError(502, "model_discovery.upstream_http_error", "供应商模型列表接口请求失败，可自定义添加模型", "Provider model listing failed; models can be added manually")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("Invalid model list")
                for item in payload["data"]:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                        raise ValueError("Invalid model ID")
                    found[item["id"]] = {"name": item["id"], "display_name": item.get("display_name") if isinstance(item.get("display_name"), str) else None}
                if not payload.get("has_more"):
                    return {"models": sorted(found.values(), key=lambda item: item["name"])}
                cursor = payload.get("last_id")
                if not isinstance(cursor, str) or not cursor or cursor == params.get("after_id"):
                    raise ValueError("Invalid model cursor")
                params = {"after_id": cursor}
            raise ValueError("Model list pagination limit exceeded")
    except httpx.RequestError:
        raise ApiError(502, "model_discovery.connection_failed", "无法连接供应商，可重试或自定义添加模型", "Could not connect to the provider; retry or add models manually") from None
    except ValueError:
        raise ApiError(502, "model_discovery.invalid_response", "供应商模型列表格式无效，可自定义添加模型", "Invalid provider model list; models can be added manually") from None


@admin_router.post("/model-providers/{provider_id}/test")
async def test_model_provider(
    provider_id: int,
    body: schemas.ModelProviderTestRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelProvider).filter(models.ModelProvider.id == provider_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    model_name = body.model.strip()
    if not model_name:
        raise ApiError(
            422,
            "model_provider_test.model_required",
            "请输入测试模型",
            "Enter a model to test",
        )
    url, payload, headers = _upstream_request(
        row,
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_tokens": 128,
            "stream": False,
        },
    )
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=min(row.timeout_seconds, 15)) as client:
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        return {
            "ok": False,
            "model": model_name,
            "endpoint": url,
            "error_code": "model_provider_test.connection_failed",
            "error": str(exc),
        }

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if not 200 <= response.status_code < 300:
        return {
            "ok": False,
            "status_code": response.status_code,
            "model": model_name,
            "endpoint": url,
            "duration_ms": duration_ms,
            "error_code": "model_provider_test.upstream_http_error",
            "error": _upstream_error_summary(response),
        }
    try:
        result = response.json()
    except ValueError:
        result = None
    if not _is_valid_provider_test_response((getattr(row, "api_format", "openai") or "openai"), result):
        return {
            "ok": False,
            "status_code": response.status_code,
            "model": model_name,
            "endpoint": url,
            "duration_ms": duration_ms,
            "error_code": "model_provider_test.invalid_response",
        }
    return {
        "ok": True,
        "status_code": response.status_code,
        "model": model_name,
        "endpoint": url,
        "duration_ms": duration_ms,
    }


@admin_router.get("/models", response_model=list[schemas.ModelEndpointResponse])
async def list_models(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return [_model_response(db, row) for row in db.query(models.ModelEndpoint).order_by(models.ModelEndpoint.id.asc()).all()]


@admin_router.post("/models", response_model=schemas.ModelEndpointResponse)
async def create_model(
    body: schemas.ModelEndpointCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    provider = db.get(models.ModelProvider, body.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    upstream_name = (body.upstream_name or body.name or "").strip()
    if not upstream_name:
        raise ApiError(422, "model.upstream_required", "请输入上游模型名", "Enter an upstream model name")
    if db.query(models.ModelEndpoint).filter(models.ModelEndpoint.provider_id == provider.id, func.coalesce(models.ModelEndpoint.upstream_name, models.ModelEndpoint.name) == upstream_name).first():
        raise ApiError(409, "model.provider_duplicate", "当前供应商已添加该模型", "This provider already has this model")
    name = (body.name or "").strip()
    if not name:
        name = upstream_name
        if db.query(models.ModelEndpoint).filter_by(name=name).first():
            prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", provider.name).strip("-") or f"provider-{provider.id}"
            base = f"{prefix}/{upstream_name}"[:120]
            name = base
            counter = 2
            while db.query(models.ModelEndpoint).filter_by(name=name).first():
                name = f"{base}-{counter}"
                counter += 1
    elif db.query(models.ModelEndpoint).filter_by(name=name).first():
        raise ApiError(409, "model.gateway_name_duplicate", "网关调用名称已存在，请使用其他名称", "Gateway model name already exists; choose another name")
    if body.is_default:
        db.query(models.ModelEndpoint).update({"is_default": False})
    row = models.ModelEndpoint(**{**body.model_dump(), "name": name, "upstream_name": upstream_name})
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "model.configuration_conflict", "模型配置重复，请刷新后重试", "Model configuration conflicts; refresh and retry") from None
    db.refresh(row)
    return _model_response(db, row)


@admin_router.put("/models/{model_id}", response_model=schemas.ModelEndpointResponse)
async def update_model(
    model_id: int,
    body: schemas.ModelEndpointUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id == model_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != row.name:
        raise ApiError(422, "model.gateway_name_immutable", "网关调用名称创建后保持固定，以保留权限和调用绑定", "Gateway model names are fixed after creation to preserve access and caller bindings")
    provider_id = data.get("provider_id", row.provider_id)
    if not db.get(models.ModelProvider, provider_id):
        raise ApiError(404, "model.provider_not_found", "模型供应商不存在", "Model provider not found")
    upstream_name = (data.get("upstream_name", row.upstream_name or row.name) or "").strip()
    if not upstream_name:
        raise ApiError(422, "model.upstream_required", "请输入上游模型名", "Enter an upstream model name")
    if db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id != row.id, models.ModelEndpoint.provider_id == provider_id, func.coalesce(models.ModelEndpoint.upstream_name, models.ModelEndpoint.name) == upstream_name).first():
        raise ApiError(409, "model.provider_duplicate", "当前供应商已添加该模型", "This provider already has this model")
    data["upstream_name"] = upstream_name
    if data.get("is_default"):
        db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id != model_id).update({"is_default": False})
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_at = _now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "model.configuration_conflict", "模型配置重复，请刷新后重试", "Model configuration conflicts; refresh and retry") from None
    db.refresh(row)
    return _model_response(db, row)


@admin_router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id == model_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@admin_router.post("/prompt-guard/test")
async def test_prompt_guard(
    body: schemas.PromptGuardTestRequest,
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    messages = [_strip_undefined_values(message.model_dump()) for message in body.messages]
    sources = _message_content_sources(messages, {})
    return _scan_prompt_security(messages, mode=body.mode, llm_review=body.llm_review, sources=sources)


@admin_router.get("/llm-api-keys", response_model=list[schemas.LlmApiKeyResponse])
async def list_llm_api_keys(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    rows = _api_key_query_for_user(db, current_user).order_by(models.LlmApiKey.id.desc()).all()
    return [_api_key_response(row) for row in rows]


@admin_router.post("/llm-api-keys", response_model=schemas.LlmApiKeyResponse)
async def create_llm_api_key(
    body: schemas.LlmApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    raise ApiError(
        410,
        "credential.legacy_llm_key_issuance_removed",
        "旧 LLM API Key 已停止签发，请在统一凭证中心创建模型调用凭证",
        "Legacy LLM API Key issuance has been removed; create a model gateway credential in the Credential Center",
    )


@admin_router.put("/llm-api-keys/{key_id}", response_model=schemas.LlmApiKeyResponse)
async def update_llm_api_key(
    key_id: int,
    body: schemas.LlmApiKeyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _api_key_query_for_user(db, current_user).filter(models.LlmApiKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    data = body.model_dump(exclude_unset=True)
    if "user_id" in data and data["user_id"] and not db.query(models.User).filter(models.User.id == data["user_id"]).first():
        raise HTTPException(status_code=404, detail="用户不存在")
    if "group_id" in data and data["group_id"] and not db.query(models.UserGroup).filter(models.UserGroup.id == data["group_id"]).first():
        raise HTTPException(status_code=404, detail="用户组不存在")
    allowed_models = data.pop("allowed_models", None)
    if allowed_models is not None:
        row.allowed_models_json = _json_dumps(allowed_models)
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _api_key_response(row)


@admin_router.post("/llm-api-keys/{key_id}/revoke")
async def revoke_llm_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _api_key_query_for_user(db, current_user).filter(models.LlmApiKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    row.status = "revoked"
    db.commit()
    return {"status": "revoked"}


@admin_router.delete("/llm-api-keys/{key_id}")
async def delete_llm_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _api_key_query_for_user(db, current_user).filter(models.LlmApiKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@admin_router.get("/privacy-policies", response_model=list[schemas.PrivacyPolicyResponse])
async def list_privacy_policies(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    default_policy = _get_default_policy(db)
    return [
        _policy_response(row, default_policy_id=default_policy.id)
        for row in db.query(models.PrivacyPolicy).order_by(models.PrivacyPolicy.id.asc()).all()
    ]


@admin_router.post("/privacy-policies", response_model=schemas.PrivacyPolicyResponse)
async def upsert_privacy_policy(
    body: schemas.PrivacyPolicyPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    from .. import iam
    request.state.iam_permission = "privacy:update" if body.id else "privacy:create"
    if not iam.permission_codes(db, current_user) & {"privacy:create", "privacy:update"}:
        iam.check(db, current_user, request.state.iam_permission)
    if body.group_id and not db.query(models.UserGroup).filter(models.UserGroup.id == body.group_id).first():
        raise HTTPException(status_code=404, detail="用户组不存在")
    row = None
    if body.id:
        row = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.id == body.id).first()
        if not row:
            raise HTTPException(status_code=404, detail="隐私策略不存在")
    elif body.group_id:
        row = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == body.group_id).first()
    permission = "privacy:create" if row is None else "privacy:update"
    request.state.iam_permission = permission
    iam.check(db, current_user, permission)
    default_policy = _get_default_policy(db)
    if row is None:
        row = models.PrivacyPolicy(group_id=body.group_id, entity_types_json="[]", name=body.name)
        db.add(row)
    if row.id == default_policy.id and body.group_id is not None:
        raise HTTPException(status_code=400, detail="系统默认隐私策略不能绑定用户组")
    if body.name.strip() == "默认隐私策略" and row.id != default_policy.id:
        raise HTTPException(status_code=400, detail="隐私策略名称已存在，请使用其他名称")
    data = body.model_dump()
    data.pop("id", None)
    entity_types = _normalize_entity_types(data.pop("entity_types") or DEFAULT_ENTITY_TYPES)
    entity_rules = {
        k: v for k, v in (data.pop("entity_rules") or {}).items()
        if v and k not in REMOVED_ENTITY_TYPES and k not in LEGACY_ENTITY_ALIASES and k != "PERSON"
    }
    for field, value in data.items():
        setattr(row, field, value)
    row.entity_types_json = _json_dumps(entity_types)
    row.entity_rules_json = _json_dumps({**DEFAULT_ENTITY_RULES, **entity_rules})
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _policy_response(row, default_policy_id=default_policy.id)


@admin_router.delete("/privacy-policies/{policy_id}")
async def delete_privacy_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.id == policy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="隐私策略不存在")
    if row.id == _get_default_policy(db).id:
        raise HTTPException(status_code=400, detail="默认隐私策略不能删除")
    if row.group_id is not None:
        raise HTTPException(status_code=400, detail="隐私策略已绑定用户组，请先解绑")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@admin_router.get("/model-gateway/skill-alerts", response_model=schemas.ModelSkillAlertListResponse)
async def list_model_skill_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    days: int = Query(default=7, ge=1, le=90),
    category: str = Query(default="actionable", pattern="^(actionable|missing|observation|all)$"),
    severity: str | None = Query(default=None, pattern="^(info|medium|high)$"),
    alert_code: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    skill_name: str | None = Query(default=None, max_length=255),
    model: str | None = Query(default=None, max_length=128),
    q: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_get_privacy_audit_user),
):
    del current_user
    since = _now() - timedelta(days=days)
    visible_states = ("suspicious", "missing", "declared_trusted")
    base_query = db.query(models.LlmRequestAudit).filter(
        models.LlmRequestAudit.created_at >= since,
        models.LlmRequestAudit.skill_trust_state.in_(visible_states),
    )
    summary = schemas.ModelSkillAlertSummary(
        actionable=base_query.filter(models.LlmRequestAudit.skill_trust_state == "suspicious").count(),
        missing=base_query.filter(models.LlmRequestAudit.skill_trust_state == "missing").count(),
        observations=base_query.filter(models.LlmRequestAudit.skill_trust_state == "declared_trusted").count(),
        affected_agents=(
            base_query.filter(
                models.LlmRequestAudit.skill_trust_state == "suspicious",
                models.LlmRequestAudit.agent_id.is_not(None),
            )
            .with_entities(func.count(func.distinct(models.LlmRequestAudit.agent_id)))
            .scalar()
            or 0
        ),
    )

    query = base_query
    state_by_category = {
        "actionable": "suspicious",
        "missing": "missing",
        "observation": "declared_trusted",
    }
    if category in state_by_category:
        query = query.filter(models.LlmRequestAudit.skill_trust_state == state_by_category[category])
    if severity:
        query = query.filter(models.LlmRequestAudit.skill_alert_severity == severity)
    if alert_code:
        query = query.filter(models.LlmRequestAudit.skill_alert_codes_json.contains(f'"{alert_code}"'))
    if agent_id:
        query = query.filter(models.LlmRequestAudit.agent_id == agent_id)
    if skill_name:
        query = query.filter(models.LlmRequestAudit.skill_name.ilike(f"%{skill_name.strip()}%"))
    if model:
        query = query.filter(models.LlmRequestAudit.model == model)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.LlmRequestAudit.request_id.ilike(keyword),
                models.LlmRequestAudit.agent_id.ilike(keyword),
                models.LlmRequestAudit.skill_id.ilike(keyword),
                models.LlmRequestAudit.skill_version_id.ilike(keyword),
                models.LlmRequestAudit.skill_name.ilike(keyword),
            )
        )

    total = query.count()
    rows = (
        query.order_by(models.LlmRequestAudit.created_at.desc(), models.LlmRequestAudit.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    access_token_ids = {
        row.api_key_id for row in rows
        if row.api_key_id is not None and row.credential_type != "legacy_llm_api_key"
    }
    llm_key_ids = {
        row.api_key_id for row in rows
        if row.api_key_id is not None and row.credential_type == "legacy_llm_api_key"
    }
    agent_ids = {row.agent_id for row in rows if row.agent_id}
    access_token_names = {
        row.id: row.name
        for row in db.query(models.AccessToken).filter(models.AccessToken.id.in_(access_token_ids)).all()
    } if access_token_ids else {}
    llm_key_names = {
        row.id: row.name
        for row in db.query(models.LlmApiKey).filter(models.LlmApiKey.id.in_(llm_key_ids)).all()
    } if llm_key_ids else {}
    agent_names = {
        row.agent_id: row.name
        for row in db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id.in_(agent_ids)).all()
    } if agent_ids else {}

    items = []
    for row in rows:
        credential_names = llm_key_names if row.credential_type == "legacy_llm_api_key" else access_token_names
        items.append(
            schemas.ModelSkillAlertItem(
                id=row.id,
                request_id=row.request_id,
                created_at=row.created_at,
                severity=row.skill_alert_severity,
                trust_state=row.skill_trust_state,
                alert_codes=_json_loads(row.skill_alert_codes_json, []),
                agent_id=row.agent_id,
                agent_name=agent_names.get(row.agent_id),
                skill_id=row.skill_id,
                skill_version_id=row.skill_version_id,
                skill_name=row.skill_name,
                context_source=row.skill_context_source,
                model=row.model,
                credential_type=row.credential_type,
                credential_name=credential_names.get(row.api_key_id),
                request_status=row.status,
            )
        )
    return schemas.ModelSkillAlertListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        days=days,
        summary=summary,
    )


@admin_router.get("/privacy/traces")
async def list_traces(
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_get_privacy_audit_user),
):
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    query = db.query(models.LlmPipelineTrace).filter(models.LlmPipelineTrace.stage == "meta")
    total = query.count()
    rows = (
        query
        .order_by(models.LlmPipelineTrace.created_at.desc())
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .all()
    )
    request_ids = [row.request_id for row in rows]
    metric_by_request_id = {
        metric.request_id: metric
        for metric in (
            db.query(models.LlmUsageMetric)
            .filter(models.LlmUsageMetric.request_id.in_(request_ids))
            .all()
            if request_ids
            else []
        )
    }
    audit_by_request_id = {
        audit.request_id: audit
        for audit in (
            db.query(models.LlmRequestAudit)
            .filter(models.LlmRequestAudit.request_id.in_(request_ids))
            .all()
            if request_ids
            else []
        )
    }
    compressed_by_request_id = {
        compressed.request_id: _json_loads(compressed.payload_json, {})
        for compressed in (
            db.query(models.LlmPipelineTrace)
            .filter(
                models.LlmPipelineTrace.request_id.in_(request_ids),
                models.LlmPipelineTrace.stage == "compressed",
            )
            .all()
            if request_ids
            else []
        )
    }
    traces = []
    for row in rows:
        payload = _json_loads(row.payload_json, {})
        metric = metric_by_request_id.get(row.request_id)
        audit = audit_by_request_id.get(row.request_id)
        compressed = compressed_by_request_id.get(row.request_id, {})
        provider_prompt_tokens = metric.prompt_tokens if metric else payload.get("prompt_tokens", 0)
        compression_enabled = compressed.get("enabled") is True
        original_input_tokens = compressed.get("pre_tokens") if compression_enabled else provider_prompt_tokens
        model_input_tokens = compressed.get("post_tokens") if compression_enabled else provider_prompt_tokens
        if not isinstance(original_input_tokens, int) or isinstance(original_input_tokens, bool):
            original_input_tokens = provider_prompt_tokens
        if not isinstance(model_input_tokens, int) or isinstance(model_input_tokens, bool):
            model_input_tokens = provider_prompt_tokens
        detected_counts = _json_loads(audit.detected_counts_json, None) if audit else None
        has_pii = (
            any(isinstance(count, int) and count > 0 for count in detected_counts.values())
            if audit and not row.bypass_pii and audit.traffic_type == "pii_checked" and isinstance(detected_counts, dict)
            else None
        )
        traces.append(
            {
                **payload,
                "request_id": row.request_id,
                "tenant_id": row.tenant_id,
                "conversation_id": row.conversation_id,
                "model": row.model,
                "bypass_pii": row.bypass_pii,
                "has_pii": has_pii,
                "created_at": row.created_at.isoformat(),
                "prompt_tokens": provider_prompt_tokens,
                "original_input_tokens": original_input_tokens,
                "model_input_tokens": model_input_tokens,
                "completion_tokens": metric.completion_tokens if metric else payload.get("completion_tokens", 0),
                "prompt_security_risk": payload.get("prompt_security_risk", "none"),
                "prompt_security_action": payload.get("prompt_security_action", "off"),
            }
        )
    return {"traces": traces, "total": total, "page": safe_page, "page_size": safe_page_size}


@admin_router.get("/privacy/traces/{request_id}")
async def get_trace_detail(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_get_privacy_audit_user),
):
    rows = (
        db.query(models.LlmPipelineTrace)
        .filter(models.LlmPipelineTrace.request_id == request_id)
        .order_by(models.LlmPipelineTrace.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    stages = {row.stage: _json_loads(row.payload_json, {}) for row in rows}
    metric = db.query(models.LlmUsageMetric).filter(models.LlmUsageMetric.request_id == request_id).first()
    if metric:
        stages.setdefault("meta", {}).update(
            {
                "prompt_tokens": metric.prompt_tokens,
                "completion_tokens": metric.completion_tokens,
                "total_tokens": metric.total_tokens,
            }
        )
    tokens = set(re.findall(r"<[A-Z][A-Z0-9_]*:[a-z]+_[0-9a-f]{10}>", _json_dumps(stages)))
    mappings = []
    if tokens:
        mappings = db.query(models.PseudonymMapping).filter(
            models.PseudonymMapping.tenant_id == rows[0].tenant_id,
            models.PseudonymMapping.conversation_id == rows[0].conversation_id,
            models.PseudonymMapping.token.in_(tokens),
            models.PseudonymMapping.expires_at >= _now(),
        ).all()
    return {
        "request_id": request_id,
        "stages": stages,
        "pii_mappings": [
            {"token": row.token, "original_value": row.original_value, "entity_type": row.entity_type}
            for row in mappings
        ],
    }


def _mapping_payload(row: models.PseudonymMapping) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "conversation_id": row.conversation_id,
        "token": row.token,
        "entity_type": row.entity_type,
        "original_value": row.original_value,
        "normalized_value": row.normalized_value,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
    }


@admin_router.get("/privacy/mappings")
async def list_privacy_mappings(
    q: str | None = None,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    query = db.query(models.PseudonymMapping).filter(models.PseudonymMapping.expires_at >= _now())
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.PseudonymMapping.tenant_id.ilike(pattern),
                models.PseudonymMapping.conversation_id.ilike(pattern),
                models.PseudonymMapping.original_value.ilike(pattern),
            )
        )
    total = query.count()
    rows = (
        query.order_by(models.PseudonymMapping.created_at.desc(), models.PseudonymMapping.id.desc())
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .all()
    )
    return {
        "mappings": [_mapping_payload(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
    }


@admin_router.delete("/privacy/mappings/{mapping_id}")
async def delete_privacy_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.PseudonymMapping).filter(models.PseudonymMapping.id == mapping_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="映射不存在")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@admin_router.get("/privacy/conversations/{conversation_id}/mappings")
async def get_conversation_mappings(
    conversation_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    rows = db.query(models.PseudonymMapping).filter(
        models.PseudonymMapping.tenant_id == tenant_id,
        models.PseudonymMapping.conversation_id == conversation_id,
        models.PseudonymMapping.expires_at >= _now(),
    ).order_by(models.PseudonymMapping.id.asc()).all()
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "count": len(rows),
        "mappings": [_mapping_payload(row) for row in rows],
    }


@admin_router.delete("/privacy/conversations/{conversation_id}/mappings")
async def delete_conversation_mappings(
    conversation_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    deleted = db.query(models.PseudonymMapping).filter(
        models.PseudonymMapping.tenant_id == tenant_id,
        models.PseudonymMapping.conversation_id == conversation_id,
    ).delete()
    db.commit()
    return {"deleted": deleted}


@admin_router.get("/privacy/stats")
async def get_privacy_stats(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    policy = _get_default_policy(db)
    api_key_ids = [row.id for row in _api_key_query_for_user(db, current_user).all()]
    access_token_ids = [
        row.id for row in db.query(models.AccessToken)
        .filter(models.AccessToken.token_type.in_(["model_gateway", "agent_runtime"]))
        .filter(or_(models.AccessToken.user_id == current_user.id, models.AccessToken.created_by == current_user.username))
        .all()
        if "model:chat" in _json_loads(row.scopes_json, [])
    ]
    api_key_ids = sorted(set(api_key_ids + access_token_ids))
    audit_query = db.query(models.LlmRequestAudit).filter(models.LlmRequestAudit.api_key_id.in_(api_key_ids))
    total = audit_query.count()
    pii_checked = audit_query.filter(models.LlmRequestAudit.traffic_type == "pii_checked").count()
    request_ids = [row[0] for row in audit_query.with_entities(models.LlmRequestAudit.request_id).all()]
    mappings = (
        db.query(models.PseudonymMapping)
        .filter(models.PseudonymMapping.request_id.in_(request_ids))
        .count()
        if request_ids
        else 0
    )
    metrics = db.query(models.LlmUsageMetric).filter(models.LlmUsageMetric.api_key_id.in_(api_key_ids)).all()
    created_tokens = sum(row.created_tokens or 0 for row in metrics)
    reused_tokens = sum(row.reused_tokens or 0 for row in metrics)
    pii_hits: dict[str, int] = {}
    prompt_guard_events = 0
    prompt_guard_blocked = 0
    for row in metrics:
        for entity_type, count in _json_loads(row.pii_hits_json, {}).items():
            pii_hits[entity_type] = pii_hits.get(entity_type, 0) + int(count or 0)
    for row in audit_query.all():
        guard = _json_loads(getattr(row, "prompt_guard_result_json", None), {})
        if guard.get("enabled") and guard.get("findings_count", 0):
            prompt_guard_events += 1
        if guard.get("blocked") or row.status == "blocked":
            prompt_guard_blocked += 1
    def protected(value: int) -> int | None:
        if policy.dp_enabled and value < policy.dp_min_count:
            return None
        if policy.dp_enabled:
            return max(0, int(round(value + _laplace_noise(policy.dp_epsilon))))
        return value
    return {
        "total_requests": protected(total),
        "pii_checked_requests": protected(pii_checked),
        "active_mappings": protected(mappings),
        "created_tokens": protected(created_tokens),
        "reused_tokens": protected(reused_tokens),
        "prompt_guard_events": protected(prompt_guard_events),
        "prompt_guard_blocked": protected(prompt_guard_blocked),
        "pii_hits": {entity_type: protected(count) for entity_type, count in pii_hits.items()},
        "dp_enabled": policy.dp_enabled,
        "dp_min_count": policy.dp_min_count,
    }


# ── 压缩自检 API ──────────────────────────────────────────────────


@runtime_router.get("/llm-stats/compression-self-test")
async def compression_self_test():
    """验证压缩模块是否正常加载（无需认证，无敏感数据）"""
    from .. import compression as comp_module

    test_messages = [
        {"role": "user", "content": "test"},
        {"role": "tool", "content": '[{"id":1,"name":"a"},{"id":2,"name":"b"},{"id":3,"name":"c"}]' * 10},
    ]

    # 直接测 headroom 原始返回
    headroom_raw = {}
    headroom_error = None
    try:
        from headroom import compress
        raw = compress(test_messages, model="gpt-4o")
        headroom_raw = {
            "tokens_before": raw.tokens_before,
            "tokens_after": raw.tokens_after,
            "tokens_saved": raw.tokens_saved,
            "transforms": list(raw.transforms_applied) if raw.transforms_applied else [],
        }
    except ImportError as e:
        headroom_error = f"ImportError: {e}"
    except Exception as e:
        headroom_error = f"{type(e).__name__}: {e}"

    # 再测封装函数
    wrapper_error = None
    result = None
    try:
        result = comp_module.compress_messages(test_messages, model="gpt-4o", level="auto")
    except Exception as e:
        wrapper_error = f"{type(e).__name__}: {e}"

    return {
        "module_version": getattr(comp_module, "__version__", "unknown"),
        "headroom_available": headroom_error is None,
        "headroom_error": headroom_error,
        "headroom_raw": headroom_raw,
        "wrapper_error": wrapper_error,
        "test_pre_tokens": result.pre_tokens if result else 0,
        "test_post_tokens": result.post_tokens if result else 0,
        "test_tokens_saved": result.tokens_saved if result else 0,
        "test_transforms": result.transforms_applied if result else [],
        "test_duration_ms": result.duration_ms if result else 0,
        "verdict": "OK" if (result and (result.tokens_saved > 0 or result.pre_tokens > 50)) else "NEEDS_INVESTIGATION",
    }


# ── LLM 用量统计 API ──────────────────────────────────────────────

# 压缩诊断：近 10 条压缩请求的详细日志
@admin_router.get("/llm-stats/compression-diagnostics")
async def get_compression_diagnostics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """查看最近压缩请求的详细诊断信息，帮助排查压缩为什么是 0"""
    # 最近 10 条 compress_enabled=True 的审计记录
    audit_rows = (
        db.query(models.LlmRequestAudit)
        .filter(models.LlmRequestAudit.compression_enabled.is_(True))
        .order_by(models.LlmRequestAudit.created_at.desc())
        .limit(10)
        .all()
    )

    # 对应的用量指标
    request_ids = [r.request_id for r in audit_rows]
    metric_rows = (
        db.query(models.LlmUsageMetric)
        .filter(models.LlmUsageMetric.request_id.in_(request_ids))
        .all()
    ) if request_ids else []
    metric_by_id = {m.request_id: m for m in metric_rows}

    # 对应的 trace
    trace_rows = (
        db.query(models.LlmPipelineTrace)
        .filter(
            models.LlmPipelineTrace.request_id.in_(request_ids),
            models.LlmPipelineTrace.stage == "compressed",
        )
        .all()
    ) if request_ids else []
    trace_by_id: dict[str, Any] = {}
    for t in trace_rows:
        trace_by_id.setdefault(t.request_id, {})
        try:
            trace_by_id[t.request_id] = json.loads(t.payload_json or "{}")
        except Exception:
            trace_by_id[t.request_id] = {"raw": t.payload_json}

    return {
        "compression_enabled_requests_found": len(audit_rows),
        "recent": [
            {
                "request_id": r.request_id,
                "model": r.model,
                "compression_level": r.compression_level,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "metrics": {
                    "prompt_tokens": m.prompt_tokens,
                    "completion_tokens": m.completion_tokens,
                    "tokens_saved": m.tokens_saved,
                    "compression_ratio": m.compression_ratio,
                    "pre_compression_tokens": m.pre_compression_tokens,
                    "post_compression_tokens": m.post_compression_tokens,
                    "compression_duration_ms": m.compression_duration_ms,
                } if (m := metric_by_id.get(r.request_id)) else None,
                "trace_compressed_stage": trace_by_id.get(r.request_id),
            }
            for r in audit_rows
        ],
    }


def _usage_base_query(db: Session, days: int, model: str | None = None):
    """查询最近 N 天的用量指标"""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    q = db.query(models.LlmUsageMetric).filter(
        models.LlmUsageMetric.created_at >= since,
    )
    if model:
        q = q.filter(models.LlmUsageMetric.model == model)
    return q


def _audit_base_query(db: Session, days: int, model: str | None = None):
    """查询最近 N 天的审计记录"""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    q = db.query(models.LlmRequestAudit).filter(
        models.LlmRequestAudit.created_at >= since,
    )
    if model:
        q = q.filter(models.LlmRequestAudit.model == model)
    return q


@admin_router.get("/llm-stats/overview")
async def get_llm_stats_overview(
    days: int = Query(default=30, ge=1, le=365),
    model: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """统计总览卡片数据"""
    metrics_q = _usage_base_query(db, days, model)
    audit_q = _audit_base_query(db, days, model)

    total_requests = audit_q.filter(models.LlmRequestAudit.status == "success").count()
    total_requests_with_error = audit_q.filter(models.LlmRequestAudit.status == "error").count()
    compression_requests = audit_q.filter(
        models.LlmRequestAudit.compression_enabled.is_(True),
        models.LlmRequestAudit.status == "success",
    ).count()

    agg = metrics_q.with_entities(
        func.coalesce(func.sum(models.LlmUsageMetric.prompt_tokens), 0),
        func.coalesce(func.sum(models.LlmUsageMetric.completion_tokens), 0),
        func.coalesce(func.sum(models.LlmUsageMetric.total_tokens), 0),
        func.coalesce(func.sum(models.LlmUsageMetric.tokens_saved), 0),
        func.coalesce(func.avg(models.LlmUsageMetric.compression_ratio), 0),
        func.coalesce(func.avg(models.LlmUsageMetric.compression_duration_ms), 0),
    ).first()

    prompt_tokens, completion_tokens, total_tokens, tokens_saved, avg_ratio, avg_duration = agg
    duration_agg = audit_q.with_entities(
        func.coalesce(func.avg(models.LlmRequestAudit.request_duration_ms), 0),
        func.coalesce(func.avg(models.LlmRequestAudit.upstream_duration_ms), 0),
        func.coalesce(func.avg(models.LlmRequestAudit.platform_duration_ms), 0),
    ).first()
    avg_request_ms, avg_upstream_ms, avg_platform_ms = duration_agg

    return {
        "days": days,
        "total_requests": total_requests,
        "error_requests": total_requests_with_error,
        "compression_requests": compression_requests,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
        "tokens_saved": int(tokens_saved),
        "avg_compression_ratio": round(float(avg_ratio or 0), 4),
        "avg_compression_ms": round(float(avg_duration or 0), 1),
        "avg_request_ms": round(float(avg_request_ms or 0), 1),
        "avg_upstream_ms": round(float(avg_upstream_ms or 0), 1),
        "avg_platform_ms": round(float(avg_platform_ms or 0), 1),
    }


@admin_router.get("/llm-stats/daily")
async def get_llm_stats_daily(
    days: int = Query(default=30, ge=1, le=365),
    model: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """按天统计的折线图数据"""
    since = _now() - timedelta(days=max(1, min(days, 365)))

    q = db.query(
        func.strftime("%Y-%m-%d", models.LlmUsageMetric.created_at).label("date"),
        func.coalesce(func.sum(models.LlmUsageMetric.prompt_tokens), 0).label("prompt"),
        func.coalesce(func.sum(models.LlmUsageMetric.completion_tokens), 0).label("completion"),
        func.coalesce(func.sum(models.LlmUsageMetric.tokens_saved), 0).label("saved"),
        func.count(models.LlmUsageMetric.id).label("requests"),
    ).filter(models.LlmUsageMetric.created_at >= since)
    if model:
        q = q.filter(models.LlmUsageMetric.model == model)
    rows = q.group_by("date").order_by("date").all()

    return {
        "days": days,
        "series": [
            {
                "date": row.date,
                "prompt_tokens": int(row.prompt),
                "completion_tokens": int(row.completion),
                "tokens_saved": int(row.saved),
                "requests": row.requests,
            }
            for row in rows
        ],
    }


@admin_router.get("/llm-stats/by-model")
async def get_llm_stats_by_model(
    days: int = Query(default=30, ge=1, le=365),
    model: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """按模型统计的柱状图数据"""
    since = _now() - timedelta(days=max(1, min(days, 365)))

    q = db.query(
        models.LlmUsageMetric.model,
        func.coalesce(func.sum(models.LlmUsageMetric.prompt_tokens), 0).label("prompt"),
        func.coalesce(func.sum(models.LlmUsageMetric.completion_tokens), 0).label("completion"),
        func.coalesce(func.sum(models.LlmUsageMetric.total_tokens), 0).label("total"),
        func.coalesce(func.sum(models.LlmUsageMetric.tokens_saved), 0).label("saved"),
        func.count(models.LlmUsageMetric.id).label("requests"),
    ).filter(models.LlmUsageMetric.created_at >= since)
    if model:
        q = q.filter(models.LlmUsageMetric.model == model)
    rows = q.group_by(models.LlmUsageMetric.model).order_by(func.sum(models.LlmUsageMetric.total_tokens).desc()).all()
    duration_q = db.query(
        models.LlmRequestAudit.model,
        func.coalesce(func.avg(models.LlmRequestAudit.request_duration_ms), 0).label("avg_request_ms"),
        func.coalesce(func.avg(models.LlmRequestAudit.upstream_duration_ms), 0).label("avg_upstream_ms"),
        func.coalesce(func.avg(models.LlmRequestAudit.platform_duration_ms), 0).label("avg_platform_ms"),
    ).filter(models.LlmRequestAudit.created_at >= since)
    if model:
        duration_q = duration_q.filter(models.LlmRequestAudit.model == model)
    duration_rows = {row.model: row for row in duration_q.group_by(models.LlmRequestAudit.model).all()}

    return {
        "days": days,
        "models": [
            {
                "model": row.model,
                "prompt_tokens": int(row.prompt),
                "completion_tokens": int(row.completion),
                "total_tokens": int(row.total),
                "tokens_saved": int(row.saved),
                "requests": row.requests,
                "avg_request_ms": round(float(getattr(duration_rows.get(row.model), "avg_request_ms", 0) or 0), 1),
                "avg_upstream_ms": round(float(getattr(duration_rows.get(row.model), "avg_upstream_ms", 0) or 0), 1),
                "avg_platform_ms": round(float(getattr(duration_rows.get(row.model), "avg_platform_ms", 0) or 0), 1),
            }
            for row in rows
        ],
    }


@admin_router.get("/llm-stats/by-user")
async def get_llm_stats_by_user(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
    model: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """按用户统计 Token 用量，覆盖旧 LLM API Key 和统一凭证中心。"""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    users = {row.id: row.username for row in db.query(models.User).all()}
    api_key_users = {
        row.id: row.user_id
        for row in db.query(models.LlmApiKey.id, models.LlmApiKey.user_id).all()
        if row.user_id
    }
    access_token_users = {
        row.id: row.user_id
        for row in db.query(models.AccessToken.id, models.AccessToken.user_id)
        .filter(models.AccessToken.token_type.in_(["model_gateway", "agent_runtime"]))
        .all()
        if row.user_id
    }
    stats = {
        user_id: {
            "user_id": user_id,
            "username": username or f"user-{user_id}",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "tokens_saved": 0,
            "requests": 0,
        }
        for user_id, username in users.items()
    }
    q = db.query(models.LlmUsageMetric).filter(models.LlmUsageMetric.created_at >= since)
    if model:
        q = q.filter(models.LlmUsageMetric.model == model)
    for metric in q.all():
        # Unified access tokens are the current path; fall back to legacy LLM API keys.
        user_id = access_token_users.get(metric.api_key_id) or api_key_users.get(metric.api_key_id)
        if not user_id:
            continue
        row = stats.setdefault(user_id, {
            "user_id": user_id,
            "username": users.get(user_id) or f"user-{user_id}",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "tokens_saved": 0,
            "requests": 0,
        })
        row["prompt_tokens"] += int(metric.prompt_tokens or 0)
        row["completion_tokens"] += int(metric.completion_tokens or 0)
        row["total_tokens"] += int(metric.total_tokens or 0)
        row["tokens_saved"] += int(metric.tokens_saved or 0)
        row["requests"] += 1
    rows = sorted(
        stats.values(),
        key=lambda item: (item["total_tokens"], item["requests"], item["username"]),
        reverse=True,
    )[:limit]

    return {
        "days": days,
        "model": model,
        "limit": limit,
        "users": rows,
    }


async def _chat_completions_impl(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None,
    db: Session,
) -> dict[str, Any]:
    key = _resolve_api_key(db, authorization, request)
    await _check_request_size(request, key)
    _acquire_key_slot(key)
    if payload.stream:
        try:
            return await _chat_completions_with_key(payload, response, key, db, request=request)
        except Exception:
            _release_key_slot(key)
            raise
    try:
        return await _chat_completions_with_key(payload, response, key, db, request=request)
    finally:
        _release_key_slot(key)


async def _chat_completions_with_key(
    payload: schemas.ChatCompletionRequest,
    response: Response,
    key: models.LlmApiKey,
    db: Session,
    request: Request | None = None,
) -> dict[str, Any]:
    request_started_at = time.perf_counter()
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    context = {}
    metadata = payload.metadata or {}
    tenant_id = str(metadata.get("tenant_id") or f"group-{key.group_id or 'default'}")
    if isinstance(key, models.AccessToken):
        tenant_id = str(key.group_id) if key.group_id is not None else ("default" if tenant_id == "group-default" else tenant_id)
    _resolve_model(db, payload.model, key)
    record_probe(db, key, payload, request_id)
    messages = [_strip_undefined_values(message.model_dump()) for message in payload.messages]
    if settings.RUNTIME_TRACE_ENABLED and not (getattr(key, "bound_agent_id", None) and metadata.get("trace_id")):
        declared = [("metadata.session_id", metadata.get("session_id")),
                    ("x-hermes-session-id", request.headers.get("x-hermes-session-id") if request else None),
                    ("conversation_id", payload.conversation_id),
                    ("metadata.conversation_id", metadata.get("conversation_id"))]
        source, explicit_id = next(((name, str(value).strip()) for name, value in declared if value and str(value).strip()), (None, None))
        try:
            context = gateway_sessions.associate(db, key=key, tenant_id=tenant_id, messages=messages,
                                                 request_id=request_id, explicit_id=explicit_id, source=source)
        except Exception as exc:
            db.rollback()
            # Trace association follows the existing best-effort tracing contract.
            logging.getLogger(__name__).warning("gateway session association failed: %s", type(exc).__name__)
            context = {}

    def record_unfinished(error):
        if context.get("gateway_trace_id") and not context.get("gateway_finished"):
            _publish_model_runtime_trace(db, key=key, trace_context=context, tenant_id=tenant_id,
                                         request_id=request_id, model_name=payload.model or "",
                                         request_payload={"messages": messages}, error=error,
                                         duration_ms=(time.perf_counter() - request_started_at) * 1000)

    try:
        result = await _execute_chat_completions_with_key(payload, response, key, db,
                                                         request_id=request_id, gateway_context=context,
                                                         request_started_at=request_started_at)
    except BaseException:
        record_unfinished("gateway.request_interrupted")
        raise
    if isinstance(result, StreamingResponse):
        original_iterator = result.body_iterator

        async def observe_stream():
            try:
                async for chunk in original_iterator:
                    yield chunk
            finally:
                try:
                    await original_iterator.aclose()
                finally:
                    record_unfinished("gateway.stream_interrupted")

        result.body_iterator = observe_stream()
    return result


async def _execute_chat_completions_with_key(
    payload: schemas.ChatCompletionRequest,
    response: Response,
    key: models.LlmApiKey,
    db: Session,
    *,
    request_id: str,
    gateway_context: dict,
    request_started_at: float,
) -> dict[str, Any]:
    model = _resolve_model(db, payload.model, key)
    policy = _resolve_policy(db, key)
    declared_skill = declared_skill_context(payload.metadata)
    manager = None
    if any(declared_skill.values()):
        from agent_manager.api.router import get_manager

        manager = get_manager()
    skill_assessment = evaluate_gateway_skill_context(
        db,
        key,
        payload.metadata,
        manager=manager,
        source="caller_metadata",
    )

    compression_enabled = bool(getattr(key, "enable_compression", False))
    compression_level = str(getattr(key, "compression_level", None) or "auto")
    metadata = {str(k): str(v) for k, v in (payload.metadata or {}).items()}
    tenant_id = metadata.get("tenant_id") or f"group-{key.group_id or 'default'}"
    user_ref = metadata.get("user_id") or (f"user-{key.user_id}" if key.user_id else f"key-{key.id}")
    conversation_id = payload.conversation_id or metadata.get("conversation_id") or f"conv-{uuid.uuid4().hex}"
    trace_context = _runtime_trace_context(metadata, conversation_id)
    trace_context.update(gateway_context)
    # Share completion state with the outer streaming/error observer.
    gateway_context.update(trace_context)
    trace_context = gateway_context
    privacy_enabled = bool(policy.enabled)
    requested_bypass = str(metadata.get("bypass_pii_check", "")).lower() in {"1", "true", "yes", "on"}
    if privacy_enabled and requested_bypass and not policy.allow_bypass:
        raise HTTPException(status_code=403, detail="当前策略不允许绕过 PII 检查")
    bypass_pii = requested_bypass or not privacy_enabled

    original_messages = [_strip_undefined_values(message.model_dump()) for message in payload.messages]
    content_sources = _message_content_sources(original_messages, payload.metadata)
    prompt_security = _scan_prompt_security(
        original_messages,
        mode=_prompt_guard_mode(key),
        llm_review=bool(getattr(key, "prompt_guard_llm_review", False)),
        sources=content_sources,
    )
    if prompt_security["blocked"]:
        _record_prompt_guard_block(
            db,
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            key=key,
            model_name=model.name,
            bypass_pii=bypass_pii,
            policy=policy,
            original_messages=original_messages,
            prompt_security=prompt_security,
            skill_assessment=skill_assessment,
            request_duration_ms=(time.perf_counter() - request_started_at) * 1000,
            trace_context=trace_context,
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-prompt-guard"] = "block"
        raise HTTPException(status_code=403, detail="Prompt 防护阻断高风险请求，请在链路追踪中查看命中规则")
    active_mappings = db.query(models.PseudonymMapping).filter(
        models.PseudonymMapping.tenant_id == tenant_id,
        models.PseudonymMapping.conversation_id == conversation_id,
        models.PseudonymMapping.expires_at >= _now(),
    ).all()
    rewritten_messages: list[dict[str, Any]] = []
    all_mappings = list(active_mappings)
    created_total = 0
    reused_total = 0
    detected_counts: dict[str, int] = {}
    entity_types = set(_normalize_entity_types(_json_loads(policy.entity_types_json, DEFAULT_ENTITY_TYPES)))
    entity_rules = _effective_entity_rules(getattr(policy, "entity_rules_json", None))
    pseudonymized_fields: dict[int, set[str]] = {}

    if bypass_pii:
        rewritten_messages = list(original_messages)
        all_mappings = []
    else:
        for idx, message in enumerate(original_messages):
            role = message.get("role")
            scan_fields: list[str] = []
            if role in {"user", "assistant", "tool"} or (role == "system" and policy.detect_system_messages):
                scan_fields.append("content")
            if isinstance(message.get("reasoning_content"), (str, list)):
                scan_fields.append("reasoning_content")
            if not scan_fields and not message.get("tool_calls"):
                rewritten_messages.append(message)
                continue
            rewritten_message = dict(message)
            pseudonymized_fields[idx] = set()
            for field in scan_fields:
                rewritten, new_mappings, created, reused, counts = _pseudonymize_content(
                    db,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    user_ref=user_ref,
                    request_id=request_id,
                    content=message.get(field),
                    entity_types=entity_types,
                    entity_rules=entity_rules,
                    ttl_days=policy.mapping_ttl_days,
                )
                rewritten_message[field] = rewritten
                pseudonymized_fields[idx].add(field)
                all_mappings.extend(new_mappings)
                created_total += created
                reused_total += reused
                for entity_type, count in counts.items():
                    detected_counts[entity_type] = detected_counts.get(entity_type, 0) + count
            if isinstance(message.get("tool_calls"), list):
                rewritten_tool_calls = []
                for tool_call in message["tool_calls"]:
                    copied_call = dict(tool_call)
                    function = dict(copied_call.get("function") or {})
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        rewritten, new_mappings, created, reused, counts = _pseudonymize_content(
                            db,
                            tenant_id=tenant_id,
                            conversation_id=conversation_id,
                            user_ref=user_ref,
                            request_id=request_id,
                            content=arguments,
                            entity_types=entity_types,
                            entity_rules=entity_rules,
                            ttl_days=policy.mapping_ttl_days,
                        )
                        function["arguments"] = rewritten
                        all_mappings.extend(new_mappings)
                        created_total += created
                        reused_total += reused
                        for entity_type, count in counts.items():
                            detected_counts[entity_type] = detected_counts.get(entity_type, 0) + count
                    copied_call["function"] = function
                    rewritten_tool_calls.append(copied_call)
                rewritten_message["tool_calls"] = rewritten_tool_calls
                pseudonymized_fields[idx].add("tool_calls")
            rewritten_messages.append(rewritten_message)

    rewritten_messages = _redact_known_values(rewritten_messages, all_mappings, skip_fields=pseudonymized_fields)
    upstream_messages = rewritten_messages if bypass_pii else [{"role": "system", "content": PLACEHOLDER_PRESERVATION_SYSTEM_PROMPT, "system": True}, *rewritten_messages]
    body = payload.model_dump(exclude={"metadata", "conversation_id"}, exclude_none=True)
    if payload.anthropic_options:
        body["anthropic_options"] = payload.anthropic_options
    body["model"] = model.name
    body["messages"] = [
        _strip_undefined_values({k: v for k, v in message.items() if k != "system"}) for message in upstream_messages
    ]
    body["stream"] = bool(payload.stream)
    if model.max_output_tokens:
        for token_field in ("max_tokens", "max_completion_tokens"):
            if token_field in body and int(body[token_field]) > model.max_output_tokens:
                raise HTTPException(status_code=400, detail=f"{token_field} 超过模型输出限制: {model.max_output_tokens}")

    # === Headroom 智能压缩（可选） ===
    compression_result = None
    if compression_enabled:
        compression_result = compress_messages(
            body["messages"],
            model=body["model"],
            level=compression_level,
        )
        body["messages"] = compression_result.messages
    # =================================

    # Pseudonym mappings are flushed while rewriting the prompt. Commit before
    # the network call so a slow or streaming model response does not hold SQLite's write lock.
    db.commit()

    if payload.stream:
        stream = await _stream_upstream(
            db,
            model,
            body,
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            key=key,
            bypass_pii=bypass_pii,
            all_mappings=all_mappings,
            detected_counts=detected_counts,
            created_total=created_total,
            reused_total=reused_total,
            policy=policy,
            original_messages=original_messages,
            upstream_messages=upstream_messages,
            compression_enabled=compression_enabled,
            compression_level=compression_level,
            compression_result=compression_result,
            prompt_security=prompt_security,
            skill_assessment=skill_assessment,
            request_started_at=request_started_at,
            trace_context=trace_context,
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "x-request-id": request_id,
                "x-tenant-id": tenant_id,
                "x-conversation-id": conversation_id,
                "x-traffic-type": "pii_bypass" if bypass_pii else "pii_checked",
                "x-privacy-policy": "enabled" if privacy_enabled else "disabled",
                "x-prompt-guard": prompt_security.get("action", "off"),
                "x-compression": (
                    "on" if compression_result and compression_result.applied
                    else ("enabled-noop" if compression_result else "off")
                ),
                **({
                    "x-compression-saved-tokens": str(compression_result.tokens_saved),
                    "x-compression-ratio": str(round(compression_result.ratio * 100, 1)),
                    "x-compression-ms": str(round(compression_result.duration_ms, 0)),
                    "x-compression-transforms": ",".join(compression_result.transforms_applied) if compression_result.transforms_applied else "no-op",
                } if compression_result else {}),
                "cache-control": "no-cache",
            },
        )

    try:
        upstream_started_at = time.perf_counter()
        upstream_response = await _call_upstream(db, model, body)
        upstream_duration_ms = (time.perf_counter() - upstream_started_at) * 1000
        request_duration_ms = (time.perf_counter() - request_started_at) * 1000
        masked_choices = []
        final_choices = []
        for choice in upstream_response.get("choices", []):
            message = choice.get("message") or {}
            masked_choice = {"index": choice.get("index", 0)}
            final_choice = {"index": choice.get("index", 0)}
            for field in MESSAGE_TEXT_FIELDS:
                if field not in message:
                    continue
                before = message.get(field)
                after = before if bypass_pii else _replace_text_content(before, all_mappings, to_token=False)
                masked_choice[field] = before or ""
                final_choice[field] = after or ""
                message[field] = after
            if message.get("tool_calls"):
                masked_tool_calls = json.loads(json.dumps(message["tool_calls"]))
                final_tool_calls = (
                    masked_tool_calls
                    if bypass_pii
                    else _replace_tool_call_arguments(masked_tool_calls, all_mappings, to_token=False)
                )
                masked_choice["tool_calls"] = masked_tool_calls
                final_choice["tool_calls"] = final_tool_calls
                message["tool_calls"] = final_tool_calls
            masked_choices.append(masked_choice)
            final_choices.append(final_choice)
            choice["message"] = message
        usage = upstream_response.get("usage") or {}
        audit = models.LlmRequestAudit(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            group_id=key.group_id,
            api_key_id=key.id,
            **_audit_identity_fields(key),
            **skill_assessment.audit_fields(),
            model=model.name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            detected_counts_json=_json_dumps(detected_counts),
            created_tokens=created_total,
            reused_tokens=reused_total,
            compression_enabled=compression_enabled,
            compression_level=compression_level if compression_enabled else None,
            request_duration_ms=round(request_duration_ms, 2),
            upstream_duration_ms=round(upstream_duration_ms, 2),
            platform_duration_ms=round(max(0.0, request_duration_ms - upstream_duration_ms), 2),
            prompt_guard_result_json=_json_dumps(prompt_security),
        )
        db.add(audit)
        db.add(
            models.LlmUsageMetric(
                request_id=request_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                group_id=key.group_id,
                api_key_id=key.id,
                model=model.name,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                pii_hits_json=_json_dumps(detected_counts),
                created_tokens=created_total,
                reused_tokens=reused_total,
                pre_compression_tokens=compression_result.pre_tokens if compression_result else 0,
                post_compression_tokens=compression_result.post_tokens if compression_result else 0,
                tokens_saved=(min(compression_result.tokens_saved, int(usage.get("prompt_tokens") or 0)) if compression_result else 0),
                compression_ratio=compression_result.ratio if compression_result else 0.0,
                compression_duration_ms=compression_result.duration_ms if compression_result else 0.0,
            )
        )
        _save_trace(
            db,
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            model=model.name,
            bypass_pii=bypass_pii,
            ttl_days=policy.mapping_ttl_days,
            stages={
                "meta": {
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "model": model.name,
                    "bypass_pii": bypass_pii,
                    **_key_owner_meta(db, key),
                    **skill_assessment.trace_fields(),
                    "created_at": int(time.time()),
                    "request_duration_ms": round(request_duration_ms, 2),
                    "upstream_duration_ms": round(upstream_duration_ms, 2),
                    "platform_duration_ms": round(max(0.0, request_duration_ms - upstream_duration_ms), 2),
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "prompt_security_risk": prompt_security.get("risk_level", "none"),
                    "prompt_security_action": prompt_security.get("action", "off"),
                },
                "prompt_security": prompt_security,
                "original": {"messages": original_messages},
                "masked": {"messages": upstream_messages},
                "compressed": {
                    "messages": body["messages"],
                    "enabled": compression_enabled,
                    "level": compression_level if compression_enabled else None,
                    "pre_tokens": compression_result.pre_tokens if compression_result else 0,
                    "post_tokens": compression_result.post_tokens if compression_result else 0,
                    "tokens_saved": compression_result.tokens_saved if compression_result else 0,
                    "ratio": compression_result.ratio if compression_result else 0,
                    "duration_ms": compression_result.duration_ms if compression_result else 0,
                },
                "masked_response": {"choices": masked_choices},
                "final_response": {"choices": final_choices},
            },
        )
        db.commit()
        _publish_model_runtime_trace(
            db,
            key=key,
            trace_context=trace_context,
            tenant_id=tenant_id,
            request_id=request_id,
            model_name=model.name,
            request_payload={"messages": original_messages},
            redacted_request={"messages": upstream_messages},
            response_payload={"choices": final_choices},
            redacted_response={"choices": masked_choices},
            usage=usage,
            prompt_security=prompt_security,
            duration_ms=request_duration_ms,
            upstream_duration_ms=upstream_duration_ms,
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-tenant-id"] = tenant_id
        response.headers["x-conversation-id"] = conversation_id
        response.headers["x-traffic-type"] = "pii_bypass" if bypass_pii else "pii_checked"
        response.headers["x-privacy-policy"] = "enabled" if privacy_enabled else "disabled"
        response.headers["x-prompt-guard"] = prompt_security.get("action", "off")
        response.headers["x-compression"] = (
            "on" if compression_result and compression_result.applied
            else ("enabled-noop" if compression_result else "off")
        )
        if compression_result:
            response.headers["x-compression-transforms"] = ",".join(compression_result.transforms_applied) if compression_result.transforms_applied else "no-op"
            if compression_result.applied:
                response.headers["x-compression-saved-tokens"] = str(compression_result.tokens_saved)
                response.headers["x-compression-ratio"] = str(round(compression_result.ratio * 100, 1))
                response.headers["x-compression-ms"] = str(round(compression_result.duration_ms, 0))
        return upstream_response
    except HTTPException as exc:
        request_duration_ms = (time.perf_counter() - request_started_at) * 1000
        upstream_duration_ms = locals().get("upstream_duration_ms")
        if upstream_duration_ms is None and "upstream_started_at" in locals():
            upstream_duration_ms = (time.perf_counter() - upstream_started_at) * 1000
        upstream_duration_ms = float(upstream_duration_ms or 0.0)
        db.add(
            models.LlmRequestAudit(
                request_id=request_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                user_ref=user_ref,
                group_id=key.group_id,
                api_key_id=key.id,
                **_audit_identity_fields(key),
                **skill_assessment.audit_fields(),
                model=model.name,
                traffic_type="pii_bypass" if bypass_pii else "pii_checked",
                status="error",
                error=str(exc.detail),
                compression_enabled=compression_enabled,
                compression_level=compression_level if compression_enabled else None,
                request_duration_ms=round(request_duration_ms, 2),
                upstream_duration_ms=round(upstream_duration_ms, 2),
                platform_duration_ms=round(max(0.0, request_duration_ms - upstream_duration_ms), 2),
            )
        )
        db.commit()
        _publish_model_runtime_trace(
            db,
            key=key,
            trace_context=trace_context,
            tenant_id=tenant_id,
            request_id=request_id,
            model_name=model.name,
            error=str(exc.detail),
            duration_ms=request_duration_ms,
            upstream_duration_ms=upstream_duration_ms,
        )
        # 即使上游失败也输出压缩诊断头
        response.headers["x-compression"] = (
            "on" if compression_result and compression_result.applied
            else ("enabled-noop" if compression_result else "off")
        )
        if compression_result:
            response.headers["x-compression-transforms"] = ",".join(compression_result.transforms_applied) if compression_result.transforms_applied else "no-op"
            if compression_result.applied:
                response.headers["x-compression-saved-tokens"] = str(compression_result.tokens_saved)
                response.headers["x-compression-ratio"] = str(round(compression_result.ratio * 100, 1))
        raise


def _models_payload_for_key(db: Session, key: models.LlmApiKey) -> dict[str, Any]:
    allowed_models = _json_loads(key.allowed_models_json, [])
    if isinstance(key, models.AccessToken) and key.token_type == "agent_runtime" and not allowed_models and key.bound_agent_id:
        agent = db.query(models.ManagedAgent).filter_by(agent_id=key.bound_agent_id).first()
        if agent and agent.default_model:
            allowed_models = [agent.default_model]
    query = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(
        models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True))
    if allowed_models:
        query = query.filter(models.ModelEndpoint.name.in_(allowed_models))
    rows = query.order_by(models.ModelEndpoint.name.asc()).all()
    return {
        "object": "list",
        "data": [
            {
                "id": row.name,
                "object": "model",
                "created": int((row.created_at or _now()).timestamp()),
                "owned_by": "agent-manager",
                "provider_id": row.provider_id,
                "provider_name": db.get(models.ModelProvider, row.provider_id).name,
                "upstream_name": row.upstream_name or row.name,
            }
            for row in rows
        ],
    }


def _anthropic_error(exc: HTTPException) -> JSONResponse:
    status = 401 if isinstance(exc, ApiError) and exc.code in {"credential.invalid_or_disabled", "credential.expired"} else exc.status_code
    kind = {401: "authentication_error", 403: "permission_error", 404: "not_found_error",
            413: "request_too_large", 429: "rate_limit_error"}.get(status, "api_error" if status >= 500 else "invalid_request_error")
    message = exc.en_message if isinstance(exc, ApiError) else str(exc.detail)
    return JSONResponse(status_code=status, headers=exc.headers,
                        content={"type": "error", "error": {"type": kind, "message": message,
                                 "code": exc.code if isinstance(exc, ApiError) else f"http.{status}"}})


def _anthropic_model(db: Session, item: dict[str, Any]) -> dict[str, Any]:
    row = db.query(models.ModelEndpoint).filter_by(name=item["id"]).one()
    return {"id": row.name, "type": "model", "display_name": row.display_name or row.upstream_name or row.name,
            "created_at": datetime.utcfromtimestamp(item["created"]).isoformat() + "Z",
            "max_input_tokens": row.context_window, "max_tokens": row.max_output_tokens}


def _runtime_model_catalog(request: Request, db: Session, model_id: str | None = None):
    anthropic = bool(request.headers.get("anthropic-version") or request.headers.get("x-api-key"))
    credential = request.headers.get("authorization") or (f"Bearer {request.headers['x-api-key']}" if request.headers.get("x-api-key") else None)
    try:
        key = _resolve_api_key(db, credential, request=request)
        catalog = _models_payload_for_key(db, key)
        items = catalog["data"]
        if model_id is not None:
            item = next((item for item in items if item["id"] == model_id), None)
            if item is None:
                raise ApiError(404, "model.unavailable", "模型不存在或不可用", "Model not found or unavailable")
            return _anthropic_model(db, item) if anthropic else item
        if not anthropic:
            return catalog
        params = request.query_params
        try:
            limit = int(params.get("limit", "20"))
        except ValueError:
            raise ApiError(400, "model_catalog.invalid_limit", "分页数量必须为整数", "limit must be an integer") from None
        if not 1 <= limit <= 1000 or (params.get("before_id") and params.get("after_id")):
            raise ApiError(400, "model_catalog.invalid_pagination", "分页数量须为 1–1000，且只能使用一个游标", "Use limit 1..1000 and only one pagination cursor")
        before, after = params.get("before_id"), params.get("after_id")
        ids = [item["id"] for item in items]
        if (before or after) and (before or after) not in ids:
            raise ApiError(400, "model_catalog.invalid_cursor", "模型分页游标无效", "Unknown model pagination cursor")
        if after:
            items = items[ids.index(after) + 1:]
        if before:
            items = items[:ids.index(before)]
        has_more = len(items) > limit
        page = items[-limit:] if before else items[:limit]
        return {"data": [_anthropic_model(db, item) for item in page], "has_more": has_more,
                "first_id": page[0]["id"] if page else None, "last_id": page[-1]["id"] if page else None}
    except HTTPException as exc:
        if anthropic:
            return _anthropic_error(exc)
        raise


@runtime_router.post("/v1/messages/count_tokens", summary="Anthropic-compatible local token estimate")
async def anthropic_count_tokens(request: Request, response: Response, db: Session = Depends(get_db)):
    credential = request.headers.get("authorization") or (f"Bearer {request.headers['x-api-key']}" if request.headers.get("x-api-key") else None)
    try:
        key = _resolve_api_key(db, credential, request=request)
        await _check_request_size(request, key)
        try:
            payload = await request.json()
            # Counting requests omit generation limits.
            parsed = schemas.AnthropicMessagesRequest.model_validate({**payload, "max_tokens": 1})
        except (ValueError, TypeError):
            raise ApiError(400, "token_count.invalid_request", "Token 计数请求格式无效", "Invalid token counting request") from None
        _resolve_model(db, parsed.model, key)
        content = {field: payload[field] for field in ("system", "messages", "tools", "tool_choice", "thinking") if field in payload}
        count = max(1, math.ceil(len(json.dumps(content, ensure_ascii=False).encode("utf-8")) / 3))
        response.headers["x-token-count-method"] = "estimated-utf8"
        return {"input_tokens": count}
    except HTTPException as exc:
        return _anthropic_error(exc)


@runtime_router.post(
    "/v1/messages",
    summary="Anthropic-compatible Messages endpoint for Claude Code",
)
async def anthropic_messages_compat(
    payload: schemas.AnthropicMessagesRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    credential = authorization or (f"Bearer {x_api_key}" if x_api_key else None)
    converted = schemas.ChatCompletionRequest.model_validate(
        anthropic_to_openai_request(payload.model_dump(exclude_none=True))
    )
    try:
        result = await _chat_completions_impl(converted, request, response, credential, db)
    except HTTPException as exc:
        return _anthropic_error(exc)
    if isinstance(result, StreamingResponse):
        headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower() not in {"content-type", "content-length"}
        }
        return StreamingResponse(
            openai_stream_to_anthropic(result.body_iterator, payload.model),
            media_type="text/event-stream",
            headers=headers,
        )
    return openai_to_anthropic_response(result)


@runtime_router.post("/v1/responses", summary="OpenAI-compatible Responses endpoint for Codex")
async def responses_compat(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    try:
        converted = schemas.ChatCompletionRequest.model_validate(responses_to_openai_request(payload))
    except (ValueError, ValidationError) as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc), "type": "invalid_request_error", "code": "responses.invalid_request"}})
    tool_kinds = response_tool_kinds(payload)
    try:
        result = await _chat_completions_impl(converted, request, response, authorization, db)
    except HTTPException as exc:
        error_type = {
            401: "authentication_error",
            403: "permission_error",
            404: "not_found_error",
            409: "conflict_error",
            429: "rate_limit_error",
        }.get(exc.status_code, "api_error" if exc.status_code >= 500 else "invalid_request_error")
        if isinstance(exc, ApiError):
            message = exc.en_message if request_locale(request) == "en-US" else exc.zh_message
            error_code = exc.code
            if error_code in {"credential.invalid_or_disabled", "credential.expired"}:
                error_type = "authentication_error"
        else:
            message = str(exc.detail)
            error_code = f"http.{exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"error": {"message": message, "type": error_type, "code": error_code}},
        )
    if isinstance(result, StreamingResponse):
        headers = {key: value for key, value in result.headers.items() if key.lower() not in {"content-type", "content-length"}}
        return StreamingResponse(openai_stream_to_responses(result.body_iterator, payload.get("model"), tool_kinds), media_type="text/event-stream", headers=headers)
    return openai_to_responses_response(result, tool_kinds)


@runtime_router.post("/client-models/{model_id}/v1/messages", summary="Claude Desktop gateway model route")
async def claude_desktop_messages(
    model_id: str, payload: schemas.AnthropicMessagesRequest, request: Request, response: Response,
    authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    try:
        model = bytes.fromhex(model_id).decode("utf-8")
        if not model or len(model) > 128 or payload.model != "claude-sonnet-5":
            raise ValueError("invalid route")
    except (ValueError, UnicodeError) as exc:
        raise ApiError(400, "client.desktop_model_route_invalid", "桌面模型路由无效", "Invalid desktop model route") from exc
    # Routing changes only the model alias. Credential, model permission,
    # privacy, Prompt Guard, rate limits and auditing use the ordinary pipeline.
    return await anthropic_messages_compat(payload.model_copy(update={"model": model}), request, response, authorization, x_api_key, db)


@runtime_router.post("/client-models/{model_id}/v1beta/models/{model_action:path}")
async def client_gemini_generate_content(
    model_id: str, model_action: str, payload: dict[str, Any], request: Request, response: Response,
    authorization: str | None = Header(default=None), x_goog_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    try:
        model = bytes.fromhex(model_id).decode("utf-8")
        if not model or len(model) > 128:
            raise ValueError("invalid route")
    except (ValueError, UnicodeError) as exc:
        raise ApiError(400, "client.model_route_invalid", "模型路由无效", "Invalid model route") from exc
    _, separator, action = model_action.rpartition(":")
    if not separator:
        raise ApiError(400, "gemini.operation_unsupported", "不支持此 Gemini 操作", "Unsupported Gemini operation")
    return await gemini_generate_content(model + ":" + action, payload, request, response, authorization, x_goog_api_key, db)


@runtime_router.post("/v1beta/models/{model_action:path}", summary="Gemini-compatible governed generation")
async def gemini_generate_content(
    model_action: str, payload: dict[str, Any], request: Request, response: Response,
    authorization: str | None = Header(default=None), x_goog_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    model, separator, action = model_action.rpartition(":")
    if not separator or not model or action not in {"generateContent", "streamGenerateContent"}:
        raise ApiError(400, "gemini.operation_unsupported", "不支持此 Gemini 操作", "Unsupported Gemini operation")
    try:
        converted = schemas.ChatCompletionRequest.model_validate(gemini_to_chat(payload, model, action == "streamGenerateContent"))
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise ApiError(400, "gemini.invalid_request", "Gemini 请求参数无效或不受支持", "Invalid or unsupported Gemini request") from exc
    credential = authorization or (f"Bearer {x_goog_api_key}" if x_goog_api_key else None)
    result = await _chat_completions_impl(converted, request, response, credential, db)
    if isinstance(result, StreamingResponse):
        headers = {key: value for key, value in result.headers.items() if key.lower() not in {"content-type", "content-length"}}
        return StreamingResponse(chat_stream_to_gemini(result.body_iterator, model), media_type="text/event-stream", headers=headers)
    return chat_to_gemini(result)


@runtime_router.post(
    "/v1/chat/completions",
    summary="OpenAI-compatible chat completions endpoint for SDK base_url compatibility",
)
async def chat_completions_compat(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return await _chat_completions_impl(payload, request, response, authorization, db)


@runtime_router.post(
    "/",
    summary="Chat completions compatibility endpoint for clients that treat base_url as the full endpoint",
)
async def chat_completions_index_compat(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return await _chat_completions_impl(payload, request, response, authorization, db)


@runtime_router.post(
    "/chat/completions",
    summary="OpenAI-compatible chat completions endpoint for clients whose base_url omits /v1",
)
async def chat_completions_root_compat(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return await _chat_completions_impl(payload, request, response, authorization, db)


@runtime_router.post(
    "/api/v1/llm/chat/completions",
    summary="Agent Manager namespaced chat completions endpoint",
)
async def chat_completions_api(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return await _chat_completions_impl(payload, request, response, authorization, db)


@runtime_router.get(
    "/v1/models",
    summary="OpenAI-compatible model list endpoint",
)
async def list_models_compat(
    request: Request,
    db: Session = Depends(get_db),
):
    return _runtime_model_catalog(request, db)


@runtime_router.get(
    "/models",
    summary="OpenAI-compatible model list endpoint for clients whose base_url omits /v1",
)
async def list_models_root_compat(
    request: Request,
    db: Session = Depends(get_db),
):
    return _runtime_model_catalog(request, db)


@runtime_router.get("/v1/models/{model_id:path}", summary="Retrieve an authorized gateway model")
async def retrieve_model_compat(model_id: str, request: Request, db: Session = Depends(get_db)):
    return _runtime_model_catalog(request, db, model_id)
