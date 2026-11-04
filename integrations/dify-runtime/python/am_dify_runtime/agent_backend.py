"""Dify 1.16.1 Agent Backend Skill and shell execution boundaries."""
import asyncio
import base64
import contextvars
import functools
import hashlib
import inspect
import json
import uuid

from .client import Blocked, fingerprint

active = contextvars.ContextVar("am_dify_agent_run", default=None)


def context_for(identity, run_id):
    from .hooks import client_for
    client = client_for(identity.app_id, identity.tenant_id)
    if client is None:
        return None
    context = {"app_id": identity.app_id, "workspace_id": identity.tenant_id,
               "run_id": run_id, "workflow_id": identity.workflow_id or identity.agent_config_version_id or identity.agent_id,
               "graph_digest": fingerprint({"agent_id": identity.agent_id,
                   "config_version": identity.agent_config_version_id}),
               "node_id": identity.node_id or identity.agent_id, "node_title": "Agent",
               "execution_id": run_id, "node_type": "agent"}
    return client, context, identity


async def observe(state, kind, status, **details):
    await asyncio.to_thread(state[0].observe, state[1], kind, status, **details)


def shell_status(value):
    if isinstance(value, dict) and value.get("error"):
        return "failed"
    if isinstance(value, str) and value.startswith("<metadata>\n"):
        metadata = json.loads(value.split("</metadata>", 1)[0].removeprefix("<metadata>\n"))
        if metadata.get("exit_code") not in (None, 0):
            return "failed"
    return "succeeded"


async def controlled(state, node_type, title, parameters, invoke, *, tool="", govern=True):
    client, parent, identity = state
    context = {**parent, "node_type": node_type, "node_title": title,
               "execution_id": uuid.uuid4().hex, "call_index": 0}
    call = client, context, identity
    await observe(call, "step.start", "started", execution=parameters)
    try:
        value = (await asyncio.to_thread(client.execute, context,
            {"tool": tool, "code_digest": fingerprint(parameters) if node_type == "shell" else ""},
            parameters, invoke, result_status=shell_status) if govern else invoke())
        if inspect.isawaitable(value):
            value = await value
        status = shell_status(value)
        await observe(call, "step.end", status, outputs=value if not isinstance(value, bytes) else {"bytes": len(value)},
                      error=value if status == "failed" else None)
        return value
    except BaseException as exc:
        await observe(call, "step.end", "blocked" if isinstance(exc, Blocked) else "failed", error=str(exc))
        raise


async def check_package(state, name, archive):
    client, _, identity = state
    await asyncio.to_thread(client.post, f"/bindings/{client.binding}/skills/upload",
        {"dify_agent_id": identity.agent_id, "archive_base64": base64.b64encode(archive).decode("ascii")}, timeout=30)
    result = await asyncio.to_thread(client.post, f"/bindings/{client.binding}/skills/runtime-check",
        {"dify_agent_id": identity.agent_id,
         "skills": [{"name": name, "archive_hash": hashlib.sha256(archive).hexdigest()}]})
    item = result.get("skills", [{}])[0]
    certified = item.get("allowed") is True
    allowed = result.get("allowed") is True
    audit = (client, {**state[1], "execution_id": uuid.uuid4().hex,
                     "node_type": "skill", "node_title": name}, identity)
    await observe(audit, "step.end", "succeeded" if allowed else "blocked", execution={
        "skill_admission": {"name": name, "status": item.get("status", "MISSING"),
            "certified": certified, "allowed": allowed, "mode": result.get("mode"),
            "reason": "certified" if certified else "observe_unapproved" if allowed else "unapproved_blocked",
            "check_reason": item.get("reason", "missing")}})
    if not result.get("allowed"):
        reason = result.get("skills", [{}])[0].get("reason", "missing")
        raise Blocked(f"dify_runtime.skill_not_approved: {name} ({reason})")
    return result


def patch_skill_pull(module):
    original = module.DifyApiAgentStubConfigRequestHandler.pull_skill
    @functools.wraps(original)
    async def pull(self, *, principal, name):
        parent = active.get()
        state = parent or context_for(principal.execution_context, "skill-pull:" + uuid.uuid4().hex)
        if state is None:
            return await original(self, principal=principal, name=name)
        async def checked():
            archive = await original(self, principal=principal, name=name)
            await check_package(state, name, archive)
            return archive
        try:
            result = await controlled(state, "skill", name, {"skill": name}, checked, tool=name)
            if parent is None:
                await observe(state, "turn.end", "succeeded", outputs={"skill": name, "bytes": len(result)})
            return result
        except Blocked as exc:
            if parent is None:
                await observe(state, "turn.end", "failed", error=str(exc))
            raise module.AgentStubConfigRequestError(403, str(exc)) from None
        except Exception as exc:
            if parent is None:
                await observe(state, "turn.end", "failed", error=str(exc))
            raise
    module.DifyApiAgentStubConfigRequestHandler.pull_skill = pull
    from .hooks import hook_status
    hook_status["skill_runtime"] = True


async def check_config(state):
    from dify_agent.agent_stub.server.tokens.agent_stub import AgentStubPrincipal
    from dify_agent.server.settings import ServerSettings
    handler = ServerSettings().create_agent_stub_config_request_handler()
    if handler is None:
        raise Blocked("dify_runtime.skill_source_unavailable")
    principal = AgentStubPrincipal(execution_context=state[2], session_id=None, scope=[], token_id=state[1]["run_id"])
    manifest = await handler.manifest(principal=principal)
    for skill in manifest.skills.items:
        await handler.pull_skill(principal=principal, name=skill.name)


def patch_runner(module):
    original = module.AgentRunRunner._run_agent
    @functools.wraps(original)
    async def run(self):
        if not module._has_model_layer(self.request):
            return await original(self)
        from dify_agent.layers.execution_context.configs import DifyExecutionContextLayerConfig
        layer = next((item for item in self.request.composition.layers if item.type == "dify.execution_context"), None)
        identity = DifyExecutionContextLayerConfig.model_validate(layer.config) if layer else None
        state = context_for(identity, self.run_id) if identity else None
        if state is None:
            return await original(self)
        marker = active.set(state)
        try:
            await observe(state, "step.start", "started", execution={
                "workflow_run_id": identity.workflow_run_id})
            await check_config(state)
            result = await original(self)
            await observe(state, "step.end", "succeeded")
            await observe(state, "turn.end", "succeeded", outputs=result.output)
            return result
        except BaseException as exc:
            await observe(state, "step.end", "failed", error=str(exc))
            await observe(state, "turn.end", "failed", error=str(exc))
            raise
        finally:
            active.reset(marker)
    module.AgentRunRunner._run_agent = run
    from .hooks import hook_status
    hook_status["agent_runtime"] = True


def patch_shell(module):
    def wrap(name):
        original = getattr(module.DifyShellLayer, name)
        @functools.wraps(original)
        async def invoke(self, *args, **kwargs):
            state = active.get()
            if state is None:
                return await original(self, *args, **kwargs)
            params = dict(inspect.signature(original).bind(self, *args, **kwargs).arguments)
            params.pop("self")
            if name == "_bootstrap_workspace":
                params = {"install_commands": [command for tool in self.config.cli_tools for command in tool.install_commands]}
            govern = name not in {"_tool_wait", "_tool_interrupt"}
            if govern:
                await check_config(state)
            return await controlled(state, "shell", name.removeprefix("_tool_"), params,
                                    lambda: original(self, *args, **kwargs), tool=name.removeprefix("_tool_"), govern=govern)
        setattr(module.DifyShellLayer, name, invoke)
    for name in ("_tool_run", "_tool_input", "_tool_wait", "_tool_interrupt", "_bootstrap_workspace"):
        wrap(name)
    from .hooks import hook_status
    hook_status["shell_runtime"] = True
