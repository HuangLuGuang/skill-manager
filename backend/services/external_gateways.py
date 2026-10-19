"""Resolve the current gateway while retaining frozen delivery endpoint versions."""
import json
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit

from ..api_errors import ApiError
from ..external_access_models import ExternalGatewayConfig, ExternalDeliveryEndpoint
from ..models import ExternalAIGateway


def validate_path(value):
    parsed = urlsplit(value)
    decoded = unquote(value)
    if (not value.startswith("/") or value.startswith("//") or parsed.scheme or parsed.netloc
            or parsed.query or parsed.fragment or "?" in value or "#" in value
            or "\\" in decoded or any(c.isspace() or ord(c) < 32 for c in decoded)
            or any(part in {".", ".."} for part in decoded.split("/"))):
        raise ValueError("Use an absolute API path without a host, query, fragment or traversal")
    return value


def receiver_url(gateway, path):
    url = gateway.management_base_url.rstrip("/") + quote(validate_path(path), safe="/%:@!$&'()*+,;=-._~")
    if len(url) > 2048:
        raise ApiError(422, "external_gateways.path_invalid", "结果同步完整地址最多2048字符", "The complete result URL must not exceed 2048 characters")
    return url


def require_path(endpoint):
    if not endpoint.gateway_path:
        raise ApiError(409, "external_gateways.path_required", "请配置结果同步接口路径", "Configure the result synchronization API path")


def linked_gateway(db, gateway_id):
    if gateway_id is None:
        raise ApiError(409, "external_gateways.binding_required", "请先为结果同步配置选择外部 AI 网关", "Select an external AI gateway for this result synchronization configuration")
    gateway = db.get(ExternalAIGateway, gateway_id)
    if gateway is None or not gateway.enabled:
        raise ApiError(422, "external_gateways.gateway_unavailable", "请选择已启用的外部 AI 网关", "Select an enabled external AI gateway")
    return gateway


def resolve(db, gateway_id, platform_id, legacy=None):
    config = db.get(ExternalGatewayConfig, gateway_id)
    if config is not None:
        if config.deleted_at:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "网关配置已删除", "Gateway configuration was deleted")
        endpoint = db.get(ExternalDeliveryEndpoint, config.endpoint_id)
        if not config.enabled or not endpoint.enabled:
            raise ApiError(403, "FORBIDDEN", "网关配置已停用", "Gateway configuration is disabled")
        try:
            linked_gateway(db, endpoint.external_gateway_id)
        except ApiError as exc:
            status, code = (400, "INVALID_ARGUMENT") if endpoint.external_gateway_id is None else (403, "FORBIDDEN")
            raise ApiError(status, code, exc.zh_message, exc.en_message) from None
        if platform_id not in json.loads(endpoint.platform_ids_json):
            raise ApiError(403, "FORBIDDEN", "接入方未获网关配置授权", "The partner is not authorized for this gateway")
        if not endpoint.gateway_path:
            raise ApiError(400, "INVALID_ARGUMENT", "请配置结果同步接口路径", "Configure the result synchronization API path")
        return SimpleNamespace(version=endpoint.version)
    if legacy is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "网关配置不存在", "Gateway configuration not found")
    if platform_id not in legacy.platform_ids:
        raise ApiError(403, "FORBIDDEN", "接入方未获网关配置授权", "The partner is not authorized for this gateway")
    return legacy


def register_endpoint(db, endpoint):
    config = db.get(ExternalGatewayConfig, endpoint.config_id)
    if config and config.deleted_at:
        raise ApiError(409, "external_gateways.deleted", "该网关编号已删除，请使用新编号", "This gateway ID was deleted; use a new ID")
    if config is None:
        db.add(ExternalGatewayConfig(gateway_id=endpoint.config_id, name=endpoint.config_id,
            endpoint_id=endpoint.endpoint_id, enabled=endpoint.enabled, created_by=endpoint.created_by))
