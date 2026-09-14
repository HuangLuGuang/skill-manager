"""Shared model-switch contract and validation for local and remote requests."""
import json
import math
import re
from pathlib import Path

from agent_manager import core
from backend.api_errors import ApiError

CONTRACT = json.loads((Path(core.__file__).parent / "model_switch_contract.json").read_text())
AGENTS = CONTRACT["agents"]


def contract_for_version(agent_type: str, version: str | None) -> dict:
    spec = dict(AGENTS[agent_type])
    found = re.search(r"\b[vV]?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?)", version or "")
    supported = bool(found and found.group(1) in spec.get("parameter_versions", []))
    spec["parameter_status"] = "available" if supported or not spec["parameters"] else "version_unverified"
    if not supported:
        spec["parameters"] = {}
    return spec


def validate_parameter_version(agent_type: str, parameters: dict, version: str | None):
    if any(value is not None for value in parameters.values()) and contract_for_version(agent_type, version)["parameter_status"] != "available":
        raise ApiError(422, "client.model_parameter_version_unverified", "该 Agent 版本的参数支持尚未验证，请刷新发现结果或保留现有参数", "Parameter support is unverified for this Agent version; refresh discovery or retain existing parameters")


def reported_model_parameters(capabilities) -> dict:
    if not isinstance(capabilities, dict):
        raise ApiError(422, "client.model_parameters_invalid", "模型参数必须是对象", "Model parameters must be an object")
    state = capabilities.get("model_config_state")
    if state is None:
        return {}
    if not isinstance(state, dict) or not isinstance(state.get("parameters", {}), dict):
        raise ApiError(422, "client.model_parameters_invalid", "模型参数必须是对象", "Model parameters must be an object")
    return state.get("parameters", {})


def validate_effective_parameters(agent_type: str, parameters: dict, current: dict, model):
    if not isinstance(current, dict):
        raise ApiError(422, "client.model_parameters_invalid", "模型参数必须是对象", "Model parameters must be an object")
    effective = {key: value for key, value in current.items() if key in AGENTS[agent_type]["parameters"]}
    effective.update({key: value for key, value in parameters.items() if value is not None})
    return validate_options(agent_type, effective, model=model)["parameters"]


def validate_options(agent_type: str, parameters, revision=None, model=None) -> dict:
    spec = AGENTS.get(agent_type)
    if not spec:
        raise ApiError(400, "client.model_config_agent_unsupported", "Agent 不支持模型配置", "Agent does not support model configuration")
    if not isinstance(parameters, dict):
        raise ApiError(422, "client.model_parameters_invalid", "模型参数必须是对象", "Model parameters must be an object")
    result = {}
    for key, value in parameters.items():
        field = spec["parameters"].get(key)
        if not field:
            raise ApiError(422, "client.model_parameter_unsupported", "该 Agent 不支持此参数", "The Agent does not support this parameter")
        if value is None:
            continue
        valid = False
        if field["type"] in {"integer", "number"}:
            valid = (type(value) in {int, float} and math.isfinite(value)
                     and field["min"] <= value <= field["max"]
                     and (field["type"] != "integer" or int(value) == value))
        else:
            valid = isinstance(value, str) and value in field["enum"]
        if not valid:
            raise ApiError(422, "client.model_parameter_invalid", "模型参数值无效", "Invalid model parameter value")
        if model and field["condition"] == "model_output_limit" and model.max_output_tokens and value > model.max_output_tokens:
            raise ApiError(422, "client.model_output_limit", "参数超过平台模型输出限制", "The parameter exceeds the platform model output limit")
        result[key] = value
    if revision is not None and (not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision)):
        raise ApiError(422, "client.model_revision_invalid", "配置版本指纹无效", "Invalid configuration revision")
    return {"parameters": result, **({"expected_revision": revision} if revision else {})}
