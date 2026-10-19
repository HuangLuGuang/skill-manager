"""Current callback configuration backed by immutable delivery endpoints."""
import json
from types import SimpleNamespace

from ..api_errors import ApiError
from ..external_access_models import ExternalCallbackConfig, ExternalDeliveryEndpoint


def resolve(db, callback_id, platform_id, task_type, legacy=None):
    config = db.get(ExternalCallbackConfig, callback_id) if db is not None else None
    if config is not None:
        if config.deleted_at:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "回调配置已删除", "Callback configuration was deleted")
        endpoint = db.get(ExternalDeliveryEndpoint, config.endpoint_id)
        if not config.enabled or not endpoint.enabled:
            raise ApiError(403, "FORBIDDEN", "回调配置已停用", "Callback configuration is disabled")
        if platform_id not in json.loads(endpoint.platform_ids_json) or task_type not in json.loads(endpoint.notification_types_json):
            raise ApiError(403, "FORBIDDEN", "回调配置未授权该接入方或通知类型", "Callback configuration does not authorize this partner or notification type")
        return SimpleNamespace(version=endpoint.version)
    # Existing file-only installations continue to resolve their saved references.
    if legacy is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "回调配置不存在", "Callback configuration not found")
    if platform_id not in legacy.platform_ids:
        raise ApiError(403, "FORBIDDEN", "接入方未获回调配置授权", "The partner is not authorized for this callback")
    return legacy


def register_endpoint(db, endpoint):
    """Keep the original receiver management API compatible with callback management."""
    config = db.get(ExternalCallbackConfig, endpoint.config_id)
    if config and config.deleted_at:
        raise ApiError(409, "external_callbacks.deleted", "该回调编号已删除，请使用新编号", "This callback ID was deleted; use a new ID")
    if config is None:
        config = ExternalCallbackConfig(callback_id=endpoint.config_id, name=endpoint.config_id,
            endpoint_id=endpoint.endpoint_id, enabled=endpoint.enabled, created_by=endpoint.created_by)
        db.add(config)
    return config
