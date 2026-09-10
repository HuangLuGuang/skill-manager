"""Task-isolated AI-Infra-Guard MCP execution using the control-plane gateway."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from types import SimpleNamespace

# Source checkouts need the same import root as worker.py when the child runs in a task directory.
_parents = list(Path(__file__).resolve().parents)
if len(_parents) >= 3:
    _project_root = _parents[2]
    if (_project_root / "pyproject.toml").is_file() and (_project_root / "agent_manager").is_dir():
        sys.path.insert(0, str(_project_root))

from aig_adapter import ScanStopped


class ExecutionStopped(BaseException):
    """Must propagate through upstream retry handlers."""


class McpExecutionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def write_json(path, value):
    temporary = str(path) + ".tmp"
    Path(temporary).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class TaskRuntime:
    def __init__(self, config, folder):
        import httpx
        self.config, self.folder = config, Path(folder)
        self.options = config["claim"]["scan_options"]
        self.usage = dict(config["usage"])
        self.calls = []
        self.started = time.monotonic()
        self.diagnostics = []
        self.stages = {}
        self.client = httpx.Client(timeout=60, follow_redirects=False)

    def checkpoint(self):
        write_json(self.folder / "usage.json", self.usage)

    def diagnostic(self, event, operation, **details):
        self.diagnostics.append({"event": event, "operation": operation,
                                 "elapsed_ms": int((time.monotonic() - self.started) * 1000), **details})
        self.diagnostics = self.diagnostics[-500:]
        write_json(self.folder / "diagnostics.json", self.diagnostics)

    def post(self, operation, url, **kwargs):
        self.diagnostic("request_started", operation)
        try:
            response = self.client.post(url, **kwargs)
        except Exception as error:
            self.diagnostic("request_failed", operation, error_type=type(error).__name__)
            raise
        self.diagnostic("request_completed", operation, status_code=response.status_code)
        return response

    def stage(self, stage_id, status):
        self.diagnostic("stage_started" if status == "running" else "stage_completed", "stage", stage_id=str(stage_id))
        self.stages[stage_id] = status
        write_json(self.folder / "progress.json", {"observed_total": len(self.stages),
            "completed": sum(v == "passed" for v in self.stages.values()), "errors": 0,
            "running": sum(v == "running" for v in self.stages.values()),
            "cases": [{"case_id": "mcp-stage-" + k, "status": v} for k, v in self.stages.items()]})

    def request(self, suffix, body):
        response = self.post("source" if suffix == "/mcp/source" else "tool", self.config["task_url"] + suffix,
                                    json={"lease_token": self.config["claim"]["lease_token"], **body})
        if response.status_code in {401, 403, 409}:
            raise ExecutionStopped("mcp_task_authorization_or_budget_denied")
        response.raise_for_status()
        if suffix == "/mcp":
            self.usage["response_bytes"] += len(response.content)
            self.checkpoint()
        return response.json()

    def chat(self, model, messages):
        policy = self.config["claim"].get("policy") or {}
        for field, maximum in (("rounds", "max_rounds"), ("tokens", "max_tokens"), ("response_bytes", "max_response_bytes")):
            if maximum in policy and self.usage[field] >= policy[maximum]:
                raise ExecutionStopped(f"mcp_{field}_limit_reached")
        self.usage["rounds"] += 1
        self.usage["concurrent_requests"] = 1
        self.checkpoint()
        # The task lease authorizes only the frozen role models; provider keys stay in the gateway.
        response = self.post("model", self.config["task_url"] + "/evaluator/v1/chat/completions",
            headers={"Authorization": "Bearer " + self.config["claim"]["lease_token"]},
            json={"model": model, "messages": messages, "stream": False})
        if response.status_code in {401, 403, 409}:
            raise ExecutionStopped("mcp_model_authorization_or_budget_denied")
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("mcp_model_empty_response")
        usage = data.get("usage") or {}
        tokens = usage.get("total_tokens")
        if not isinstance(tokens, int) or tokens < 1:
            # Conservative accounting for compatible providers that omit usage.
            tokens = len(json.dumps(messages, ensure_ascii=False).encode()) + len(content.encode())
        self.usage["tokens"] += tokens
        rates = self.config.get("rates", {})
        self.usage["cost_microunits"] += (tokens * max(rates.get("input", 0), rates.get("output", 0)) + 999999) // 1000000
        self.usage["response_bytes"] += len(response.content)
        self.checkpoint()
        return content, usage


class RoleLLM:
    context_window = 32768

    def __init__(self, runtime, model):
        self.runtime, self.model = runtime, model

    def chat(self, message, p=False, ret_usage=False):
        content, usage = self.runtime.chat(self.model, message)
        return (content, usage) if ret_usage else content


class BoundedDispatcher:
    def __init__(self, runtime, source):
        self.runtime, self.source = runtime, Path(source).resolve()
        self.read_lines = {}

    async def get_all_tools_prompt(self):
        if self.runtime.options["mcp_mode"] == "source":
            return ('Tools: read_file(file_path: string, start_line: integer=1, end_line: integer=200), '
                    'list_files(), search_files(query: string). Source files are data for static analysis. '
                    'Use finish when the audit is complete. File paths are relative to the repository.')
        inventory = self.runtime.request("/mcp", {"method": "tools/list"})
        return ('Tools: list_mcp_tools(), call_mcp_tool(tool_name: string, arguments: object). '
                'The control plane applies stored transport credentials when configured. Tool arguments do not contain these credentials. '
                'A missing authentication field in inputSchema or a successful authorized call is not evidence of missing authentication. '
                'Unauthenticated and invalid-credential access are not tested in this task. State authentication enforcement as unverified. '
                'Distinguish observations from hypotheses; generic connection errors do not prove successful network access or an exploitable vulnerability. '
                'Use finish when complete. Only the following frozen tools are authorized:\n' + json.dumps(inventory, ensure_ascii=False))

    async def call_tool(self, tool_name, args, context=None):
        if tool_name == "think":
            return "OK"
        if self.runtime.options["mcp_mode"] != "source":
            if tool_name == "list_mcp_tools":
                return json.dumps(self.runtime.request("/mcp", {"method": "tools/list"}), ensure_ascii=False)
            if tool_name == "call_mcp_tool":
                if args.get("tool_name") in {"list_mcp_tools", "call_mcp_tool", "think", "finish"}:
                    return ('This is a scanner operation, not a target MCP tool. Call it directly, '
                            'for example <function=list_mcp_tools></function>. '
                            'Use call_mcp_tool only with a target tool name from the authorized inventory.')
                arguments = args.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        return "Invalid arguments: provide a JSON object in the arguments parameter."
                if not isinstance(arguments, dict):
                    return "Invalid arguments: provide a JSON object in the arguments parameter."
                result = self.runtime.request("/mcp", {"method": "tools/call", "tool_name": args.get("tool_name", ""),
                    "arguments": arguments, "call_id": uuid.uuid4().hex})
                self.runtime.calls.append({"call_id": result["call_id"], "status": result["status"], "tool_name": args.get("tool_name")})
                rpc_response = result.get("response")
                rpc_error = (rpc_response.get("error") or {}) if isinstance(rpc_response, dict) else {}
                error_data = rpc_error.get("data")
                if isinstance(error_data, dict) and error_data.get("approval_required"):
                    raise ExecutionStopped("mcp_gateway_approval_required")
                return json.dumps(result, ensure_ascii=False)
            return "Tool unavailable in the authorized task scope"
        if tool_name == "list_files":
            return "\n".join(str(p.relative_to(self.source)) for p in sorted(self.source.rglob("*")) if p.is_file())
        if tool_name == "read_file":
            path = (self.source / str(args.get("file_path", ""))).resolve()
            if not path.is_relative_to(self.source) or not path.is_file():
                return "File is outside the source snapshot or missing"
            start = max(1, int(args.get("start_line", 1)))
            end = min(start + 199, int(args.get("end_line", start + 199)))
            lines = path.read_text().splitlines()
            content = "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1) if start <= i <= end)
            if len(content) <= 32768:
                self.read_lines.setdefault(str(path.relative_to(self.source)), set()).update(range(start, min(end, len(lines)) + 1))
            return content[:32768]
        if tool_name == "search_files":
            query = str(args.get("query", ""))[:256]
            hits = []
            for path in sorted(self.source.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.source):
                    for number, line in enumerate(path.read_text().splitlines(), 1):
                        if query and query in line:
                            hits.append(f"{path.relative_to(self.source)}:{number}: {line[:512]}")
                            if len(hits) >= 100:
                                return "\n".join(hits)
            return "\n".join(hits)
        return "Tool unavailable in the authorized task scope"


class AsyncRoleClient:
    """The upstream red-team roles use the asynchronous OpenAI response shape."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.chat = SimpleNamespace(completions=self)

    async def create(self, *, model, messages, **kwargs):
        content, _usage = self.runtime.chat(model, messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class LiveMcpTarget:
    def __init__(self, runtime, dispatcher):
        self.runtime, self.dispatcher = runtime, dispatcher

    async def respond_to_attack(self, message, history):
        inventory = self.runtime.request("/mcp", {"method": "tools/list"})
        content, _ = self.runtime.chat(self.runtime.options.get("analysis_model") or self.runtime.options["evaluation_model"], [
            {"role": "system", "content": "Translate the test into one MCP tool call. Return only JSON with tool_name and arguments, matching the provided schema."},
            {"role": "user", "content": json.dumps({"tools": inventory, "test": message, "history": history}, ensure_ascii=False)}])
        call = json.loads(content.removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        return await self.dispatcher.call_tool("call_mcp_tool", call)


async def run_redteam(runtime, dispatcher, prompt):
    from mcp_scan.redteam.orchestrator import RedTeamOrchestrator
    from mcp_scan.redteam.attacker import AttackerAgent
    from mcp_scan.redteam.evaluator import EvaluatorAgent
    options = runtime.options
    client = AsyncRoleClient(runtime)
    orchestrator = RedTeamOrchestrator(api_key=runtime.config["claim"]["lease_token"],
        base_url=runtime.config["task_url"] + "/evaluator/v1", model=options["evaluation_model"])
    orchestrator._attacker = AttackerAgent(client, options.get("attack_model") or options["evaluation_model"])
    orchestrator._evaluator = EvaluatorAgent(client, options["evaluation_model"])
    orchestrator._target = LiveMcpTarget(runtime, dispatcher)
    model_rounds = int((runtime.config["claim"].get("policy") or {}).get("max_rounds", 60)) - runtime.usage.get("rounds", 0)
    call_budget = min(options["mcp_call_limit"], model_rounds // 3)
    if call_budget < 1:
        raise ExecutionStopped("mcp_rounds_limit_reached")
    if options["mcp_strategy"] == "crescendo":
        raw = await orchestrator.run_crescendo(prompt, max_total_rounds=min(call_budget, 20))
        raw.pop("history", None)
    else:
        branches = min(2, call_budget)
        raw = await orchestrator.run_tap(prompt, branch_factor=branches, top_k=1, max_depth=min(5, call_budget // branches))
        raw = {"strategy": "tap", "best_score": raw["best_score"], "success": bool(raw["success_nodes"]),
               "nodes": [{"node_id": n.node_id, "score": n.score, "is_successful": n.is_successful,
                          "attack_message": n.turn.attack_message, "target_response": n.turn.target_response}
                         for n in raw["all_nodes"]]}
    if not any(c["status"] == "succeeded" for c in runtime.calls):
        raise ValueError("mcp_no_successful_tool_calls")
    results = [{"title": "MCP red-team risk signal", "level": "medium",
                "description": "The evaluator identified an attack success signal. Review the captured tool calls to confirm impact."}] if raw.get("success") else []
    return {"readme": prompt, "results": results, "redteam": raw, "score": None}


async def execute_child(config, folder):
    from mcp_scan.agent.agent import Agent
    from mcp_scan.utils.sarif_formatter import to_sarif
    from mcp_scan.utils.loging import logger
    logger.remove()
    logging.disable(logging.CRITICAL)
    runtime = TaskRuntime(config, folder)
    options = runtime.options
    source = Path(folder) / "source"
    source.mkdir()
    if options["mcp_mode"] == "source":
        bundle = runtime.request("/mcp/source", {})
        digest = hashlib.sha256(json.dumps(bundle["files"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest != options["mcp_source_sha256"]:
            raise ValueError("mcp_source_hash_mismatch")
        for item in bundle["files"]:
            if item["content"] is None:
                continue
            path = (source / item["path"]).resolve()
            if not path.is_relative_to(source.resolve()) or path == source.resolve():
                raise ValueError("mcp_source_path_invalid")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["content"], encoding="utf-8")
            path.chmod(0o400)
    llm = RoleLLM(runtime, options.get("analysis_model") or options["evaluation_model"])
    agent = Agent(llm, language=options.get("language", "zh"), aig_mode=options.get("mcp_depth") == "full")
    agent.dispatcher = BoundedDispatcher(runtime, source)
    for method in ("execute_stage", "execute_stage_dynamic"):
        original = getattr(agent.pipeline, method)
        async def stage_wrapper(stage, *args, _original=original, **kwargs):
            runtime.stage(stage.stage_id, "running")
            is_review = stage.template in {"agents/vuln_review", "agents/dynamic/general_analyzing_prompt_template"}
            agent.llm = RoleLLM(runtime, options["evaluation_model"] if is_review else options.get("analysis_model") or options["evaluation_model"])
            stage_result = await _original(stage, *args, **kwargs)
            if stage.output_check_fn and not stage.output_check_fn(stage_result):
                raise ValueError("mcp_review_output_invalid")
            runtime.stage(stage.stage_id, "passed")
            return stage_result
        setattr(agent.pipeline, method, stage_wrapper)
    prompt = options.get("prompt") or "Audit the authorized MCP target and report evidence for each risk."
    if options["mcp_mode"] == "source":
        report = await agent.scan(str(source), prompt, language=options.get("language", "zh"))
    elif options["mcp_mode"] == "dynamic":
        report = await agent.dynamic_analysis(prompt)
        if not any(c["status"] == "succeeded" for c in runtime.calls):
            raise ValueError("mcp_no_successful_tool_calls")
    elif options["mcp_mode"] == "redteam":
        report = await run_redteam(runtime, agent.dispatcher, prompt)
    else:
        raise ValueError("mcp_mode_not_supported")
    report["scan_mode"] = options["mcp_mode"]
    if options["mcp_mode"] == "source":
        text_files = [item for item in bundle["files"] if item["content"] is not None]
        fully_read = [item["path"] for item in text_files if item["path"] in agent.dispatcher.read_lines
                      and len(agent.dispatcher.read_lines[item["path"]]) == len(item["content"].splitlines())]
        report["source"] = {"sha256": bundle["sha256"], "revision": bundle.get("revision"),
            "fully_read_files": fully_read, "text_file_count": len(text_files),
            "omitted_binary_files": [{"path": item["path"], "sha256": item["sha256"]} for item in bundle["files"] if item["content"] is None]}
        report["coverage_complete"] = len(fully_read) == len(text_files)
    else:
        successful_tools = {c["tool_name"] for c in runtime.calls if c["status"] == "succeeded"}
        report["coverage_complete"] = set(options.get("mcp_tools", [])) <= successful_tools
        report["untested_tools"] = sorted(set(options.get("mcp_tools", [])) - successful_tools)
    report["calls"] = runtime.calls
    report["stages"] = agent.pipeline.results
    write_json(Path(folder) / "result.json", {"report": report, "sarif": to_sarif(report), "usage": runtime.usage})


def execute_mcp_aig_scan(claim, heartbeat, evaluator, *, initial_usage):
    task_url = evaluator.base_url.removesuffix("/evaluator/v1")
    with tempfile.TemporaryDirectory(prefix="mcp-task-") as folder:
        config = {"claim": claim, "usage": initial_usage, "task_url": task_url,
                  "rates": {"input": evaluator.input_cost_microunits_per_million, "output": evaluator.output_cost_microunits_per_million}}
        write_json(Path(folder) / "config.json", config)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), folder],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, cwd=folder)
        usage = dict(initial_usage)
        try:
            while True:
                usage_file = Path(folder) / "usage.json"
                if usage_file.exists():
                    usage = json.loads(usage_file.read_text())
                progress_file = Path(folder) / "progress.json"
                diagnostics_file = Path(folder) / "diagnostics.json"
                if diagnostics_file.exists():
                    claim["diagnostics"] = json.loads(diagnostics_file.read_text())
                if progress_file.exists():
                    claim["mcp_progress"] = json.loads(progress_file.read_text())
                status = heartbeat(usage)
                if not status.get("continue_allowed"):
                    raise ScanStopped(status.get("stop_reason") or "scan_stopped")
                try:
                    process.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                logging.getLogger(__name__).warning("MCP scan child exited: returncode=%s", process.returncode)
                error_file = Path(folder) / "error.json"
                code = json.loads(error_file.read_text())["code"] if error_file.exists() else "mcp_scan.engine_terminated"
                events = json.loads(diagnostics_file.read_text()) if diagnostics_file.exists() else []
                error_details = json.loads(error_file.read_text()) if error_file.exists() else {}
                events.append({"event": "engine_exited", "operation": "engine", "elapsed_ms": events[-1]["elapsed_ms"] if events else 0,
                               "returncode": process.returncode, **{k: error_details[k] for k in ("error_type", "source_file", "source_line") if k in error_details}})
                claim["diagnostics"] = events[-500:]
                if usage_file.exists():
                    usage = json.loads(usage_file.read_text())
                heartbeat(usage)
                raise McpExecutionError(code)
            result = json.loads((Path(folder) / "result.json").read_text())
            if diagnostics_file.exists():
                claim["diagnostics"] = json.loads(diagnostics_file.read_text())
            status = heartbeat(result["usage"])
            if not status.get("continue_allowed"):
                raise ScanStopped(status.get("stop_reason") or "scan_stopped")
            return normalize_result(claim, result)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def normalize_result(claim, result):
    from mcp_adapter import AIG_COMMIT, AIG_TAG
    report = result["report"]
    from agent_manager.security_redaction import redact_sensitive_value
    report = redact_sensitive_value(report)
    mode = report["scan_mode"]
    coverage_complete = report.get("coverage_complete", False)
    findings = []
    for index, item in enumerate(report.get("results", [])):
        findings.append({"case_external_id": "mcp-aig", "finding_code": "mcp_model_risk_signal",
            "severity": str(item.get("level", "medium")).lower() if str(item.get("level", "medium")).lower() in {"info", "low", "medium", "high", "critical"} else "medium",
            "title": str(item.get("title") or item.get("risk_type") or "MCP risk signal")[:255],
            "description": str(item.get("description") or item.get("desc") or item)[:16384], "confidence": 0.5, "source": "ai-infra-guard-mcp",
            "evidence": {"model_assessment": True, "confirmed_vulnerability": False, "result_index": index,
                "tool_call_ids": [c["call_id"] for c in report["calls"]], "risk_type": item.get("risk_type"),
                "file": item.get("file"), "line_start": item.get("line_start"), "line_end": item.get("line_end"),
                "remediation": [{"action": "review_evidence", "execution": "suggestion_only",
                    "message": str(item.get("suggestion") or "Review the source and captured tool evidence.")[:16384]}]}})
    artifacts = []
    for name, payload in (("mcp-aig-report", report), ("mcp-sarif-report", redact_sensitive_value(result["sarif"]))):
        content = json.dumps(payload, ensure_ascii=False, default=str)
        artifacts.append({"artifact_type": name, "uri": f"artifact://{claim['task']['task_id']}/{name}.json",
            "sha256": hashlib.sha256(content.encode()).hexdigest(), "size_bytes": len(content.encode()),
            "redacted": True, "content": content, "metadata": {"scan_mode": mode, "upstream_commit": AIG_COMMIT}})
    return {"status": "succeeded", "usage": result["usage"], "findings": findings,
        "cases": [{"external_case_id": "mcp-aig", "category": "mcp_" + mode, "title": "MCP risk scan",
            "status": "failed" if findings else "passed" if coverage_complete else "unverified", "round_count": result["usage"]["rounds"],
            "request_summary": {"scan_mode": mode}, "response_summary": {"scan_mode": mode,
                "execution_status": "completed", "coverage_complete": coverage_complete,
                "assessment_status": "risk_signal_detected" if findings else "no_risk_observed" if coverage_complete else "unverified",
                "tool_calls_performed": len(report["calls"])}}],
        "artifacts": artifacts, "engine_name": "ai-infra-guard-mcp-scan", "engine_version": f"{AIG_TAG}+{AIG_COMMIT[:12]}"}


if __name__ == "__main__":
    task_folder = sys.argv[1]
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    try:
        asyncio.run(execute_child(json.loads((Path(task_folder) / "config.json").read_text()), task_folder))
    except (ExecutionStopped, Exception) as error:
        allowed = {"mcp_no_successful_tool_calls", "mcp_review_output_invalid", "mcp_source_hash_mismatch", "mcp_source_path_invalid", "mcp_model_empty_response",
                   "mcp_rounds_limit_reached", "mcp_tokens_limit_reached", "mcp_response_bytes_limit_reached", "mcp_gateway_approval_required"}
        code = "mcp_scan." + str(error).removeprefix("mcp_") if str(error) in allowed else "mcp_scan.execution_denied" if isinstance(error, ExecutionStopped) else "mcp_scan.engine_failed"
        frames = traceback.extract_tb(error.__traceback__)
        location = {"source_file": Path(frames[-1].filename).name, "source_line": frames[-1].lineno} if frames else {}
        write_json(Path(task_folder) / "error.json", {"code": code, "error_type": type(error).__name__, **location})
        sys.exit(1)
