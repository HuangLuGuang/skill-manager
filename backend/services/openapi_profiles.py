"""Manage the same profile files consumed by external task submission."""
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import uuid
from pathlib import Path

from pydantic import ValidationError

from ..api_errors import ApiError
from . import openapi_agents, openapi_skills


def config_path(kind, data_dir):
    path = openapi_skills.configuration_path(data_dir) if kind == "skill" else openapi_agents.configuration_path()
    return path.resolve()


def read_configuration(kind, path):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        config = {"profiles": {}, "callbacks": {}}
        if kind == "agent":
            config.update(partners={}, gateways={})
        return config, hashlib.sha256(b"missing").hexdigest()
    except OSError:
        raise unavailable() from None
    try:
        config = json.loads(raw)
        model = openapi_skills.SkillConfiguration if kind == "skill" else openapi_agents.Configuration
        model.model_validate(config)
    except (ValueError, TypeError):
        raise ApiError(422, "openapi_profiles.config_invalid", "现有方案配置文件格式无效，请修复后刷新", "The existing profile file is invalid. Repair it and refresh") from None
    return config, hashlib.sha256(raw).hexdigest()


def unavailable():
    return ApiError(503, "openapi_profiles.storage_unavailable", "方案配置文件无法读写，请检查文件权限和存储", "Profile storage is unavailable. Check file permissions and storage")


def profile_model(kind):
    return openapi_skills.Profile if kind == "skill" else openapi_agents.EvaluationProfile


def listing(kind, path):
    config, revision = read_configuration(kind, path)
    return {"revision": revision, "items": [{"profile_id": key, **profile_model(kind).model_validate(value).model_dump()}
            for key, value in sorted(config["profiles"].items())]}


def validate_settings(kind, settings):
    try:
        if "version" in settings:
            raise ValueError("version")
        profile = profile_model(kind).model_validate({**settings, "version": "1"}, strict=True)
        for field in ("platform_ids", "malicious_rule_ids"):
            values = getattr(profile, field)
            if len(set(values)) != len(values) or any(not value.strip() or value != value.strip() for value in values):
                raise ValueError(field)
        if kind == "agent":
            for field in ("policy_id", "evaluation_model"):
                if not getattr(profile, field).strip():
                    raise ValueError(field)
        return profile
    except (ValidationError, ValueError) as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}) if isinstance(exc, ValidationError) else [str(exc)]
        raise ApiError(422, "openapi_profiles.invalid_fields", "请检查方案字段、必填项和重复编码", "Check profile fields, required values and duplicate identifiers", params={"fields": fields}) from None


def save(kind, path, body, *, create):
    """Serialize writers across workers, check the editor revision, then replace atomically."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / (path.name + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config, revision = read_configuration(kind, path)
            if revision != body.revision:
                raise ApiError(409, "openapi_profiles.conflict", "方案配置已变更，请刷新列表后重新打开编辑", "Profile configuration changed. Refresh the list and reopen the editor")
            current = config["profiles"].get(body.profile_id)
            if create and current is not None:
                raise ApiError(409, "openapi_profiles.exists", "方案编号已存在", "Profile ID already exists")
            if not create and current is None:
                raise ApiError(404, "openapi_profiles.not_found", "方案不存在", "Profile not found")
            profile = validate_settings(kind, body.settings).model_dump()
            old = profile_model(kind).model_validate(current).model_dump() if current is not None else None
            if old and {k: v for k, v in old.items() if k != "version"} == body_settings(profile):
                return listing(kind, path)
            profile["version"] = "v_" + uuid.uuid4().hex
            config["profiles"][body.profile_id] = profile
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".openapi-profile-", delete=False) as output:
                temporary = Path(output.name)
                if path.exists():
                    os.fchmod(output.fileno(), stat.S_IMODE(path.stat().st_mode))
                json.dump(config, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            temporary = None
            return listing(kind, path)
    except OSError:
        raise unavailable() from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def body_settings(profile):
    return {key: value for key, value in profile.items() if key != "version"}
