import hashlib
import json
import math
import random
import re
import secrets
import time
import uuid
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..config import settings
from ..sqlite_db import get_db


admin_router = APIRouter(prefix="/v1", tags=["llm-gateway-admin"])
runtime_router = APIRouter(tags=["llm-gateway"])

DEFAULT_ENTITY_TYPES = [
    "PERSON",
    "CN_PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "CREDIT_CARD",
    "US_SSN",
    "ID_CARD",
    "EMPLOYEE_ID",
    "CUSTOMER_ID",
    "ACCOUNT_ID",
]
DEFAULT_ENTITY_PATTERNS = {
    "PERSON": r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b",
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE_NUMBER": r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)",
    "CREDIT_CARD": r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)",
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "ID_CARD": r"\b\d{15}(?:\d{2}[\dXx])?\b",
    "EMPLOYEE_ID": r"\b(?:EMP|Employee|员工)[-_:# ]?[A-Za-z0-9]{4,}\b",
    "CUSTOMER_ID": r"\b(?:CUST|Customer|客户)[-_:# ]?[A-Za-z0-9]{4,}\b",
    "ACCOUNT_ID": r"\b(?:ACCT|Account|账号)[-_:# ]?[A-Za-z0-9]{4,}\b",
}
DEFAULT_ENTITY_RULES = {name: DEFAULT_ENTITY_PATTERNS.get(name, "") for name in DEFAULT_ENTITY_TYPES}
PLACEHOLDER_PRESERVATION_SYSTEM_PROMPT = (
    "Each token like <PERSON:p_abc> or <PHONE_NUMBER:ph_xyz> is encoded private data. "
    "Treat these tokens as the real values and preserve them naturally in the answer. "
    "Do not explain that they are placeholders."
)
TRACE_STAGES = ["meta", "original", "masked", "masked_response", "final_response"]
ACTIVE_KEY_REQUESTS: dict[int, int] = {}
MESSAGE_TEXT_FIELDS = ("content", "reasoning_content")
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


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


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
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


def _api_key_query_for_user(db: Session, current_user: models.User):
    return db.query(models.LlmApiKey).filter(models.LlmApiKey.user_id == current_user.id)


def _key_owner_meta(db: Session, key: models.LlmApiKey) -> dict[str, Any]:
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
    return {
        "api_key_id": key.id,
        "api_key_prefix": key.key_prefix,
        "api_key_name": key.name,
        "api_key_user_id": key.user_id,
        "api_key_username": user.username if user else None,
        "api_key_group_id": key.group_id,
        "api_key_group_ids": [group.id for group in groups],
        "api_key_group_names": [group.name for group in groups],
    }


def _policy_response(row: models.PrivacyPolicy) -> schemas.PrivacyPolicyResponse:
    return schemas.PrivacyPolicyResponse(
        id=row.id,
        name=row.name,
        group_id=row.group_id,
        entity_types=_json_loads(row.entity_types_json, DEFAULT_ENTITY_TYPES),
        entity_rules={**DEFAULT_ENTITY_RULES, **_json_loads(getattr(row, "entity_rules_json", None), {})},
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


def _sync_group_members(db: Session, group_id: int, user_ids: list[int]) -> None:
    db.query(models.UserGroupMember).filter(models.UserGroupMember.group_id == group_id).delete()
    for user_id in sorted(set(user_ids)):
        if db.query(models.User).filter(models.User.id == user_id).first():
            db.add(models.UserGroupMember(user_id=user_id, group_id=group_id))


def _bind_group_policy(db: Session, group_id: int, policy_id: int | None) -> None:
    db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == group_id).update({"group_id": None})
    if policy_id is None:
        return
    policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="隐私策略不存在")
    if policy.group_id is not None and policy.group_id != group_id:
        raise HTTPException(status_code=400, detail="隐私策略已绑定其他用户组")
    policy.group_id = group_id


def _get_default_policy(db: Session) -> models.PrivacyPolicy:
    policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id.is_(None)).first()
    if policy:
        return policy
    policy = models.PrivacyPolicy(
        name="默认隐私策略",
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


def _resolve_policy(db: Session, key: models.LlmApiKey) -> models.PrivacyPolicy:
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
    for group_id in candidate_group_ids:
        policy = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == group_id).first()
        if policy:
            return policy
    return _get_default_policy(db)


def _resolve_api_key(db: Session, authorization: str | None) -> models.LlmApiKey:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 LLM API Key")
    raw = authorization[len("Bearer "):].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="缺少 LLM API Key")
    key_hash = _hash_token(raw)
    key = db.query(models.LlmApiKey).filter(models.LlmApiKey.key_hash == key_hash).first()
    if not key or key.status != "active":
        raise HTTPException(status_code=401, detail="LLM API Key 无效或已禁用")
    if key.expires_at and key.expires_at < _now():
        raise HTTPException(status_code=401, detail="LLM API Key 已过期")
    key.last_used_at = _now()
    return key


async def _check_request_size(request: Request, key: models.LlmApiKey) -> None:
    raw_body = await request.body()
    max_bytes = max(1, key.max_body_kb) * 1024
    if len(raw_body) > max_bytes:
        raise HTTPException(status_code=413, detail=f"请求体超过 API Key 限制: {key.max_body_kb} KB")


def _acquire_key_slot(key: models.LlmApiKey) -> None:
    active = ACTIVE_KEY_REQUESTS.get(key.id, 0)
    if active >= max(1, key.max_concurrent_requests):
        raise HTTPException(status_code=429, detail="API Key 并发请求数已达上限")
    ACTIVE_KEY_REQUESTS[key.id] = active + 1


def _release_key_slot(key: models.LlmApiKey) -> None:
    active = ACTIVE_KEY_REQUESTS.get(key.id, 0)
    if active <= 1:
        ACTIVE_KEY_REQUESTS.pop(key.id, None)
    else:
        ACTIVE_KEY_REQUESTS[key.id] = active - 1


def _resolve_model(db: Session, requested_model: str | None, key: models.LlmApiKey) -> models.ModelEndpoint:
    allowed_models = _json_loads(key.allowed_models_json, [])
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
    if entity_type in {"PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "ID_CARD"}:
        return re.sub(r"\D+", "", value)
    return re.sub(r"\s+", " ", value).lower()


def _detect_entities(text: str, allowed_types: set[str], entity_rules: dict[str, str] | None = None) -> list[dict[str, Any]]:
    patterns = {**DEFAULT_ENTITY_PATTERNS, **{k: v for k, v in (entity_rules or {}).items() if v}}
    entities: list[dict[str, Any]] = []
    for entity_type, pattern in patterns.items():
        if entity_type not in allowed_types:
            continue
        try:
            matches = re.finditer(pattern, text)
        except re.error:
            continue
        for match in matches:
            entities.append({"entity_type": entity_type, "start": match.start(), "end": match.end(), "score": 0.85})
    if "CN_PERSON" in allowed_types:
        cn_name_core = rf"[{COMMON_CN_SURNAMES}][\u4e00-\u9fff]{{1,2}}"
        context_pattern = rf"(?:我叫|叫我|姓名(?:是|为)?|名字(?:是|叫)?|用户叫|候选人(?:叫|姓名)?|联系人(?:是|为)?|客户(?:叫|姓名)?|孩子(?:叫|名叫|姓名(?:是|为)?)|小孩(?:叫|名叫|姓名(?:是|为)?))[：:\\s]*({cn_name_core})"
        for match in re.finditer(context_pattern, text):
            entities.append(
                {
                    "entity_type": "CN_PERSON",
                    "start": match.start(1),
                    "end": match.end(1),
                    "score": 0.9,
                }
            )
        cn_name_pattern = rf"(?<![\u4e00-\u9fff])(?:[{COMMON_CN_SURNAMES}])[\u4e00-\u9fff]{{1,2}}(?![\u4e00-\u9fff])"
        for match in re.finditer(cn_name_pattern, text):
            entities.append({"entity_type": "CN_PERSON", "start": match.start(), "end": match.end(), "score": 0.5})
        suffix_pattern = rf"(?<![\u4e00-\u9fff])({cn_name_core})(?=这个|这人|此人|怎么样|如何|吗|呢|，|。|、|；|：|,|;|:|\s|$)"
        for match in re.finditer(suffix_pattern, text):
            entities.append(
                {
                    "entity_type": "CN_PERSON",
                    "start": match.start(1),
                    "end": match.end(1),
                    "score": 0.65,
                }
            )
    entities.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), -item["score"]))
    accepted: list[dict[str, Any]] = []
    for candidate in entities:
        if any(not (candidate["end"] <= item["start"] or candidate["start"] >= item["end"]) for item in accepted):
            continue
        accepted.append(candidate)
    return accepted


def _token_for(tenant_id: str, conversation_id: str, entity_type: str, normalized_value: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{conversation_id}:{entity_type}:{normalized_value}".encode("utf-8")).hexdigest()
    prefix = {
        "PERSON": "p",
        "CN_PERSON": "cnp",
        "PHONE_NUMBER": "ph",
        "EMAIL_ADDRESS": "em",
        "CREDIT_CARD": "cc",
        "US_SSN": "ssn",
        "ID_CARD": "id",
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
    if base.endswith("/v1/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


async def _call_upstream(db: Session, model: models.ModelEndpoint, payload: dict[str, Any]) -> dict[str, Any]:
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == model.provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="模型供应商不存在")
    headers = {"content-type": "application/json"}
    api_key = _unprotect_secret(provider.api_key)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        response = await client.post(_chat_url(provider.base_url), json=payload, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"上游模型接口失败: {response.status_code} {response.text[:500]}")
    return response.json()


def _stream_choices_snapshot(parts_by_index: dict[int, dict[str, list[str]]]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for index, fields in sorted(parts_by_index.items()):
        choice: dict[str, Any] = {"index": index}
        for field, parts in fields.items():
            choice[field] = "".join(parts)
        choices.append(choice)
    return choices


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
):
    provider = db.query(models.ModelProvider).filter(models.ModelProvider.id == model.provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="模型供应商不存在")
    headers = {"content-type": "application/json"}
    api_key = _unprotect_secret(provider.api_key)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    masked_parts: dict[int, dict[str, list[str]]] = {}
    final_parts: dict[int, dict[str, list[str]]] = {}
    pending_parts: dict[tuple[int, str], str] = {}
    usage: dict[str, Any] = {}
    mapping_tokens = [mapping.token for mapping in all_mappings if mapping.token]

    async def event_generator():
        nonlocal usage
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    _chat_url(provider.base_url),
                    json=payload,
                    headers=headers,
                    timeout=provider.timeout_seconds,
                ) as upstream:
                    if upstream.status_code >= 400:
                        error_body = await upstream.aread()
                        raise HTTPException(
                            status_code=502,
                            detail=f"上游模型接口失败: {upstream.status_code} {error_body[:500].decode('utf-8', errors='replace')}",
                        )
                    async for line in upstream.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            yield f"{line}\n\n"
                            continue
                        data = line[5:].strip()
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
                                masked_choices=_stream_choices_snapshot(masked_parts),
                                final_choices=_stream_choices_snapshot(final_parts),
                            )
                            yield "data: [DONE]\n\n"
                            return
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            yield f"data: {data}\n\n"
                            continue
                        if isinstance(chunk.get("usage"), dict):
                            usage = chunk["usage"]
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
                masked_choices=_stream_choices_snapshot(masked_parts),
                final_choices=_stream_choices_snapshot(final_parts),
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
            model=model_name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            detected_counts_json=_json_dumps(detected_counts),
            created_tokens=created_total,
            reused_tokens=reused_total,
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
                "created_at": int(time.time()),
            },
            "original": {"messages": original_messages},
            "masked": {"messages": upstream_messages},
            "masked_response": {"choices": masked_choices},
            "final_response": {"choices": final_choices},
        },
    )
    db.commit()


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
) -> None:
    db.add(
        models.LlmRequestAudit(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_ref=user_ref,
            group_id=key.group_id,
            api_key_id=key.id,
            model=model_name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            status="error",
            error=error,
        )
    )
    db.commit()


@admin_router.get("/users", response_model=list[schemas.User])
async def list_users(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return db.query(models.User).order_by(models.User.id.asc()).all()


@admin_router.post("/users", response_model=schemas.User)
async def create_managed_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = models.User(
        username=body.username,
        email=body.email,
        hashed_password=auth.get_password_hash(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@admin_router.put("/users/{user_id}", response_model=schemas.User)
async def update_managed_user(
    user_id: int,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = body.model_dump(exclude_unset=True)
    if data.get("password"):
        user.hashed_password = auth.get_password_hash(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


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


@admin_router.post("/model-providers/{provider_id}/test")
async def test_model_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.ModelProvider).filter(models.ModelProvider.id == provider_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    headers = {"content-type": "application/json"}
    api_key = _unprotect_secret(row.api_key)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=min(row.timeout_seconds, 15)) as client:
            response = await client.get(row.base_url.rstrip("/"), headers=headers)
        return {"ok": response.status_code < 500, "status_code": response.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@admin_router.get("/models", response_model=list[schemas.ModelEndpointResponse])
async def list_models(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return [_model_response(db, row) for row in db.query(models.ModelEndpoint).order_by(models.ModelEndpoint.id.asc()).all()]


@admin_router.post("/models", response_model=schemas.ModelEndpointResponse)
async def create_model(
    body: schemas.ModelEndpointCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if not db.query(models.ModelProvider).filter(models.ModelProvider.id == body.provider_id).first():
        raise HTTPException(status_code=404, detail="模型供应商不存在")
    if db.query(models.ModelEndpoint).filter(models.ModelEndpoint.name == body.name).first():
        raise HTTPException(status_code=400, detail="模型名称已存在")
    if body.is_default:
        db.query(models.ModelEndpoint).update({"is_default": False})
    row = models.ModelEndpoint(**body.model_dump())
    db.add(row)
    db.commit()
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
    if data.get("is_default"):
        db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id != model_id).update({"is_default": False})
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_at = _now()
    db.commit()
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
    token = _new_api_key()
    row = models.LlmApiKey(
        name=body.name,
        key_hash=_hash_token(token),
        key_prefix=token[:8],
        user_id=current_user.id,
        group_id=None,
        allowed_models_json=_json_dumps(body.allowed_models),
        expires_at=body.expires_at,
        max_body_kb=body.max_body_kb,
        max_concurrent_requests=body.max_concurrent_requests,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _api_key_response(row, token=token)


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
    _get_default_policy(db)
    return [_policy_response(row) for row in db.query(models.PrivacyPolicy).order_by(models.PrivacyPolicy.id.asc()).all()]


@admin_router.post("/privacy-policies", response_model=schemas.PrivacyPolicyResponse)
async def upsert_privacy_policy(
    body: schemas.PrivacyPolicyPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if body.group_id and not db.query(models.UserGroup).filter(models.UserGroup.id == body.group_id).first():
        raise HTTPException(status_code=404, detail="用户组不存在")
    row = db.query(models.PrivacyPolicy).filter(models.PrivacyPolicy.group_id == body.group_id).first()
    if not row:
        row = models.PrivacyPolicy(group_id=body.group_id, entity_types_json="[]", name=body.name)
        db.add(row)
    data = body.model_dump()
    entity_types = data.pop("entity_types") or DEFAULT_ENTITY_TYPES
    entity_rules = {k: v for k, v in (data.pop("entity_rules") or {}).items() if v}
    for field, value in data.items():
        setattr(row, field, value)
    row.entity_types_json = _json_dumps(entity_types)
    row.entity_rules_json = _json_dumps({**DEFAULT_ENTITY_RULES, **entity_rules})
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _policy_response(row)


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
    traces = []
    for row in rows:
        payload = _json_loads(row.payload_json, {})
        traces.append(
            {
                **payload,
                "request_id": row.request_id,
                "tenant_id": row.tenant_id,
                "conversation_id": row.conversation_id,
                "model": row.model,
                "bypass_pii": row.bypass_pii,
                "created_at": row.created_at.isoformat(),
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
    return {"request_id": request_id, "stages": stages}


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
    for row in metrics:
        for entity_type, count in _json_loads(row.pii_hits_json, {}).items():
            pii_hits[entity_type] = pii_hits.get(entity_type, 0) + int(count or 0)
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
        "pii_hits": {entity_type: protected(count) for entity_type, count in pii_hits.items()},
        "dp_enabled": policy.dp_enabled,
        "dp_min_count": policy.dp_min_count,
    }


async def _chat_completions_impl(
    payload: schemas.ChatCompletionRequest,
    request: Request,
    response: Response,
    authorization: str | None,
    db: Session,
) -> dict[str, Any]:
    key = _resolve_api_key(db, authorization)
    await _check_request_size(request, key)
    _acquire_key_slot(key)
    if payload.stream:
        try:
            return await _chat_completions_with_key(payload, response, key, db)
        except Exception:
            _release_key_slot(key)
            raise
    try:
        return await _chat_completions_with_key(payload, response, key, db)
    finally:
        _release_key_slot(key)


async def _chat_completions_with_key(
    payload: schemas.ChatCompletionRequest,
    response: Response,
    key: models.LlmApiKey,
    db: Session,
) -> dict[str, Any]:
    model = _resolve_model(db, payload.model, key)
    policy = _resolve_policy(db, key)
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    metadata = {str(k): str(v) for k, v in (payload.metadata or {}).items()}
    tenant_id = metadata.get("tenant_id") or f"group-{key.group_id or 'default'}"
    user_ref = metadata.get("user_id") or (f"user-{key.user_id}" if key.user_id else f"key-{key.id}")
    conversation_id = payload.conversation_id or metadata.get("conversation_id") or f"conv-{uuid.uuid4().hex}"
    bypass_pii = str(metadata.get("bypass_pii_check", "")).lower() in {"1", "true", "yes", "on"}
    if bypass_pii and not policy.allow_bypass:
        raise HTTPException(status_code=403, detail="当前策略不允许绕过 PII 检查")

    original_messages = [_strip_undefined_values(message.model_dump()) for message in payload.messages]
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
    entity_types = set(_json_loads(policy.entity_types_json, DEFAULT_ENTITY_TYPES))
    entity_rules = {**DEFAULT_ENTITY_RULES, **_json_loads(getattr(policy, "entity_rules_json", None), {})}
    pseudonymized_fields: dict[int, set[str]] = {}

    if bypass_pii:
        rewritten_messages = list(original_messages)
        all_mappings = []
    else:
        for idx, message in enumerate(original_messages):
            role = message.get("role")
            scan_fields: list[str] = []
            if role == "user" or (role == "system" and policy.detect_system_messages):
                scan_fields.append("content")
            if isinstance(message.get("reasoning_content"), (str, list)):
                scan_fields.append("reasoning_content")
            if not scan_fields:
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
            rewritten_messages.append(rewritten_message)

    rewritten_messages = _redact_known_values(rewritten_messages, all_mappings, skip_fields=pseudonymized_fields)
    upstream_messages = [{"role": "system", "content": PLACEHOLDER_PRESERVATION_SYSTEM_PROMPT, "system": True}, *rewritten_messages]
    body = payload.model_dump(exclude={"metadata", "conversation_id"}, exclude_none=True)
    body["model"] = model.name
    body["messages"] = [
        _strip_undefined_values({k: v for k, v in message.items() if k != "system"}) for message in upstream_messages
    ]
    body["stream"] = bool(payload.stream)
    if model.max_output_tokens:
        for token_field in ("max_tokens", "max_completion_tokens"):
            if token_field in body and int(body[token_field]) > model.max_output_tokens:
                raise HTTPException(status_code=400, detail=f"{token_field} 超过模型输出限制: {model.max_output_tokens}")

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
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "x-request-id": request_id,
                "x-tenant-id": tenant_id,
                "x-conversation-id": conversation_id,
                "x-traffic-type": "pii_bypass" if bypass_pii else "pii_checked",
                "cache-control": "no-cache",
            },
        )

    try:
        upstream_response = await _call_upstream(db, model, body)
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
            model=model.name,
            traffic_type="pii_bypass" if bypass_pii else "pii_checked",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            detected_counts_json=_json_dumps(detected_counts),
            created_tokens=created_total,
            reused_tokens=reused_total,
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
                    "created_at": int(time.time()),
                },
                "original": {"messages": original_messages},
                "masked": {"messages": upstream_messages},
                "masked_response": {"choices": masked_choices},
                "final_response": {"choices": final_choices},
            },
        )
        db.commit()
        response.headers["x-request-id"] = request_id
        response.headers["x-tenant-id"] = tenant_id
        response.headers["x-conversation-id"] = conversation_id
        response.headers["x-traffic-type"] = "pii_bypass" if bypass_pii else "pii_checked"
        return upstream_response
    except HTTPException as exc:
        db.add(
            models.LlmRequestAudit(
                request_id=request_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                user_ref=user_ref,
                group_id=key.group_id,
                api_key_id=key.id,
                model=model.name,
                traffic_type="pii_bypass" if bypass_pii else "pii_checked",
                status="error",
                error=str(exc.detail),
            )
        )
        db.commit()
        raise


def _models_payload_for_key(db: Session, key: models.LlmApiKey) -> dict[str, Any]:
    allowed_models = _json_loads(key.allowed_models_json, [])
    query = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.enabled.is_(True))
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
            }
            for row in rows
        ],
    }


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
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    key = _resolve_api_key(db, authorization)
    return _models_payload_for_key(db, key)


@runtime_router.get(
    "/models",
    summary="OpenAI-compatible model list endpoint for clients whose base_url omits /v1",
)
async def list_models_root_compat(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    key = _resolve_api_key(db, authorization)
    return _models_payload_for_key(db, key)
