"""Dify 1.16.1 Skill upload and publication boundaries."""
import base64
import contextvars
import functools
import hashlib

upload_target = contextvars.ContextVar("am_dify_skill_target", default=None)


def client_for_agent(session, tenant_id, agent_id, app_id=None):
    from models.agent import Agent
    from .hooks import client_for
    agent = session.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        return None
    return client_for(app_id or agent.app_id or agent.backing_app_id, tenant_id)


def send_package(client, agent_id, archive):
    from werkzeug.exceptions import ServiceUnavailable
    from .client import Blocked
    try:
        return client.post(f"/bindings/{client.binding}/skills/upload", {
            "dify_agent_id": agent_id, "archive_base64": base64.b64encode(archive).decode("ascii")}, timeout=30)
    except Blocked:
        raise ServiceUnavailable(description="Skill scan submission failed / Skill 检测提交失败，请检查平台连接、凭证及上传大小限制") from None


def check_soul(session, tenant_id, agent_id, soul, app_id=None):
    from core.tools.tool_file_manager import ToolFileManager
    from models.tools import ToolFile
    from werkzeug.exceptions import Forbidden
    from .client import Blocked
    client = client_for_agent(session, tenant_id, agent_id, app_id)
    if client is None:
        return
    refs = []
    try:
        for skill in [*soul.config_skills, *soul.files.skills]:
            file_id = getattr(skill, "full_archive_file_id", None) or skill.file_id
            file = session.get(ToolFile, file_id) if file_id else None
            if not file or file.tenant_id != tenant_id:
                raise Forbidden(description=f"Skill {skill.name}: package unavailable / Skill 包不可用")
            package = ToolFileManager().get_file_binary(file_id)
            if package is None:
                raise Forbidden(description=f"Skill {skill.name}: package unavailable / Skill 包不可用")
            archive = package[0]
            send_package(client, agent_id, archive)
            refs.append({"name": skill.name, "archive_hash": hashlib.sha256(archive).hexdigest()})
        result = client.post(f"/bindings/{client.binding}/skills/publish-check", {
            "dify_agent_id": agent_id, "skills": refs})
    except Blocked:
        raise Forbidden(description="Skill admission unavailable / Skill 准入服务不可用，请稍后重试") from None
    if not result.get("allowed"):
        names = ", ".join(item["name"] for item in result["skills"] if not item["allowed"])
        raise Forbidden(description=f"Skills require approval in Agent Manager / 请在平台完成 Skill 检测与审批: {names}")


def patch_config(module):
    original = module.AgentConfigService._upload_skill
    @functools.wraps(original)
    def upload(self, **kwargs):
        marker = upload_target.set((kwargs["tenant_id"], kwargs["agent_id"]))
        try:
            return original(self, **kwargs)
        finally:
            upload_target.reset(marker)
    module.AgentConfigService._upload_skill = upload
    from .hooks import hook_status
    hook_status["skill_upload"] = True


def patch_normalizer(module):
    original = module.ConfigSkillNormalizeService.normalize
    @functools.wraps(original)
    def normalize(self, **kwargs):
        result = original(self, **kwargs)
        target = upload_target.get()
        if target:
            from core.db.session_factory import session_factory
            with session_factory.create_session() as session:
                client = client_for_agent(session, *target)
                if client:
                    send_package(client, target[1], result[1].archive_bytes)
        return result
    module.ConfigSkillNormalizeService.normalize = normalize


def patch_standardize(module):
    original = module.SkillStandardizeService.standardize
    @functools.wraps(original)
    def standardize(self, **kwargs):
        client = client_for_agent(kwargs["session"], kwargs["tenant_id"], kwargs["agent_id"])
        if client:
            package = self._package.validate_and_normalize(content=kwargs["content"], filename=kwargs["filename"])
            send_package(client, kwargs["agent_id"], package.archive_bytes)
        return original(self, **kwargs)
    module.SkillStandardizeService.standardize = standardize


def patch_composer(module):
    original = module.AgentComposerService._create_config_version.__func__
    @functools.wraps(original)
    def create(cls, **kwargs):
        if kwargs["operation"] == module.AgentConfigRevisionOperation.PUBLISH_DRAFT:
            check_soul(kwargs["session"], kwargs["tenant_id"], kwargs["agent_id"], kwargs["agent_soul"])
        return original(cls, **kwargs)
    module.AgentComposerService._create_config_version = classmethod(create)
    from .hooks import hook_status
    hook_status["skill_publish"] = True


def patch_workflow_publish(module):
    original = module.WorkflowAgentPublishService._require_drive_refs_resolved_for_publish.__func__
    @functools.wraps(original)
    def require(cls, **kwargs):
        original(cls, **kwargs)
        binding = kwargs["binding"]
        check_soul(kwargs["session"], binding.tenant_id, binding.agent_id,
                   kwargs["agent_soul"], app_id=binding.app_id)
    module.WorkflowAgentPublishService._require_drive_refs_resolved_for_publish = classmethod(require)
