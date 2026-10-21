"""Dify 1.15 / graphon 0.5.3 invocation points."""
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
from pathlib import Path
from urllib.parse import urlsplit

from .client import ApprovalPause, Blocked, Client, fingerprint

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
                "node_id": node_id, "execution_id": node.ensure_execution_id(), "node_type": node_type}

    @functools.wraps(original)
    def wrapped():
        ctx = context()
        client.contexts[ctx["run_id"]] = ctx
        token = current.set((client, ctx))
        try:
            client.observe(ctx, "step.start", "started")
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
            client.observe(ctx, "step.end", "failed" if status == "failed" else "succeeded")
            return result
        except ApprovalPause as pause:
            return iter([pause_event(node, pause.action_id)])
        except Blocked:
            client.observe(ctx, "step.end", "blocked")
            raise
        except Exception:
            client.observe(ctx, "step.end", "failed")
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
    while True:
        paused = False
        token = current.set((client, context))
        try:
            item = next(iterator)
        except StopIteration:
            client.observe(context, "step.end", status)
            return
        except ApprovalPause as pause:
            item = pause_event(node, pause.action_id)
            paused = True
        except Exception:
            client.observe(context, "step.end", "failed")
            raise
        finally:
            current.reset(token)
        result = getattr(item, "node_run_result", None)
        if str(getattr(result, "status", "")) == "failed":
            status = "failed"
        yield item
        if paused:
            return


def patch_factory(module):
    if importlib.metadata.version("graphon") != "0.5.3":
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
        client.observe(context, "model.request", "started")
        try:
            result = original(self, *args, **kwargs)
        except Exception:
            client.observe(context, "model.error", "failed")
            raise
        if inspect.isgenerator(result):
            def stream():
                try:
                    yield from result
                except Exception:
                    client.observe(context, "model.error", "failed")
                    raise
                client.observe(context, "model.response", "succeeded")
            return stream()
        client.observe(context, "model.response", "succeeded")
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
                                "execution_id": run_id}, "turn.end", status)
                client.runs.pop((run_id, context["graph_digest"]), None)
    module.PauseStatePersistenceLayer.on_event = on_event
    hook_status["workflow_lifecycle"] = True


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
                 "core.model_manager": patch_models, "app_factory": patch_app,
                 "core.app.layers.pause_state_persist_layer": patch_lifecycle}

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
