"""Dify 1.15.0 / graphon 0.5.3 and Dify 1.16.1 / graphon 0.6.0 invocation points."""
import contextvars
import functools
import importlib.abc
import importlib.machinery
import inspect
import importlib.metadata
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .client import ApprovalPause, Blocked, Client, fingerprint
from .skills import patch_config, patch_normalizer, patch_standardize, patch_composer, patch_workflow_publish
from .agent_backend import patch_runner, patch_shell, patch_skill_pull

current = contextvars.ContextVar("am_dify_context", default=None)
clients = {}
client_lock = threading.Lock()
hook_status = {}
flask_app = None


def graph_fingerprint(graph):
    normalized = {
        "nodes": sorted(({"id": n["id"], "data": n["data"]} for n in graph.get("nodes", [])), key=lambda n: str(n["id"])),
        "edges": sorted(({k: e.get(k) for k in ("source", "target", "sourceHandle", "targetHandle")}
                         for e in graph.get("edges", [])), key=lambda e: json.dumps(e, sort_keys=True)),
    }
    return fingerprint(normalized)


def resume_workflow(run_id, action_id):
    if flask_app is None:
        return False
    with flask_app.app_context():
        from extensions.ext_database import db
        from extensions.ext_redis import redis_client
        from models.workflow import WorkflowPause, WorkflowPauseReason, WorkflowRun
        from tasks.app_generate.workflow_execute_task import _resume_app_execution
        lock = redis_client.lock("am-dify-resume:" + run_id, timeout=3600, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            return False
        try:
            pause = db.session.query(WorkflowPause).filter_by(workflow_run_id=run_id, resumed_at=None).first()
            if pause is None:
                run = db.session.get(WorkflowRun, run_id)
                return run is not None and str(run.status) in {"succeeded", "failed", "stopped", "partial-succeeded"}
            reason = db.session.query(WorkflowPauseReason).filter_by(
                pause_id=pause.id, message="agent-manager:" + action_id).first()
            if reason is None:
                return False
            _resume_app_execution({"workflow_run_id": run_id})
            return True
        finally:
            db.session.remove()
            lock.release()


def client_for(app_id, workspace_id):
    path = os.environ.get("AM_DIFY_CONFIG")
    if not path:
        return None
    config = json.loads(Path(path).read_text())
    application = next((a for a in config["applications"] if a["app_id"] == app_id
                        and a["workspace_id"] == workspace_id), None)
    if not application:
        return None
    key = (os.getpid(), application["binding_id"])
    with client_lock:
        if key not in clients:
            clients[key] = Client(config, application)
            clients[key].hooks = hook_status
            clients[key].resume = resume_workflow
        return clients[key]


def guarded(fields, parameters, invoke):
    state = current.get()
    if state is None:
        return invoke()
    client, context = state
    client.observe(context, "context.injected", "started", execution=parameters)
    return client.execute(context, fields, parameters, invoke)


def wrap_node(factory, node, config):
    global flask_app
    from flask import current_app
    flask_app = current_app._get_current_object()
    original = node._run
    if getattr(original, "_am_wrapped", False):
        return
    dify = factory._dify_context
    client = client_for(dify.app_id, dify.tenant_id)
    if client is None:
        return
    graph = factory.graph_init_params.graph_config
    digest = graph_fingerprint(graph)
    node_id = str(config["id"])
    node_type = str(node.node_type)

    def context():
        pool = factory.graph_runtime_state.variable_pool
        segment = pool.get(["sys", "workflow_run_id"])
        run_id = getattr(segment, "value", None)
        if not run_id:
            raise Blocked("dify_runtime.run_identity_missing")
        return {"app_id": dify.app_id, "workspace_id": dify.tenant_id, "run_id": str(run_id),
                "workflow_id": factory.graph_init_params.workflow_id, "graph_digest": digest,
                "node_id": node_id, "node_title": str(config.get("data", {}).get("title", node_id))[:256],
                "execution_id": node.ensure_execution_id(), "node_type": node_type}

    @functools.wraps(original)
    def wrapped():
        ctx = context()
        client.contexts[ctx["run_id"]] = ctx
        token = current.set((client, ctx))
        try:
            client.observe(ctx, "step.start", "started")
            if node_type == "start":
                pool = factory.graph_runtime_state.variable_pool
                user_inputs = dict(pool.get_by_prefix(node_id))
                query = pool.get(["sys", "query"])
                files = pool.get(["sys", "files"])
                if query is not None:
                    user_inputs["query"] = query.value
                if files is not None:
                    user_inputs["files"] = files.value
                client.observe(ctx, "message.user", "succeeded", inputs=user_inputs)
            if node_type in {"knowledge-retrieval"}:
                data = node.node_data.model_dump(mode="json")
                datasets = data.get("dataset_ids") or []
                resolved = {}
                for key in ("query_variable_selector", "query_attachment_selector"):
                    selector = data.get(key)
                    if isinstance(selector, list) and selector:
                        value = factory.graph_runtime_state.variable_pool.get(selector)
                        resolved[key] = getattr(value, "value", None)
                result = client.execute(ctx, {"datasets": list(datasets)}, {"config": data, "inputs": resolved}, original)
            else:
                result = original()
            if inspect.isgenerator(result):
                return scoped_generator(result, client, ctx, node)
            status = str(getattr(result, "status", "succeeded"))
            client.observe(ctx, "step.end", "failed" if status == "failed" else "succeeded",
                           **{key: getattr(result, key, None) for key in ("inputs", "outputs", "error")})
            return result
        except ApprovalPause as pause:
            return iter([pause_event(node, pause.action_id)])
        except Blocked as exc:
            client.observe(ctx, "step.end", "blocked", error=str(exc))
            raise
        except Exception as exc:
            client.observe(ctx, "step.end", "failed", error=str(exc))
            raise
        finally:
            current.reset(token)
    wrapped._am_wrapped = True
    node._run = wrapped


def pause_event(node, action_id):
    from graphon.entities.pause_reason import SchedulingPause
    from graphon.graph_events import NodeRunPauseRequestedEvent
    return NodeRunPauseRequestedEvent(id=node.execution_id, node_id=node._node_id, node_type=node.node_type,
        reason=SchedulingPause(message="agent-manager:" + action_id))


def scoped_generator(iterator, client, context, node):
    status = "succeeded"
    details = {}
    while True:
        paused = False
        token = current.set((client, context))
        try:
            item = next(iterator)
        except StopIteration:
            client.observe(context, "step.end", status, **details)
            return
        except ApprovalPause as pause:
            item = pause_event(node, pause.action_id)
            paused = True
        except Exception as exc:
            client.observe(context, "step.end", "failed", error=str(exc))
            raise
        finally:
            current.reset(token)
        result = getattr(item, "node_run_result", None)
        if result is not None:
            details = {key: getattr(result, key, None) for key in ("inputs", "outputs", "error")}
        if str(getattr(result, "status", "")) == "failed":
            status = "failed"
        yield item
        if paused:
            return


def patch_factory(module):
    if importlib.metadata.version("graphon") not in {"0.5.3", "0.6.0"}:
        raise RuntimeError("dify_runtime.unsupported_graphon_version")
    cls = module.DifyNodeFactory
    original = cls.create_node
    @functools.wraps(original)
    def create(self, node_config):
        node = original(self, node_config)
        wrap_node(self, node, node_config)
        return node
    cls.create_node = create
    hook_status["workflow_context"] = True

    from graphon.nodes.http_request.executor import Executor
    http = Executor._do_http_request
    @functools.wraps(http)
    def request(self, headers):
        return guarded({"host": (urlsplit(self.url).hostname or "").lower(), "method": self.method.upper()},
                       {"url": self.url, "method": self.method, "params": self.params,
                        "data": self.data, "json": self.json, "content": self.content,
                        "headers": headers},
                       lambda: http(self, headers))
    Executor._do_http_request = request
    hook_status["http_request"] = True

    from core.helper.code_executor.code_executor import CodeExecutor
    execute = CodeExecutor.execute_workflow_code_template
    @functools.wraps(execute)
    def code(*args, **kwargs):
        params = inspect.signature(execute).bind(*args, **kwargs).arguments
        return guarded({"code_digest": fingerprint(params.get("code", ""))}, params,
                       lambda: execute(*args, **kwargs))
    CodeExecutor.execute_workflow_code_template = staticmethod(code)
    hook_status["code"] = True
    hook_status["knowledge_retrieval"] = True


def patch_models(module):
    original = module.ModelInstance.invoke_llm
    @functools.wraps(original)
    def invoke(self, *args, **kwargs):
        state = current.get()
        if state is None:
            return original(self, *args, **kwargs)
        client, context = state
        request_id = uuid.uuid4().hex
        bound = inspect.signature(original).bind(self, *args, **kwargs).arguments
        inputs = {key: bound[key] for key in ("prompt_messages", "model_parameters", "tools", "stop") if key in bound}
        inputs.update(model=self.model_name, provider=self.provider)
        client.observe(context, "model.request", "started", request_id=request_id, inputs=inputs)
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            client.observe(context, "model.error", "failed", request_id=request_id, error=str(exc))
            raise
        if inspect.isgenerator(result):
            def stream():
                try:
                    for chunk in result:
                        client.observe(context, "model.response", "started", request_id=request_id,
                                       outputs=chunk.delta)
                        yield chunk
                except Exception as exc:
                    client.observe(context, "model.error", "failed", request_id=request_id, error=str(exc))
                    raise
                client.observe(context, "model.response", "succeeded", request_id=request_id)
            return stream()
        client.observe(context, "model.response", "succeeded", request_id=request_id, outputs=result)
        return result
    module.ModelInstance.invoke_llm = invoke
    hook_status["model"] = True


def initialize_clients():
    global client_lock, clients
    client_lock = threading.Lock()
    clients = {}
    path = os.environ.get("AM_DIFY_CONFIG")
    if path:
        for app in json.loads(Path(path).read_text())["applications"]:
            client_for(app["app_id"], app["workspace_id"])


def reset_after_fork():
    global client_lock, clients
    client_lock = threading.Lock()
    clients = {}


def patch_app(module):
    original = module.create_app
    @functools.wraps(original)
    def create(*args, **kwargs):
        global flask_app
        result = original(*args, **kwargs)
        flask_app = result[1]
        initialize_clients()
        return result
    module.create_app = create


def patch_lifecycle(module):
    original = module.PauseStatePersistenceLayer.on_event
    terminal = {"GraphRunSucceededEvent": "succeeded", "GraphRunFailedEvent": "failed",
                "GraphRunPartialSucceededEvent": "failed", "GraphRunAbortedEvent": "cancelled"}
    def on_event(self, event):
        original(self, event)
        status = terminal.get(type(event).__name__)
        if status is None:
            return
        segment = self.graph_runtime_state.variable_pool.get(["sys", "workflow_run_id"])
        run_id = str(getattr(segment, "value", ""))
        for client in list(clients.values()):
            context = client.contexts.pop(run_id, None)
            if context:
                client.observe({**context, "node_id": "__workflow__", "node_type": "workflow",
                                "node_title": "", "execution_id": run_id}, "turn.end", status,
                               outputs=getattr(event, "outputs", None), error=getattr(event, "error", None) or getattr(event, "reason", None))
                client.runs.pop((run_id, context["graph_digest"]), None)
    module.PauseStatePersistenceLayer.on_event = on_event
    hook_status["workflow_lifecycle"] = True


def patch_pause_queue(module):
    if importlib.metadata.version("graphon") != "0.6.0":
        return
    from core.app.entities.queue_entities import QueueWorkflowPausedEvent
    cls = getattr(module, "WorkflowAppQueueManager", None) or module.MessageBasedAppQueueManager
    original = cls._publish

    @functools.wraps(original)
    def publish(self, event, pub_from):
        if isinstance(event, QueueWorkflowPausedEvent) and any(
            str(getattr(reason, "message", "")).startswith("agent-manager:") for reason in event.reasons
        ):
            # Dify 1.16.1 otherwise aborts this checkpoint when its response stream closes.
            self._execution_terminal.set()
        return original(self, event, pub_from)

    cls._publish = publish


def patch_tools(module):
    def wrap(original):
        @functools.wraps(original)
        def invoke(*args, **kwargs):
            params = inspect.signature(original).bind(*args, **kwargs).arguments
            tool = params["tool"]
            values = {**(getattr(tool.runtime, "runtime_parameters", None) or {}), **params["tool_parameters"]}
            return guarded({"tool": tool.entity.identity.name}, values, lambda: original(*args, **kwargs))
        return invoke
    for name in ("_invoke", "generic_invoke"):
        setattr(module.ToolEngine, name, staticmethod(wrap(getattr(module.ToolEngine, name))))
    hook_status["tool"] = True


class Loader(importlib.abc.Loader):
    def __init__(self, wrapped, callback):
        self.wrapped, self.callback = wrapped, callback

    def create_module(self, spec):
        return self.wrapped.create_module(spec)

    def exec_module(self, module):
        self.wrapped.exec_module(module)
        self.callback(module)


class Finder(importlib.abc.MetaPathFinder):
    callbacks = {"core.workflow.node_factory": patch_factory, "core.tools.tool_engine": patch_tools,
                 "dify_agent.runtime.runner": patch_runner,
                 "dify_agent.layers.shell.layer": patch_shell,
                 "dify_agent.agent_stub.server.agent_stub_config": patch_skill_pull,
                 "services.agent_config_service": patch_config,
                 "services.agent.config_skill_normalize_service": patch_normalizer,
                 "services.agent.skill_standardize_service": patch_standardize,
                 "services.agent.composer_service": patch_composer,
                 "services.agent.workflow_publish_service": patch_workflow_publish,
                 "core.model_manager": patch_models, "app_factory": patch_app,
                 "core.app.layers.pause_state_persist_layer": patch_lifecycle,
                 "core.app.apps.workflow.app_queue_manager": patch_pause_queue,
                 "core.app.apps.message_based_app_queue_manager": patch_pause_queue}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.callbacks:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = Loader(spec.loader, self.callbacks[fullname])
        return spec


def install():
    if os.environ.get("AM_DIFY_CONFIG") and not any(isinstance(f, Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, Finder())
        os.register_at_fork(after_in_child=reset_after_fork)
