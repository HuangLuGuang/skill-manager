"""
FastAPI router for the agent manager API.

Provides endpoints for CI/CD pipelines, agent runtimes, and review UIs.
"""

from __future__ import annotations

import atexit
import difflib
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from agent_manager.api.import_work import import_endpoint, run_import_work
from backend.api_errors import ApiError
from agent_manager.api.upload_progress import stream_upload_progress

from agent_manager.core.deep_scan_display import with_deep_scan_analysis_display
from agent_manager.core.llm import LLMConfig
from agent_manager.core.manager import AgentManager, findings_summary_from_report
from agent_manager.core.models import RegistryEntry, SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.policy_simulation import PolicySimulationRequest, simulate_policy
from agent_manager.core.prompt_models import PromptStatus
from agent_manager.core.sandbox import (
    SandboxConfig,
    SandboxConnectionTest,
    sandbox_url_error,
    test_sandbox_connection,
    with_sandbox_reason_metadata,
)
from agent_manager.core.scan_report_pdf import build_scan_report_pdf
from agent_manager.core.skillspector import get_suppressed_findings, is_skillspector_available
from agent_manager.core.text_reader import read_text_fallback
from agent_manager.core.vetting import _load_manifest
from agent_manager.core.upload_jobs import UploadImportJobs
from agent_manager.core.import_results import resolve_import_result

router = APIRouter(tags=["agent-manager"])
runtime_router = APIRouter(tags=["agent-manager-runtime"])

# Module-level singleton (overridable in tests via dependency injection)
_manager: AgentManager | None = None
_upload_jobs: dict[Path, UploadImportJobs] = {}
_upload_jobs_lock = threading.Lock()
# Admission must finish deduplication and create the pending scan before a
# concurrent import resolves the same content. This lock never guards API reads.
_submission_lock = threading.Lock()


def _get_upload_jobs(mgr):
    root = mgr.registry.data_dir
    with _upload_jobs_lock:
        if root not in _upload_jobs:
            def process_item(payload, raw_path):
                body = RemoteImportSubmitRequest(**payload)
                skill_dir = Path(raw_path).resolve()
                session_root = root / "upload_import_sessions" / body.session_id
                if not _is_within_root(skill_dir, session_root):
                    raise ValueError("Path is outside upload import session")
                result = _submit_directory_for_processing(
                    mgr, BackgroundTasks(), skill_dir,
                    SourceInfo(origin=SkillOrigin(body.origin), author=body.author, channel="upload_zip"),
                    body.use_behavioral, body.use_llm, body.use_sandbox, body.use_skillspector, body.judgement_mode,
                )
                return result.model_dump(mode="json")
            _upload_jobs[root] = UploadImportJobs(root, process_item)
        return _upload_jobs[root]


def _shutdown_upload_jobs():
    for queue in list(_upload_jobs.values()):
        queue.close()


def _legacy_runtime_endpoint_removed() -> None:
    raise HTTPException(
        status_code=410,
        detail="旧 Runtime 接口已停用，请使用带 Agent 运行凭证的 /api/v1/access/runtime/... 接口",
    )


def _scan_worker_count() -> int:
    try:
        return max(1, int(os.environ.get("AGENT_MANAGER_SCAN_WORKERS", "2")))
    except ValueError:
        return 2


_scan_executor = ThreadPoolExecutor(
    max_workers=_scan_worker_count(),
    thread_name_prefix="agent-manager-scan",
)


def _shutdown_scan_executor() -> None:
    _scan_executor.shutdown(wait=True, cancel_futures=False)


atexit.register(_shutdown_scan_executor)
atexit.register(_shutdown_upload_jobs)


def _discover_policy_path() -> Path | None:
    for candidate in (Path("company-policy.yaml"), Path.home() / ".agent-manager" / "policy.yaml"):
        if candidate.exists():
            return candidate.resolve()
    return None


def get_manager() -> AgentManager:
    global _manager
    if _manager is None:
        policy_path = _discover_policy_path()
        policy = CompanyPolicy.load(policy_path) if policy_path else CompanyPolicy.default()
        _manager = AgentManager(policy=policy)
    _get_upload_jobs(_manager)
    return _manager


def _policy_path_for_write() -> Path:
    existing = _discover_policy_path()
    if existing:
        return existing
    target = Path.home() / ".agent-manager" / "policy.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_skill_root(extract_dir: Path) -> Path:
    if (extract_dir / "SKILL.md").exists():
        return extract_dir

    matches = sorted(path.parent for path in extract_dir.rglob("SKILL.md"))
    unique_matches: list[Path] = []
    seen: set[str] = set()
    for path in matches:
        key = str(path.resolve())
        if key not in seen:
            unique_matches.append(path)
            seen.add(key)

    if len(unique_matches) == 1:
        return unique_matches[0]

    if not unique_matches:
        raise HTTPException(status_code=400, detail="SKILL.md not found in uploaded ZIP")

    raise HTTPException(
        status_code=400,
        detail="Multiple SKILL.md files found in uploaded ZIP; package must contain exactly one skill",
    )


def _safe_extract_zip(zip_path: Path, extract_dir: Path, *, skipped_symlinks: list[str] | None = None, archive_prefix: str = "", progress=None, budget=None) -> None:
    extract_root = extract_dir.resolve()
    budget = budget if budget is not None else {"files": 0, "bytes": 0}
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.infolist()
        for index, info in enumerate(entries):
            if progress:
                progress("extracting", index, len(entries))
            name = info.filename
            if ".." in name or name.startswith("/"):
                raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {name}")
            if not info.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("utf-8")
                except UnicodeError:
                    pass
            if stat.S_ISLNK(info.external_attr >> 16):
                if skipped_symlinks is not None:
                    skipped_symlinks.append(f"{archive_prefix}{name}")
                    continue
                raise HTTPException(status_code=400, detail=f"Symlinks are not allowed in ZIP: {name}")
            if not info.is_dir():
                budget["files"] += 1
                budget["bytes"] += info.file_size
                if budget["files"] > 50000 or budget["bytes"] > 1024 ** 3 or info.file_size > 100 * 1024 ** 2:
                    raise HTTPException(status_code=413, detail="Archive extraction limits exceeded")
            target = (extract_root / name).resolve()
            try:
                target.relative_to(extract_root)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if progress:
            progress("extracting", len(entries), len(entries))


def _extract_zip_with_nested_archives(zip_path: Path, extract_dir: Path, *, skipped_symlinks: list[str] | None = None, progress=None) -> None:
    budget = {"files": 0, "bytes": 0}
    _safe_extract_zip(zip_path, extract_dir, skipped_symlinks=skipped_symlinks, progress=progress, budget=budget)
    nested_archives = sorted(path for path in extract_dir.rglob("*.zip") if path.is_file())
    for nested_zip in nested_archives:
        if not zipfile.is_zipfile(nested_zip):
            continue
        nested_target = nested_zip.with_suffix("")
        nested_target.mkdir(parents=True, exist_ok=True)
        _safe_extract_zip(nested_zip, nested_target, skipped_symlinks=skipped_symlinks, archive_prefix=f"{nested_zip.relative_to(extract_dir).as_posix()}!/", progress=progress, budget=budget)


def _import_root() -> Path:
    raw = os.environ.get("AGENT_MANAGER_IMPORT_ROOT") or os.environ.get("OPENCLOW_SKILLS_ROOT")
    target = Path(raw).expanduser() if raw else (Path.home() / ".openclaw" / "workspace" / "skills")
    return target.resolve()


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _collect_import_candidates(root: Path, progress=None) -> list[dict[str, str]]:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        return []
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    if progress:
        progress("discovering", 0, 0)
    manifests = sorted(root.rglob("SKILL.md"))
    for index, manifest in enumerate(manifests):
        if progress:
            progress("identifying", index, len(manifests))
        skill_dir = manifest.parent.resolve()
        key = str(skill_dir)
        if key in seen:
            continue
        seen.add(key)
        rel = skill_dir.relative_to(root).as_posix()
        try:
            name, description, _allowed_tools, _license = _load_manifest(skill_dir)
        except ValueError as exc:
            candidates.append({
                "name": skill_dir.name,
                "path": str(skill_dir),
                "relative_path": rel,
                "description": "",
                "error": str(exc),
            })
            continue
        candidates.append({
            "name": name,
            "path": str(skill_dir),
            "relative_path": rel,
            "description": description,
            "error": "",
        })
    if progress:
        progress("identifying", len(manifests), len(manifests))
    return candidates


def _normalize_download_url(url: str) -> tuple[str, str]:
    raw = url.strip()
    github_match = re.match(r"^https://github\.com/([^/]+)/([^/]+)(?:/tree/([^/?#]+))?/?(?:[?#].*)?$", raw)
    if github_match:
        owner, repo, branch = github_match.groups()
        repo = repo.removesuffix(".git")
        ref = branch or "main"
        return f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref}.zip", "github"

    github_archive_match = re.match(
        r"^https://github\.com/([^/]+)/([^/]+)/archive/refs/(heads|tags)/([^/?#]+)\.zip(?:[?#].*)?$",
        raw,
    )
    if github_archive_match:
        return raw, "github"

    return raw, "direct"


def _extract_zip_link_from_html(base_url: str, html: str) -> str | None:
    patterns = [
        re.compile(r'href=["\']([^"\']+\.zip(?:\?[^"\']*)?)["\']', re.I),
        re.compile(r'data-download-url=["\']([^"\']+)["\']', re.I),
        re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*Download\s+zip\s*</a>', re.I),
        re.compile(r'href=["\']([^"\']+/api/v\d+/download[^"\']*)["\']', re.I),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            return httpx.URL(base_url).join(match.group(1)).__str__()
    return None


def _normalize_clawhub_origin_url(url: str) -> str:
    return url.strip()


CANCELLED_SKILL_REASON = "用户取消后台分析任务"


def _process_pending_submission_task(
    mgr: AgentManager,
    skill_id: str,
    use_behavioral: bool,
    use_llm: bool,
    use_sandbox: bool,
    use_skillspector: bool,
    force_scan: bool = False,
    judgement_mode: str | None = None,
) -> None:
    try:
        mgr.process_pending_submission(
            skill_id,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            force_scan=force_scan,
            judgement_mode=judgement_mode,
        )
    except Exception as exc:
        mgr.mark_submission_failed(skill_id, f"后台分析失败: {exc}")
    finally:
        from backend.client_task_notifications import notify_all
        notify_all()


def _submit_directory_for_processing(
    mgr: AgentManager,
    background_tasks: BackgroundTasks,
    skill_dir: Path,
    source: SourceInfo,
    use_behavioral: bool,
    use_llm: bool,
    use_sandbox: bool,
    use_skillspector: bool,
    judgement_mode: str | None = None,
    entry_prepared: Callable[[RegistryEntry], None] | None = None,
) -> SubmitResponse:
    with _submission_lock:
        entry, should_process, resolution = mgr.prepare_submission(
            skill_dir,
            source=source,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            judgement_mode=judgement_mode,
        )
    if entry_prepared is not None:
        entry_prepared(entry)
    runs = mgr.list_scan_runs(entry.skill_id)
    scan_run = next((run for run in runs if run.status == "PENDING"), runs[0] if runs else None) if resolution != "existing_version_reused" else None
    if should_process:
        _scan_executor.submit(
            _process_pending_submission_task,
            mgr,
            entry.skill_id,
            use_behavioral,
            use_llm,
            use_sandbox,
            use_skillspector,
            False,
            judgement_mode,
        )
    if Path(entry.skill_path or "").resolve() != skill_dir.resolve():
        generated_roots = {
            (mgr.registry.data_dir / name).resolve()
            for name in (
                "uploaded_skills",
                "downloaded_skills",
                "clawhub_skills",
                "scanner_uploaded_skills",
            )
        }
        if any(root in skill_dir.resolve().parents for root in generated_roots):
            shutil.rmtree(skill_dir, ignore_errors=True)
    messages = {
        "new_version": "已创建新版本，后台分析中。",
        "existing_version_rescan": "检测上下文已变化，正在重新检测现有版本。",
        "scan_in_progress": "相同内容版本正在检测，已复用现有任务。",
        "existing_version_reused": "相同内容和检测配置已存在，已复用可信检测结果。",
    }
    return SubmitResponse(
        skill_id=entry.family_id or entry.skill_id,
        version_id=entry.skill_id,
        version_no=entry.version_no,
        source_version=entry.source_version,
        deduplicated=resolution != "new_version",
        scan_reused=resolution == "existing_version_reused",
        scan_run_id=scan_run.scan_run_id if scan_run else None,
        scan_state="PENDING" if scan_run else "REUSED" if resolution == "existing_version_reused" else None,
        name=entry.name,
        status="PENDING" if scan_run else entry.status.value,
        risk_level=entry.risk_level.value if entry.risk_level and not scan_run else None,
        findings_count=entry.vetting.findings_count if entry.vetting and not scan_run else 0,
        sandbox_triggered=entry.vetting.sandbox_triggered if entry.vetting and not scan_run else False,
        sandbox_required_by_policy=entry.vetting.sandbox_required_by_policy if entry.vetting and not scan_run else False,
        sandbox_runtime=entry.vetting.sandbox_runtime if entry.vetting and not scan_run else None,
        message=messages[resolution],
    )


async def _download_remote_archive(url: str, tmp_dir: Path) -> tuple[Path, str]:
    download_path = tmp_dir / "downloaded-skill.zip"
    normalized_url, detected_origin = _normalize_download_url(url)
    timeout = httpx.Timeout(60.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(normalized_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if ".zip" not in normalized_url.lower() and "zip" not in content_type.lower():
            guessed = mimetypes.guess_type(normalized_url)[0] or ""
            if "zip" not in guessed.lower():
                raise HTTPException(status_code=400, detail="Only ZIP downloads are currently supported")
        await run_import_work(download_path.write_bytes, response.content)
    return download_path, detected_origin


# --------------------------------------------------------------------------- #
# Request / Response schemas                                                    #
# --------------------------------------------------------------------------- #

class SubmitResponse(BaseModel):
    skill_id: str
    version_id: str
    version_no: int
    source_version: str | None = None
    deduplicated: bool = False
    scan_reused: bool = False
    scan_run_id: str | None = None
    scan_state: str | None = None
    outcome: str | None = None
    name: str
    status: str
    risk_level: str | None
    findings_count: int
    sandbox_triggered: bool = False
    sandbox_required_by_policy: bool = False
    sandbox_runtime: str | None = None
    message: str


class BatchSubmitResponse(BaseModel):
    results: list[SubmitResponse]
    skipped_symlinks: list[str] = Field(default_factory=list)


class LocalImportCandidate(BaseModel):
    name: str
    path: str
    relative_path: str
    description: str = ""
    error: str = ""


class LocalImportCandidatesResponse(BaseModel):
    root_path: str
    count: int
    items: list[LocalImportCandidate]


class LocalImportSubmitRequest(BaseModel):
    paths: list[str]
    author: str | None = None
    origin: str = "local"
    use_behavioral: bool = False
    use_llm: bool = False
    use_sandbox: bool = False
    use_skillspector: bool = False
    judgement_mode: str | None = None


class UrlSubmitRequest(BaseModel):
    url: str
    author: str | None = None
    origin: str = "github"
    use_behavioral: bool = False
    use_llm: bool = False
    use_sandbox: bool = False
    use_skillspector: bool = False
    judgement_mode: str | None = None


class RemoteImportPrepareRequest(BaseModel):
    url: str
    author: str | None = None
    origin: str = "unknown"


class RemoteImportPrepareResponse(BaseModel):
    session_id: str
    source_url: str
    detected_origin: str
    root_path: str
    count: int
    items: list[LocalImportCandidate]


class RemoteImportSubmitRequest(BaseModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    paths: list[str]
    author: str | None = None
    origin: str = "unknown"
    use_behavioral: bool = False
    use_llm: bool = False
    use_sandbox: bool = False
    use_skillspector: bool = False
    judgement_mode: str | None = None


class UploadZipPrepareResponse(BaseModel):
    session_id: str
    filename: str
    root_path: str
    count: int
    items: list[LocalImportCandidate]
    requires_symlink_confirmation: bool = False
    skipped_symlinks: list[str] = Field(default_factory=list)


class UploadZipConfirmationRequest(BaseModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    confirmed: bool


class ClawHubSubmitRequest(BaseModel):
    url: str
    author: str | None = None
    version: str | None = None
    token: str | None = None
    use_behavioral: bool = False
    use_llm: bool = False
    use_sandbox: bool = False
    use_skillspector: bool = False
    judgement_mode: str | None = None


# 审核文本按 Unicode 字符计数，写入前限制大小，不改写已有记录。
REVIEW_TEXT_MAX_LENGTH = 1000


class ApproveRequest(BaseModel):
    approver: str
    note: str | None = None


class RejectRequest(BaseModel):
    reviewer: str
    reason: str


class CancelScanRequest(BaseModel):
    reviewer: str


class RetireRequest(BaseModel):
    reason: str
    actor: str | None = None


class RuntimeCheckResponse(BaseModel):
    allowed: bool
    reason: str
    status: str | None = None
    risk_level: str | None = None


class ToolCheckResponse(BaseModel):
    allowed: bool
    skill_name: str
    tool_name: str


class VerifySkillSignatureRequest(BaseModel):
    skill_name: str | None = None
    local_signature: str
    skill_id: str | None = None
    agent_id: str | None = None


class VerifySkillSignatureResponse(BaseModel):
    allowed: bool
    reason: str
    skill_id: str | None = None
    skill_name: str
    status: str | None = None
    risk_level: str | None = None
    signature_match: bool


# 只约束配置写入边界，旧 YAML 继续按原模型读取，避免升级后无法启动。
_ADVANCED_INTEGER_LIMITS = {
    "llm": {"timeout_seconds": (5, 180), "max_files": (1, 20),
            "max_manifest_chars": (2000, 50000), "max_file_chars": (500, 20000)},
    "sandbox": {"timeout_seconds": (1, 300), "pids_limit": (1, 1024)},
    "policy": {},
}
_ADVANCED_FIELD_NAMES = {
    "timeout_seconds": ("超时（秒）", "Timeout (seconds)"),
    "max_files": ("最多读取文件数", "Maximum files to read"),
    "max_manifest_chars": ("Skill 描述字符上限", "Skill description character limit"),
    "max_file_chars": ("单文件字符上限", "Character limit per file"),
    "pids_limit": ("进程数上限", "Process limit"),
    "cpu_limit": ("CPU 配额（核）", "CPU quota (cores)"),
    "memory_limit": ("内存上限", "Memory limit"),
    "runtime": ("运行方式", "Runtime"), "network_mode": ("网络访问", "Network access"),
    "image": ("运行镜像", "Runtime image"), "model": ("分析模型", "Analysis model"),
    "remote_url": ("远程服务地址", "Remote service URL"),
    "remote_api_key": ("远程 API Key", "Remote API key"),
    "clear_remote_api_key": ("清除远程 API Key", "Clear remote API key"),
    "enabled": ("启用状态", "Enabled"),
    "read_only_rootfs": ("根文件系统只读", "Read-only root filesystem"),
    "scan_result_reuse_enabled": ("检测结果复用", "Reuse scan results"),
}


def _validate_service_config(values: dict, group: str) -> dict:
    """Validate raw write inputs and return safe field errors without credentials."""
    # JSON 配置必须为对象，避免数组被转换为配置或标量触发 500。
    if not isinstance(values, dict):
        raise ApiError(
            422, "request.validation_failed",
            "配置请求必须是 JSON 对象。", "Configuration must be a JSON object.",
        )
    data = dict(values)
    errors = []

    def issue(field, code, zh, en, **params):
        names = _ADVANCED_FIELD_NAMES[field]
        errors.append({"field": field, "code": code, "params": params,
                       "zh": f"{names[0]}：{zh}", "en": f"{names[1]}: {en}"})

    if group == "sandbox":
        runtime = data.get("runtime", "remote")
        # 非当前运行方式的字段既不校验，也不覆盖保存的另一种运行配置。
        inactive = ("remote_url", "remote_api_key", "clear_remote_api_key") if runtime == "docker" else (
            "image", "memory_limit", "cpu_limit", "pids_limit", "read_only_rootfs")
        for field in inactive:
            data.pop(field, None)
        for field, allowed in (("runtime", ("remote", "docker")), ("network_mode", ("none", "bridge"))):
            if field in data and data[field] not in allowed:
                issue(field, "config.choice", "请选择有效选项。", "Select a valid option.")
        if runtime == "remote":
            value = data.get("remote_url", "http://sandbox:8194")
            code = sandbox_url_error(value) if isinstance(value, (str, type(None))) else "sandbox.url_invalid"
            if code:
                issue("remote_url", code, "请输入最多 2048 字符的 HTTP/HTTPS 基础地址。", "Enter an HTTP/HTTPS base URL of at most 2048 characters.")
            key = data.get("remote_api_key")
            if key is not None and (not isinstance(key, str) or len(key) > 4096 or re.search(r"[\s\x00-\x1f\x7f]", key)):
                issue("remote_api_key", "config.key", "最多 4096 字符，不含空白或控制字符。", "Use at most 4096 characters without whitespace or control characters.")
            if key and data.get("clear_remote_api_key") is True:
                issue("remote_api_key", "config.key_conflict", "新密钥与清除操作不能同时选择。", "A new key and clearing the key cannot be selected together.")
        if runtime == "docker":
            image = data.get("image", "agent-manager-sandbox-runtime:latest")
            # 镜像名兼容 registry:port、tag 和 sha256 digest。
            component = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
            image_pattern = rf"(?:(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]+)?/)?{component}(?:/{component})*(?::[\w][\w.-]{{0,127}})?(?:@sha256:[0-9a-fA-F]{{64}})?"
            if not isinstance(image, str) or len(image) > 255 or not re.fullmatch(image_pattern, image, re.ASCII):
                issue("image", "config.image", "请输入最多 255 字符的有效 Docker 镜像引用。", "Enter a valid Docker image reference of at most 255 characters.")
            cpu = data.get("cpu_limit", "1.0")
            if not isinstance(cpu, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", cpu) or not 0.01 <= float(cpu) <= 64:
                issue("cpu_limit", "config.cpu", "请输入 0.01–64 的十进制数，最多两位小数。", "Enter a decimal number from 0.01 to 64 with at most two decimal places.")
            memory = data.get("memory_limit", "256m")
            match = re.fullmatch(r"([0-9]+)([bkmg])", memory, re.I) if isinstance(memory, str) else None
            size = int(match[1]) * 1024 ** "bkmg".index(match[2].lower()) if match and len(match[1]) <= 16 else 0
            if not 6 * 1024 ** 2 <= size <= 64 * 1024 ** 3:
                issue("memory_limit", "config.memory", "请输入正整数及 b/k/m/g 单位，范围 6 MiB–64 GiB。", "Enter a positive integer with b/k/m/g units, from 6 MiB to 64 GiB.")
    for field, (minimum, maximum) in _ADVANCED_INTEGER_LIMITS[group].items():
        if field in data and (type(data[field]) is not int or not minimum <= data[field] <= maximum):
            issue(field, "config.integer", f"请输入 {minimum}–{maximum} 的正整数。", f"Enter a positive integer from {minimum} to {maximum}.", min=minimum, max=maximum)
    bool_fields = {"llm": ("enabled",), "sandbox": ("enabled", "read_only_rootfs", "clear_remote_api_key"), "policy": ("scan_result_reuse_enabled",)}
    for field in bool_fields[group]:
        if field in data and type(data[field]) is not bool:
            issue(field, "config.boolean", "请选择开启或关闭。", "Select on or off.")
    if group == "llm" and data.get("enabled") is True and not data.get("model", "deepseek-chat"):
        issue("model", "config.required", "请选择分析模型。", "Select an analysis model.")
    if errors:
        first = errors[0]
        raise ApiError(422, first["code"], "；".join(e["zh"] for e in errors), "; ".join(e["en"] for e in errors),
                       params={"group": group, "errors": [{k: e[k] for k in ("field", "code", "params")} for e in errors]})
    return data


class PolicyPayload(BaseModel):
    scan_result_reuse_enabled: bool = True
    auto_approve_max_risk: str
    auto_approve_risk: list[str] = Field(default_factory=lambda: ["benign"])
    require_human_review: list[str]
    auto_reject_risk: list[str]
    require_sandbox_for_risk: list[str]
    blocked_permissions: list[str]
    trusted_authors: list[str]
    allowed_tools_allowlist: list[str]
    max_allowed_tools: int
    require_license: bool
    accepted_licenses: list[str]
    scanner_policy: str
    judgement_mode: str = "balanced"
    risk_classification: dict[str, str] = Field(default_factory=dict)
    skillspector_enabled: bool = False
    skillspector_fail_open: bool = True
    skillspector_timeout_seconds: int = 120
    skillspector_min_blocking_severity: str = "HIGH"
    skillspector_use_llm: bool = False


    @model_validator(mode="before")
    @classmethod
    def validate_write(cls, values):
        return _validate_service_config(values, "policy")


class PolicyResponse(BaseModel):
    policy_path: str | None
    policy: PolicyPayload


class SystemStatusResponse(BaseModel):
    data_dir: str
    policy_path: str | None
    registry_entries: int
    review_queue: int
    signing_key_configured: bool
    scanner_available: bool
    skillspector_enabled: bool
    skillspector_available: bool
    skillspector_version: str | None = None
    sandbox_enabled: bool
    sandbox_available: bool
    sandbox_runtime: str
    sandbox_target: str | None = None
    sandbox_status_message: str | None = None
    hooks_available: bool
    llm_enabled: bool
    llm_provider: str
    llm_api_base: str
    llm_model: str
    llm_api_key_configured: bool
    scan_mode: str
    service: str


class SigningPublicKeyResponse(BaseModel):
    algorithm: str = "Ed25519"
    key_id: str
    public_key: str


class LLMConfigPayload(BaseModel):
    enabled: bool = False
    provider: str = "deepseek"
    api_base: str = "https://api.deepseek.com"
    api_key: str | None = None
    model: str = "deepseek-chat"
    timeout_seconds: int = 30
    max_files: int = 6
    max_file_chars: int = 3000
    max_manifest_chars: int = 12000
    clear_api_key: bool = False


    @model_validator(mode="before")
    @classmethod
    def validate_write(cls, values):
        return _validate_service_config(values, "llm")


class LLMConfigResponse(BaseModel):
    config_path: str
    enabled: bool
    provider: str
    api_base: str
    model: str
    timeout_seconds: float
    max_files: int
    max_file_chars: int
    max_manifest_chars: int
    api_key_configured: bool
    api_key_masked: str | None = None


class SandboxConfigPayload(BaseModel):
    enabled: bool = False
    runtime: str = "remote"
    image: str = "agent-manager-sandbox-runtime:latest"
    timeout_seconds: int = 15
    network_mode: str = "none"
    memory_limit: str = "256m"
    cpu_limit: str = "1.0"
    pids_limit: int = 64
    read_only_rootfs: bool = True
    remote_url: str | None = "http://sandbox:8194"
    remote_api_key: str | None = None
    clear_remote_api_key: bool = False


    @model_validator(mode="before")
    @classmethod
    def validate_write(cls, values):
        return _validate_service_config(values, "sandbox")


class SandboxConfigResponse(BaseModel):
    config_path: str
    enabled: bool
    runtime: str
    image: str
    timeout_seconds: int
    network_mode: str
    memory_limit: str
    cpu_limit: str
    pids_limit: int
    read_only_rootfs: bool
    remote_url: str | None = None
    remote_api_key_configured: bool
    remote_api_key_masked: str | None = None


class SandboxConnectionTestResponse(BaseModel):
    available: bool
    runtime: str
    target: str | None = None
    message: str
    duration_ms: int | None = None


class SandboxImagesResponse(BaseModel):
    images: list[str]


class VerifySignatureRequest(BaseModel):
    skill_path: str | None = None


class VerifySignatureResponse(BaseModel):
    valid: bool
    skill_id: str
    skill_name: str
    reason: str


class SkillContentResponse(BaseModel):
    skill_id: str
    skill_name: str
    manifest_path: str
    content: str
    encoding: str | None = None


class SkillFileEntry(BaseModel):
    path: str
    size_bytes: int
    modified_at: str


class SkillFilesResponse(BaseModel):
    skill_id: str
    skill_name: str
    skill_path: str
    file_count: int
    files: list[SkillFileEntry]


class SkillFileContentResponse(BaseModel):
    skill_id: str
    skill_name: str
    path: str
    absolute_path: str
    content: str
    encoding: str | None = None


class GovernanceCardResponse(BaseModel):
    skill_id: str
    skill_name: str
    generated_at: str | None = None
    path: str
    content: str


def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    start = max(page - 1, 0) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# --------------------------------------------------------------------------- #
# Health                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/health")
def health():
    return {"status": "ok", "service": "agent-manager"}


@router.get("/policy", response_model=PolicyResponse)
def get_policy(mgr: AgentManager = Depends(get_manager)):
    policy_path = _discover_policy_path()
    return PolicyResponse(
        policy_path=str(policy_path) if policy_path else None,
        policy=PolicyPayload(**{**mgr.policy.to_dict(), "risk_classification": mgr.policy.risk_classification}),
    )


@router.post("/policy/simulate")
def simulate_policy_decision(body: dict[str, Any]):
    try:
        request = PolicySimulationRequest.model_validate(body)
    except ValidationError:
        return JSONResponse(status_code=422, content={
            "error_code": "policy.simulation_invalid",
            "detail": "模拟参数无效，请检查分析器状态、发现项和策略配置。",
        })
    return simulate_policy(request)


@router.get("/llm-config", response_model=LLMConfigResponse)
def get_llm_config():
    config = LLMConfig.load()
    public = config.public_dict()
    return LLMConfigResponse(**public)


@router.put("/llm-config", response_model=LLMConfigResponse)
def update_llm_config(body: LLMConfigPayload):
    current = LLMConfig.load()
    data = body.model_dump()
    clear_api_key = data.pop("clear_api_key", False)
    incoming_api_key = data.pop("api_key", None)
    merged = {**current.model_dump(), **data}
    if clear_api_key:
        merged["api_key"] = None
    elif incoming_api_key:
        merged["api_key"] = incoming_api_key
    else:
        merged["api_key"] = current.api_key

    config = LLMConfig.model_validate(merged)
    path = config.save()
    public = config.public_dict()
    public["config_path"] = str(path)
    return LLMConfigResponse(**public)


@router.get("/sandbox-config", response_model=SandboxConfigResponse)
def get_sandbox_config():
    config = SandboxConfig.load()
    public = config.public_dict()
    return SandboxConfigResponse(**public)


def _sandbox_config_from_payload(body: SandboxConfigPayload, current: SandboxConfig) -> SandboxConfig:
    data = body.model_dump()
    inactive = ("remote_url", "remote_api_key", "clear_remote_api_key") if body.runtime == "docker" else (
        "image", "memory_limit", "cpu_limit", "pids_limit", "read_only_rootfs")
    for field in inactive:
        data.pop(field, None)
    clear_remote_api_key = data.pop("clear_remote_api_key", False)
    incoming_api_key = data.pop("remote_api_key", None)
    merged = {**current.model_dump(), **data}
    if clear_remote_api_key:
        merged["remote_api_key"] = None
    elif incoming_api_key:
        merged["remote_api_key"] = incoming_api_key
    else:
        merged["remote_api_key"] = current.remote_api_key
    return SandboxConfig.model_validate(merged)


@router.put("/sandbox-config", response_model=SandboxConfigResponse)
def update_sandbox_config(body: SandboxConfigPayload):
    current = SandboxConfig.load()
    config = _sandbox_config_from_payload(body, current)
    path = config.save()
    public = config.public_dict()
    public["config_path"] = str(path)
    return SandboxConfigResponse(**public)


@router.post("/sandbox-config/test", response_model=SandboxConnectionTestResponse)
def test_sandbox_config(body: SandboxConfigPayload):
    current = SandboxConfig.load()
    config = _sandbox_config_from_payload(body, current)
    result = test_sandbox_connection(config, timeout_seconds=3)
    return SandboxConnectionTestResponse(**result.model_dump())


@router.get("/sandbox-images", response_model=SandboxImagesResponse)
def list_sandbox_images():
    if not shutil.which("docker"):
        return SandboxImagesResponse(images=[])
    try:
        completed = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return SandboxImagesResponse(images=[])
    images = sorted({
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and "sandbox" in line.lower() and not line.endswith(":<none>")
    })
    return SandboxImagesResponse(images=images)


@router.put("/policy", response_model=PolicyResponse)
def update_policy(body: PolicyPayload):
    global _manager
    path = _policy_path_for_write()
    policy = CompanyPolicy(body.model_dump())
    policy.save(path)
    _manager = AgentManager(policy=policy)
    return PolicyResponse(policy_path=str(path), policy=body)


@router.get("/system/status", response_model=SystemStatusResponse)
def get_system_status(mgr: AgentManager = Depends(get_manager)):
    llm_config = LLMConfig.load()
    sandbox_config = SandboxConfig.load()
    sandbox_enabled = sandbox_config.enabled
    sandbox_status: SandboxConnectionTest | None = None
    if sandbox_enabled:
        sandbox_status = test_sandbox_connection(sandbox_config, timeout_seconds=2)
    sandbox_available = bool(sandbox_status and sandbox_status.available)
    scanner_available = importlib.util.find_spec("skill_scanner") is not None
    skillspector_available = is_skillspector_available()

    scan_modes = []
    if scanner_available:
        scan_modes.append("scanner")
    if skillspector_available:
        scan_modes.append("深度扫描")
    if llm_config.enabled:
        scan_modes.append("llm")
    scan_mode = " + ".join(scan_modes) if scan_modes else "manifest only"

    return SystemStatusResponse(
        data_dir=str(mgr.registry.data_dir),
        policy_path=str(_discover_policy_path()) if _discover_policy_path() else None,
        registry_entries=mgr.registry.count_skills(),
        review_queue=mgr.registry.count_review_queue(),
        signing_key_configured=bool(
            os.environ.get("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", "").strip()
            or os.environ.get("AGENT_MANAGER_SIGNING_PUBLIC_KEY", "").strip()
            or os.environ.get("AGENT_MANAGER_SIGNING_PUBLIC_KEY_PATH", "").strip()
            or os.environ.get("AGENT_MANAGER_SIGNING_KEY", "").strip()
        ),
        scanner_available=scanner_available,
        skillspector_enabled=skillspector_available,
        skillspector_available=skillspector_available,
        skillspector_version=None,
        sandbox_enabled=sandbox_enabled,
        sandbox_available=sandbox_available,
        sandbox_runtime=sandbox_config.runtime,
        sandbox_target=sandbox_status.target if sandbox_status else None,
        sandbox_status_message=sandbox_status.message if sandbox_status else "Sandbox 未启用",
        hooks_available=(Path(__file__).resolve().parent.parent / "hooks" / "agent_hook.py").exists(),
        llm_enabled=llm_config.enabled,
        llm_provider=llm_config.provider,
        llm_api_base=llm_config.api_base,
        llm_model=llm_config.model,
        llm_api_key_configured=bool(llm_config.api_key),
        scan_mode=scan_mode,
        service="agent-manager",
    )


# --------------------------------------------------------------------------- #
# Submit                                                                        #
# --------------------------------------------------------------------------- #

@router.post("/skills/submit-zip", response_model=SubmitResponse)
@import_endpoint
def submit_skill_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    author: str | None = Query(None),
    origin: str = Query("unknown"),
    use_behavioral: bool = Query(False),
    use_llm: bool = Query(False),
    use_sandbox: bool = Query(False),
    use_skillspector: bool = Query(False),
    judgement_mode: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    """
    Submit a skill package as a ZIP file for vetting.

    The ZIP must contain a SKILL.md at its root.
    """
    if file.size and file.size > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 100 MiB)")

    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-"))
    try:
        zip_path = tmp_dir / "skill.zip"
        with open(zip_path, "wb") as f:
            content = file.file.read()
            f.write(content)

        extract_dir = tmp_dir / "skill"
        _extract_zip_with_nested_archives(zip_path, extract_dir)

        skill_root = _resolve_skill_root(extract_dir)
        try:
            _load_manifest(skill_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        persistent_dir = mgr.registry.data_dir / "uploaded_skills" / uuid.uuid4().hex
        persistent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, persistent_dir)

        source = SourceInfo(origin=SkillOrigin(origin), author=author, channel="upload_zip")
        return _submit_directory_for_processing(
            mgr,
            background_tasks,
            persistent_dir,
            source,
            use_behavioral,
            use_llm,
            use_sandbox,
            use_skillspector,
            judgement_mode,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/skills/prepare-upload-zip", response_model=UploadZipPrepareResponse)
async def prepare_upload_zip(
    file: UploadFile = File(...),
    skip_symlinks: bool = Query(False),
    stream: bool = Query(False),
    mgr: AgentManager = Depends(get_manager),
):
    if file.size and file.size > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 100 MiB)")

    work = lambda progress: _prepare_uploaded_zip(file.file.read(), file.filename or "skill.zip", skip_symlinks, mgr, progress)
    if stream:
        return stream_upload_progress(work)
    return await run_import_work(work, None)


def _prepare_uploaded_zip(content, filename, skip_symlinks, mgr, progress=None):
    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-prepare-upload-"))
    try:
        zip_path = tmp_dir / "skill.zip"
        with open(zip_path, "wb") as f:
            f.write(content)

        extract_dir = tmp_dir / "skill"
        skipped_symlinks: list[str] = []
        extract_dir.mkdir(parents=True, exist_ok=True)
        _extract_zip_with_nested_archives(zip_path, extract_dir, skipped_symlinks=skipped_symlinks, progress=progress)
        requires_confirmation = bool(skipped_symlinks and not skip_symlinks)

        session_id = uuid.uuid4().hex
        session_root = mgr.registry.data_dir / "upload_import_sessions" / session_id
        session_root.parent.mkdir(parents=True, exist_ok=True)
        if progress:
            progress("persisting", 0, 0)
        shutil.move(str(extract_dir), session_root)
        metadata_root = mgr.registry.data_dir / "upload_import_metadata"
        metadata_root.mkdir(parents=True, exist_ok=True)
        (metadata_root / f"{session_id}.json").write_text(
            json.dumps({"skipped_symlinks": skipped_symlinks, "requires_confirmation": requires_confirmation,
                        "filename": filename}, ensure_ascii=False), encoding="utf-8",
        )
        items = [] if requires_confirmation else [LocalImportCandidate(**item) for item in _collect_import_candidates(session_root, progress=progress)]
        return UploadZipPrepareResponse(
            session_id=session_id,
            filename=filename,
            skipped_symlinks=skipped_symlinks,
            requires_symlink_confirmation=requires_confirmation,
            root_path=str(session_root),
            count=len(items),
            items=items,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/skills/confirm-upload-zip", response_model=UploadZipPrepareResponse)
async def confirm_upload_zip(body: UploadZipConfirmationRequest, stream: bool = Query(False), mgr: AgentManager = Depends(get_manager)):
    work = lambda progress: _confirm_uploaded_zip(body, mgr, progress)
    if stream:
        return stream_upload_progress(work, initial_stage="discovering")
    return await run_import_work(work, None)


def _confirm_uploaded_zip(body, mgr, progress=None):
    session_root = mgr.registry.data_dir / "upload_import_sessions" / body.session_id
    metadata_path = mgr.registry.data_dir / "upload_import_metadata" / f"{body.session_id}.json"
    if not session_root.is_dir() or not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Upload import session not found")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not body.confirmed:
        if _get_upload_jobs(mgr).active_session(body.session_id):
            raise HTTPException(status_code=409, detail="Upload import job is active")
        shutil.rmtree(session_root)
        metadata_path.unlink()
        return UploadZipPrepareResponse(session_id="", filename=metadata["filename"], root_path="", count=0, items=[])
    items = [LocalImportCandidate(**item) for item in _collect_import_candidates(session_root, progress=progress)]
    metadata["requires_confirmation"] = False
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return UploadZipPrepareResponse(
        session_id=body.session_id, filename=metadata["filename"], root_path=str(session_root),
        count=len(items), items=items, skipped_symlinks=metadata.get("skipped_symlinks", []),
    )


@router.get("/skills/import-candidates", response_model=LocalImportCandidatesResponse)
@import_endpoint
def list_import_candidates():
    root = _import_root()
    items = [LocalImportCandidate(**item) for item in _collect_import_candidates(root)]
    return LocalImportCandidatesResponse(root_path=str(root), count=len(items), items=items)


@router.post("/skills/submit-local", response_model=BatchSubmitResponse)
@import_endpoint
def submit_local_skills(
    body: LocalImportSubmitRequest,
    background_tasks: BackgroundTasks,
    mgr: AgentManager = Depends(get_manager),
):
    root = _import_root()
    if not body.paths:
        raise HTTPException(status_code=400, detail="No skill paths selected")

    source = SourceInfo(origin=SkillOrigin(body.origin), author=body.author, channel="local_import")
    results: list[SubmitResponse] = []
    for raw_path in body.paths:
        skill_dir = Path(raw_path).expanduser().resolve()
        if not _is_within_root(skill_dir, root):
            raise HTTPException(status_code=400, detail=f"Path is outside import root: {skill_dir}")
        if not (skill_dir / "SKILL.md").exists():
            raise HTTPException(status_code=400, detail=f"SKILL.md not found: {skill_dir}")
        results.append(_submit_directory_for_processing(
            mgr,
            background_tasks,
            skill_dir,
            source,
            body.use_behavioral,
            body.use_llm,
            body.use_sandbox,
            body.use_skillspector,
            body.judgement_mode,
        ))

    return BatchSubmitResponse(results=results)


@router.post("/skills/submit-url", response_model=SubmitResponse)
async def submit_skill_url(
    body: UrlSubmitRequest,
    background_tasks: BackgroundTasks,
    mgr: AgentManager = Depends(get_manager),
):
    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-download-"))
    try:
        download_path, detected_origin = await _download_remote_archive(body.url, tmp_dir)

        def prepare():
            extract_dir = tmp_dir / "skill"
            _extract_zip_with_nested_archives(download_path, extract_dir)

            skill_root = _resolve_skill_root(extract_dir)
            persistent_dir = mgr.registry.data_dir / "downloaded_skills" / uuid.uuid4().hex
            persistent_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_root, persistent_dir)
            origin_value = body.origin
            if origin_value == "unknown" and detected_origin == "github":
                origin_value = "github"
            channel = "github" if origin_value == "github" else "remote_download"
            source = SourceInfo(origin=SkillOrigin(origin_value), author=body.author, channel=channel, url=body.url)
            return _submit_directory_for_processing(
                mgr,
                background_tasks,
                persistent_dir,
                source,
                body.use_behavioral,
                body.use_llm,
                body.use_sandbox,
                body.use_skillspector,
                body.judgement_mode,
            )

        return await run_import_work(prepare)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to download skill: {exc}") from exc
    finally:
        await run_import_work(shutil.rmtree, tmp_dir, ignore_errors=True)


@router.post("/skills/prepare-remote-import", response_model=RemoteImportPrepareResponse)
async def prepare_remote_import(
    body: RemoteImportPrepareRequest,
    mgr: AgentManager = Depends(get_manager),
):
    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-prepare-remote-"))
    try:
        download_path, detected_origin = await _download_remote_archive(body.url, tmp_dir)
        def prepare():
            extract_dir = tmp_dir / "skill"
            _extract_zip_with_nested_archives(download_path, extract_dir)

            session_id = uuid.uuid4().hex
            session_root = mgr.registry.data_dir / "remote_import_sessions" / session_id
            session_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extract_dir, session_root)
            items = [LocalImportCandidate(**item) for item in _collect_import_candidates(session_root)]
            return RemoteImportPrepareResponse(
                session_id=session_id,
                source_url=body.url,
                detected_origin=detected_origin,
                root_path=str(session_root),
                count=len(items),
                items=items,
            )

        return await run_import_work(prepare)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to download skill: {exc}") from exc
    finally:
        await run_import_work(shutil.rmtree, tmp_dir, ignore_errors=True)


@router.post("/skills/submit-remote-selected", response_model=BatchSubmitResponse)
@import_endpoint
def submit_remote_selected(
    body: RemoteImportSubmitRequest,
    background_tasks: BackgroundTasks,
    mgr: AgentManager = Depends(get_manager),
):
    session_root = (mgr.registry.data_dir / "remote_import_sessions" / body.session_id).resolve()
    if not session_root.exists() or not session_root.is_dir():
        raise HTTPException(status_code=404, detail="Remote import session not found")
    if not body.paths:
        raise HTTPException(status_code=400, detail="No skill paths selected")

    origin_value = body.origin
    channel = "github" if origin_value == "github" else "remote_download"
    source = SourceInfo(origin=SkillOrigin(origin_value), author=body.author, channel=channel)
    results: list[SubmitResponse] = []
    for raw_path in body.paths:
        skill_dir = Path(raw_path).expanduser().resolve()
        if not _is_within_root(skill_dir, session_root):
            raise HTTPException(status_code=400, detail=f"Path is outside remote import session: {skill_dir}")
        if not (skill_dir / "SKILL.md").exists():
            raise HTTPException(status_code=400, detail=f"SKILL.md not found: {skill_dir}")
        persistent_dir = mgr.registry.data_dir / "downloaded_skills" / uuid.uuid4().hex
        persistent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, persistent_dir)
        results.append(_submit_directory_for_processing(
            mgr,
            background_tasks,
            persistent_dir,
            source,
            body.use_behavioral,
            body.use_llm,
            body.use_sandbox,
            body.use_skillspector,
            body.judgement_mode,
        ))
    return BatchSubmitResponse(results=results)


@router.get("/skills/upload-import-jobs")
def list_upload_import_jobs(mgr: AgentManager = Depends(get_manager)):
    jobs = _get_upload_jobs(mgr).list()
    version_ids = {item["version_id"] for job in jobs for item in job["results"]}
    runs_by_version = mgr.list_scan_runs_for_versions(list(version_ids))
    later_submission = {}
    for job in jobs:
        results = []
        for item in job["results"]:
            version_id = item["version_id"]
            results.append(resolve_import_result(item, runs_by_version.get(version_id, []),
                                                created_at=job["created_at"], before=later_submission.get(version_id)))
        for item in job["results"]:
            later_submission[item["version_id"]] = job["created_at"]
        job["results"] = results
    return {"items": jobs}


@router.post("/skills/submit-upload-selected", status_code=202)
def submit_upload_selected(
    body: RemoteImportSubmitRequest,
    background_tasks: BackgroundTasks,
    mgr: AgentManager = Depends(get_manager),
):
    session_root = (mgr.registry.data_dir / "upload_import_sessions" / body.session_id).resolve()
    if not session_root.exists() or not session_root.is_dir():
        raise HTTPException(status_code=404, detail="Upload import session not found")
    metadata_path = mgr.registry.data_dir / "upload_import_metadata" / f"{session_root.name}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    if metadata.get("requires_confirmation"):
        raise HTTPException(status_code=409, detail="ZIP symlink confirmation required")
    if not body.paths:
        raise HTTPException(status_code=400, detail="No skill paths selected")

    SkillOrigin(body.origin)
    paths = []
    for raw_path in body.paths:
        skill_dir = Path(raw_path).expanduser().resolve()
        if not _is_within_root(skill_dir, session_root):
            raise HTTPException(status_code=400, detail=f"Path is outside upload import session: {skill_dir}")
        if not (skill_dir / "SKILL.md").exists():
            raise HTTPException(status_code=400, detail=f"SKILL.md not found: {skill_dir}")
        paths.append(str(skill_dir))
    payload = body.model_dump(mode="json")
    payload["paths"] = sorted(set(paths))
    payload["filename"] = metadata.get("filename", "")
    return _get_upload_jobs(mgr).submit(payload)


@router.post("/skills/submit-clawhub", response_model=SubmitResponse)
async def submit_skill_clawhub(
    body: ClawHubSubmitRequest,
    background_tasks: BackgroundTasks,
    mgr: AgentManager = Depends(get_manager),
):
    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-clawhub-"))
    try:
        download_path = tmp_dir / "clawhub-skill.zip"
        normalized_url = _normalize_clawhub_origin_url(body.url)
        headers = {}
        if body.token:
            headers["Authorization"] = f"Bearer {body.token}"
        timeout = httpx.Timeout(60.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(normalized_url, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            final_url = str(response.url)

            if "zip" in content_type.lower() or final_url.lower().endswith(".zip"):
                await run_import_work(download_path.write_bytes, response.content)
            else:
                zip_url = _extract_zip_link_from_html(final_url, response.text)
                if not zip_url:
                    raise HTTPException(
                        status_code=400,
                        detail="ClawHub 页面中未找到可下载的 ZIP 链接；请直接填写 ZIP 下载地址或提供可访问的详情页。",
                    )
                zip_response = await client.get(zip_url, headers=headers)
                zip_response.raise_for_status()
                await run_import_work(download_path.write_bytes, zip_response.content)

        def prepare():
            extract_dir = tmp_dir / "skill"
            _extract_zip_with_nested_archives(download_path, extract_dir)

            skill_root = _resolve_skill_root(extract_dir)
            persistent_dir = mgr.registry.data_dir / "clawhub_skills" / uuid.uuid4().hex
            persistent_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_root, persistent_dir)
            source = SourceInfo(
                origin=SkillOrigin.CLAWHUB,
                author=body.author,
                channel="clawhub",
                url=body.url,
                version=body.version,
            )
            return _submit_directory_for_processing(
                mgr,
                background_tasks,
                persistent_dir,
                source,
                body.use_behavioral,
                body.use_llm,
                body.use_sandbox,
                body.use_skillspector,
                body.judgement_mode,
            )

        return await run_import_work(prepare)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to download from ClawHub: {exc}") from exc
    finally:
        await run_import_work(shutil.rmtree, tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Registry                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/skills")
def list_skills(
    status: str | None = Query(None),
    scanning: bool | None = Query(None),
    loadable_only: bool = Query(False),
    risk_level: str | None = Query(None),
    sandbox_triggered: bool | None = Query(None),
    sandbox_executed: bool | None = Query(None),
    sandbox_required_by_policy: bool | None = Query(None),
    q: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_order: str = Query("desc"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: AgentManager = Depends(get_manager),
):
    """List skills, optionally filtered by status."""
    status_values: list[SkillStatus] = []
    cancelled_only = False
    if status:
        try:
            for item in (part.strip() for part in status.split(",") if part.strip()):
                if item.lower() == "cancelled":
                    cancelled_only = True
                    status_values.append(SkillStatus.REJECTED)
                else:
                    status_values.append(SkillStatus(item))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid skill status: {status}") from exc
    if page is not None or page_size is not None:
        return mgr.list_skill_summaries(
            page=page or 1,
            page_size=page_size or 10,
            statuses=status_values or None,
            scanning=scanning,
            cancelled_only=cancelled_only,
            cancelled_reason=CANCELLED_SKILL_REASON,
            loadable_only=loadable_only,
            risk_level=risk_level,
            sandbox_triggered=sandbox_triggered,
            sandbox_executed=sandbox_executed,
            sandbox_required_by_policy=sandbox_required_by_policy,
            q=q,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    entries = mgr.list_skills()
    if scanning is not None:
        runs_by_version = mgr.list_scan_runs_for_versions([entry.skill_id for entry in entries])
        entries = [
            entry for entry in entries
            if (entry.status == SkillStatus.PENDING or any(
                run.status == "PENDING" for run in runs_by_version.get(entry.skill_id, [])
            )) == scanning
        ]
    if status_values:
        allowed_statuses = set(status_values)
        entries = [e for e in entries if e.status in allowed_statuses]
    if cancelled_only:
        entries = [e for e in entries if e.rejection_reason == CANCELLED_SKILL_REASON]
    if loadable_only:
        entries = [e for e in entries if e.is_loadable()]

    if risk_level:
        entries = [e for e in entries if e.risk_level and e.risk_level.value == risk_level]

    if sandbox_triggered is not None:
        entries = [
            e for e in entries
            if bool(e.vetting.sandbox_triggered if e.vetting else False) == sandbox_triggered
        ]

    if sandbox_executed is not None:
        # 与分页查询相同，只有本版本报告明确记录 true 才算实际执行。
        entries = [
            e for e in entries
            if bool(e.vetting and e.vetting.scan_report.get("sandbox_analysis", {}).get("executed") is True)
            == sandbox_executed
        ]

    if sandbox_required_by_policy is not None:
        entries = [
            e for e in entries
            if bool(e.vetting.sandbox_required_by_policy if e.vetting else False) == sandbox_required_by_policy
        ]

    if q:
        needle = q.lower()
        entries = [
            e for e in entries
            if needle in e.name.lower()
            or needle in e.skill_id.lower()
            or needle in (e.approved_by or "").lower()
        ]

    reverse = sort_order.lower() != "asc"
    if sort_by == "name":
        entries = sorted(entries, key=lambda e: e.name.lower(), reverse=reverse)
    elif sort_by == "skill_id":
        entries = sorted(entries, key=lambda e: e.skill_id.lower(), reverse=reverse)
    elif sort_by == "status":
        entries = sorted(entries, key=lambda e: e.status.value, reverse=reverse)
    elif sort_by == "risk_level":
        entries = sorted(entries, key=lambda e: e.risk_level.value if e.risk_level else "", reverse=reverse)
    elif sort_by == "approved_by":
        entries = sorted(entries, key=lambda e: (e.approved_by or "").lower(), reverse=reverse)
    elif sort_by == "submitted_at":
        entries = sorted(entries, key=lambda e: e.submitted_at, reverse=reverse)
    else:
        entries = sorted(entries, key=lambda e: e.updated_at, reverse=reverse)

    summaries = [e.summary() for e in entries]
    return summaries


@router.get("/dashboard/risk-source-stats")
def get_dashboard_risk_source_stats(mgr: AgentManager = Depends(get_manager)):
    """Aggregate finding counts by analyzer source for the dashboard."""
    dashboard = mgr.dashboard_stats()
    sources = {
        "rule": {
            "key": "rule",
            "label": "规则分析",
            "count": 0,
            "skills": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "llm": {
            "key": "llm",
            "label": "大模型分析",
            "count": 0,
            "skills": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "sandbox": {
            "key": "sandbox",
            "label": "Sandbox",
            "count": 0,
            "skills": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "skillspector": {
            "key": "skillspector",
            "label": "深度分析",
            "count": 0,
            "skills": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
    }

    for source_key, counts in dashboard["risk_sources"].items():
        sources[source_key].update(
            {key: value for key, value in counts.items() if key != "source_key"}
        )

    items = list(sources.values())
    return {
        "items": items,
        "total_findings": sum(item["count"] for item in items),
        "skill_summary": {
            key: dashboard[key]
            for key in ("total", "status_counts", "risk_counts", "todos")
        },
    }


@router.get("/skills/{skill_id_or_name}")
def get_skill(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    payload = entry.model_dump(mode="json", exclude={"vetting": {"scan_report"}})
    payload["version_id"] = entry.skill_id
    payload["scan_options"] = _previous_scan_options(entry) if entry.scan_options is not None or entry.vetting else None
    payload["scan_options_source"] = "submitted" if entry.scan_options is not None else "report" if entry.vetting else "unknown"
    payload["skill_id"] = entry.family_id or entry.skill_id
    trusted = mgr.get_trusted_skill(entry.family_id or skill_id_or_name)
    payload["latest_trusted_version_id"] = trusted.skill_id if trusted else None
    payload["latest_trusted_version_no"] = trusted.version_no if trusted else None
    return payload


@router.get("/skills/{skill_id_or_name}/scan-report")
def get_scan_report(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    report = entry.vetting.scan_report if entry.vetting else {}
    if isinstance(report.get("sandbox_analysis"), dict):
        # 历史说明只在响应中补齐编码，保留原始报告及执行判定。
        report = {**report, "sandbox_analysis": with_sandbox_reason_metadata(report["sandbox_analysis"])}
    deep = report.get("skillspector_analysis")
    if isinstance(deep, dict):
        deep = with_deep_scan_analysis_display(deep)
        report = {**report, "skillspector_analysis": deep}
    if (
        isinstance(deep, dict)
        and "suppressed_findings" not in deep
        and isinstance(deep.get("raw_report"), dict)
    ):
        # 仅补齐响应中的历史噪声明细，保留已存储报告与风险判定。
        report = {**report, "skillspector_analysis": {
            **deep, "suppressed_findings": get_suppressed_findings(deep["raw_report"]),
        }}
    return {
        "skill_id": entry.family_id or entry.skill_id,
        "version_id": entry.skill_id,
        "version_no": entry.version_no,
        "name": entry.name,
        "scan_report": report,
    }


@router.get("/skills/{skill_id_or_name}/scan-report.pdf")
def export_scan_report_pdf(
    skill_id_or_name: str,
    language: str = Query("zh-CN", pattern="^(zh-CN|en-US)$"),
    mgr: AgentManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if entry.vetting is None or entry.status == SkillStatus.PENDING:
        raise HTTPException(status_code=409, detail="Scan result is not available yet")

    document = build_scan_report_pdf(
        entry,
        scan_runs=mgr.list_scan_runs(entry.skill_id),
        audit_events=mgr.audit(skill_id=entry.skill_id, limit=100),
        language=language,
    )
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", entry.name or entry.skill_id).strip("-") or "skill"
    filename = f"{safe_name}-v{entry.version_no}-scan-report.pdf"
    return Response(
        content=document,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _version_summary(
    entry,
    *,
    scan_runs=None,
    audit_events=None,
    processing_count: int | None = None,
    rescan_requested: bool | None = None,
) -> dict[str, Any]:
    runs = list(scan_runs or [])
    events = list(audit_events or [])
    report = entry.vetting.scan_report if entry.vetting else {}
    llm_analysis = report.get("llm_analysis") if isinstance(report.get("llm_analysis"), dict) else None
    policy_notes = list(entry.vetting.policy_notes if entry.vetting else [])
    llm_note = next((str(note) for note in policy_notes if str(note).startswith("[LLM]")), None)
    analyzers = {str(item).lower() for item in report.get("analyzers_used", [])}
    # 优先使用本次报告状态，旧报告继续沿用原有推断规则。
    recorded_llm_status = report.get("analyzer_timings", {}).get("llm", {}).get("status")
    if recorded_llm_status in {"completed", "failed", "disabled", "skipped"}:
        llm_status = recorded_llm_status
    elif llm_analysis:
        llm_status = "completed"
    elif llm_note:
        llm_status = "skipped"
    elif any(item.startswith("llm:") for item in analyzers):
        llm_status = "failed"
    else:
        llm_status = "not_run"
    effective_processing_count = (
        processing_count
        if processing_count is not None
        else sum(1 for event in events if event.event_type == "skill_processing_completed")
    )
    effective_rescan_requested = (
        rescan_requested
        if rescan_requested is not None
        else any(event.event_type == "skill_rescan_requested" for event in events)
    )
    rescanned = (
        len(runs) > 1
        or effective_processing_count > 1
        or effective_rescan_requested
    )
    latest_run = runs[0] if runs else None
    return {
        "skill_id": entry.family_id or entry.skill_id,
        "version_id": entry.skill_id,
        "version_no": entry.version_no,
        "source_version": entry.source_version,
        "status": entry.status.value,
        "risk_level": entry.risk_level.value if entry.risk_level else None,
        "content_fingerprint": entry.content_fingerprint,
        "scan_context_fingerprint": entry.scan_context_fingerprint,
        "scan_reused": entry.scan_reused,
        "latest": entry.latest_version,
        "latest_trusted": entry.latest_trusted_version,
        "submitted_at": entry.submitted_at,
        "updated_at": entry.updated_at,
        "approved_at": entry.approved_at,
        "approved_by": entry.approved_by,
        "last_scanned_at": (
            latest_run.finished_at or latest_run.started_at
            if latest_run
            else entry.updated_at
        ),
        "scan_run_count": max(len(runs), effective_processing_count),
        "rescanned": rescanned,
        "risk_chain": {
            "static_risk_level": report.get("pre_llm_risk_level") or (entry.risk_level.value if entry.risk_level else None),
            "llm_status": llm_status,
            "llm_risk_level": llm_analysis.get("risk_level") if llm_analysis else None,
            "final_risk_level": entry.risk_level.value if entry.risk_level else None,
            "llm_note": llm_note,
            "downgrade_reason": llm_analysis.get("downgrade_reason") if llm_analysis else None,
            "dismissed_findings": llm_analysis.get("dismissed_findings", []) if llm_analysis else [],
        },
    }


@router.get("/skills/{skill_id_or_name}/versions")
def list_skill_versions(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    versions = mgr.list_skill_versions(skill_id_or_name)
    if not versions:
        raise HTTPException(status_code=404, detail="Skill not found")
    version_ids = [entry.skill_id for entry in versions]
    runs_by_version = mgr.list_scan_runs_for_versions(version_ids)
    activity_by_version = mgr.skill_version_activity(version_ids)
    items = []
    for entry in versions:
        runs = runs_by_version.get(entry.skill_id, [])
        activity = activity_by_version.get(entry.skill_id, {})
        item = _version_summary(
            entry,
            scan_runs=runs,
            processing_count=int(activity.get("processing_count", 0)),
            rescan_requested=bool(activity.get("rescan_requested", False)),
        )
        item["scan_pending"] = any(run.status == "PENDING" for run in runs)
        items.append(item)
    return {
        "skill_id": versions[0].family_id or versions[0].skill_id,
        "name": versions[0].name,
        "items": items,
    }


def _resolve_version_ref(versions: list[Any], value: str | None, *, default_index: int) -> Any:
    if value is None:
        return versions[min(default_index, len(versions) - 1)]
    normalized = value.strip().lower()
    for entry in versions:
        if normalized in {
            entry.skill_id.lower(),
            str(entry.version_no),
            f"v{entry.version_no}",
            str(entry.source_version or "").lower(),
            f"v{str(entry.source_version or '').lower()}",
        }:
            return entry
    raise HTTPException(status_code=404, detail=f"Skill version not found: {value}")


def _version_text_files(entry) -> dict[str, list[str]]:
    if not entry.skill_path:
        return {}
    root = Path(entry.skill_path).resolve()
    if not root.is_dir():
        return {}
    result: dict[str, list[str]] = {}
    excluded = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in excluded]
        for name in filenames:
            path = Path(directory) / name
            if name in excluded or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > 1024 * 1024:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            result[path.relative_to(root).as_posix()] = text.splitlines(keepends=True)
    return result


@router.get("/skills/{skill_id_or_name}/diff")
def diff_skill_versions(
    skill_id_or_name: str,
    base: str | None = Query(None),
    target: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    versions = mgr.list_skill_versions(skill_id_or_name)
    if not versions:
        raise HTTPException(status_code=404, detail="Skill not found")
    target_entry = _resolve_version_ref(versions, target, default_index=0)
    base_entry = _resolve_version_ref(versions, base, default_index=1 if len(versions) > 1 else 0)
    response = {
        "skill_id": versions[0].family_id or versions[0].skill_id,
        "base": _version_summary(base_entry),
        "target": _version_summary(target_entry),
        "items": [],
    }
    if base_entry.skill_id == target_entry.skill_id:
        return response
    base_files = _version_text_files(base_entry)
    target_files = _version_text_files(target_entry)
    items = []
    for path in sorted(set(base_files) | set(target_files)):
        before = base_files.get(path, [])
        after = target_files.get(path, [])
        if before == after:
            continue
        status = "added" if path not in base_files else "deleted" if path not in target_files else "changed"
        diff_lines = list(difflib.unified_diff(
            before,
            after,
            fromfile=f"v{base_entry.version_no}/{path}",
            tofile=f"v{target_entry.version_no}/{path}",
            lineterm="\n",
        ))
        additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        diff_text = "".join(
            line if line.endswith(("\n", "\r")) else f"{line}\n"
            for line in diff_lines
        )
        items.append({
            "path": path,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "before": "".join(before),
            "after": "".join(after),
            "diff": diff_text,
        })
    response["items"] = items
    return response


@router.get("/skills/{skill_id_or_name}/versions/{version_id}/scan-runs")
def list_version_scan_runs(
    skill_id_or_name: str,
    version_id: str,
    mgr: AgentManager = Depends(get_manager),
):
    versions = mgr.list_skill_versions(skill_id_or_name)
    version = next((entry for entry in versions if entry.skill_id == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return {
        "skill_id": version.family_id or version.skill_id,
        "version_id": version.skill_id,
        "items": [run.model_dump(mode="json") for run in mgr.list_scan_runs(version.skill_id)],
    }


def _previous_scan_options(entry) -> dict[str, bool]:
    if entry.scan_options is not None:
        return dict(entry.scan_options)
    report = entry.vetting.scan_report if entry.vetting else {}
    analyzers = {str(item).lower() for item in report.get("analyzers_used", [])}
    return {
        "use_behavioral": bool(report.get("behavioral_analysis") or report.get("local_static_analysis") or analyzers.intersection({"behavioral:local", "agent-manager-local"})),
        "use_llm": bool(report.get("llm_analysis") or any(item.startswith("llm:") for item in analyzers)),
        "use_sandbox": bool(report.get("sandbox_analysis") or any(item.startswith("sandbox:") for item in analyzers)),
        "use_skillspector": bool(report.get("skillspector_analysis") or any(item.startswith("skillspector:") for item in analyzers)),
    }


@router.post("/skills/{skill_id}/rescan", response_model=SubmitResponse)
def rescan_skill(
    skill_id: str,
    use_behavioral: bool | None = Query(None),
    use_llm: bool | None = Query(None),
    use_sandbox: bool | None = Query(None),
    use_skillspector: bool | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    previous = mgr.get_skill(skill_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    previous_options = _previous_scan_options(previous)
    scan_options = {
        "use_behavioral": previous_options["use_behavioral"] if use_behavioral is None else use_behavioral,
        "use_llm": previous_options["use_llm"] if use_llm is None else use_llm,
        "use_sandbox": previous_options["use_sandbox"] if use_sandbox is None else use_sandbox,
        "use_skillspector": previous_options["use_skillspector"] if use_skillspector is None else use_skillspector,
    }
    try:
        entry, started = mgr.request_rescan(skill_id, scan_options=scan_options)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if started:
        _scan_executor.submit(
            _process_pending_submission_task,
            mgr,
            entry.skill_id,
            scan_options["use_behavioral"],
            scan_options["use_llm"],
            scan_options["use_sandbox"],
            scan_options["use_skillspector"],
            True,
        )
    current = mgr.get_skill(entry.skill_id) or entry
    return SubmitResponse(
        skill_id=current.family_id or current.skill_id,
        version_id=current.skill_id,
        version_no=current.version_no,
        source_version=current.source_version,
        deduplicated=True,
        scan_reused=False,
        outcome="rescan_submitted" if started else "already_scanning",
        name=current.name,
        status=current.status.value,
        risk_level=current.risk_level.value if current.risk_level else None,
        findings_count=current.vetting.findings_count if current.vetting else 0,
        sandbox_triggered=current.vetting.sandbox_triggered if current.vetting else False,
        sandbox_required_by_policy=current.vetting.sandbox_required_by_policy if current.vetting else False,
        sandbox_runtime=current.vetting.sandbox_runtime if current.vetting else None,
        message=(
            "已提交重新检测，后台分析中。请刷新技能注册表查看状态变化。"
            if started
            else "该版本正在检测中，无需重复提交。"
        ),
    )


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, mgr: AgentManager = Depends(get_manager)):
    try:
        entry = mgr.delete_skill(skill_id)
        return {"skill_id": entry.skill_id, "status": "DELETED", "message": "Deleted"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/skills/{skill_id_or_name}/governance-card", response_model=GovernanceCardResponse)
def get_governance_card(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    try:
        return GovernanceCardResponse(**mgr.get_governance_card(skill_id_or_name))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@router.post("/skills/{skill_id_or_name}/governance-card/refresh", response_model=GovernanceCardResponse)
def refresh_governance_card(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    try:
        return GovernanceCardResponse(**mgr.refresh_governance_card(skill_id_or_name))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@router.get("/skills/{skill_id_or_name}/content", response_model=SkillContentResponse)
def get_skill_content(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    manifest_path = Path(entry.skill_path) / "SKILL.md"
    if not manifest_path.exists() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="SKILL.md not found")

    try:
        content, encoding = read_text_fallback(manifest_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read SKILL.md: {exc}") from exc

    return SkillContentResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        manifest_path=str(manifest_path),
        content=content,
        encoding=encoding,
    )


@router.get("/skills/{skill_id_or_name}/files", response_model=SkillFilesResponse)
def list_skill_files(skill_id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    skill_root = Path(entry.skill_path)
    if not skill_root.exists() or not skill_root.is_dir():
        raise HTTPException(status_code=404, detail="Skill directory not found")

    files = [
        SkillFileEntry(
            path=str(path.relative_to(skill_root).as_posix()),
            size_bytes=path.stat().st_size,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        )
        for path in sorted(skill_root.rglob("*"))
        if path.is_file()
    ]

    return SkillFilesResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        skill_path=str(skill_root),
        file_count=len(files),
        files=files,
    )


@router.get("/skills/{skill_id_or_name}/file-content", response_model=SkillFileContentResponse)
def get_skill_file_content(
    skill_id_or_name: str,
    path: str = Query(..., min_length=1),
    mgr: AgentManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    skill_root = Path(entry.skill_path).resolve()
    if not skill_root.exists() or not skill_root.is_dir():
        raise HTTPException(status_code=404, detail="Skill directory not found")

    requested = (skill_root / path).resolve()
    try:
        requested.relative_to(skill_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsafe file path") from exc

    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content, encoding = read_text_fallback(requested)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}") from exc

    return SkillFileContentResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        path=path,
        absolute_path=str(requested),
        content=content,
        encoding=encoding,
    )


@router.get("/skills/{skill_id_or_name}/download")
def download_skill_archive(
    skill_id_or_name: str,
    background_tasks: BackgroundTasks,
    version: str | None = Query(None),
    trusted: bool = Query(False),
    mgr: AgentManager = Depends(get_manager),
):
    if version:
        versions = mgr.list_skill_versions(skill_id_or_name)
        entry = _resolve_version_ref(versions, version, default_index=0) if versions else None
    elif trusted:
        entry = mgr.get_trusted_skill(skill_id_or_name)
    else:
        entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    skill_root = Path(entry.skill_path).resolve()
    if not skill_root.exists() or not skill_root.is_dir():
        raise HTTPException(status_code=404, detail="Skill directory not found")

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", entry.name or entry.skill_id).strip("-") or "skill"
    tmp = tempfile.NamedTemporaryFile(prefix=f"{safe_name}-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(skill_root.rglob("*")):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                try:
                    rel = resolved.relative_to(skill_root)
                except ValueError:
                    continue
                if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in rel.parts):
                    continue
                archive.write(resolved, rel.as_posix())
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to package Skill: {exc}") from exc

    background_tasks.add_task(tmp_path.unlink, missing_ok=True)
    return FileResponse(
        path=tmp_path,
        filename=f"{safe_name}.zip",
        media_type="application/zip",
    )


@router.post("/skills/{skill_id_or_name}/verify-signature", response_model=VerifySignatureResponse)
def verify_skill_signature(
    skill_id_or_name: str,
    body: VerifySignatureRequest,
    mgr: AgentManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.signature:
        return VerifySignatureResponse(
            valid=False,
            skill_id=entry.skill_id,
            skill_name=entry.name,
            reason="No signature stored for this skill",
        )

    skill_path = body.skill_path or entry.skill_path
    if not skill_path:
        return VerifySignatureResponse(
            valid=False,
            skill_id=entry.skill_id,
            skill_name=entry.name,
            reason="No skill path available for verification",
        )

    from agent_manager.core.signer import verify_signature

    valid = verify_signature(skill_path, entry.signature)
    return VerifySignatureResponse(
        valid=valid,
        skill_id=entry.skill_id,
        skill_name=entry.name,
        reason="signature valid" if valid else "signature mismatch",
    )


# --------------------------------------------------------------------------- #
# Review                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/review")
def list_review_queue(
    risk_level: str | None = Query(None),
    q: str | None = Query(None),
    review_status: str = Query("pending"),
    sort_by: str = Query("queued_at"),
    sort_order: str = Query("asc"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: AgentManager = Depends(get_manager),
):
    allowed_review_statuses = {"pending", "reviewed", "all"}
    if review_status not in allowed_review_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"review_status must be one of: {', '.join(sorted(allowed_review_statuses))}",
        )

    data: list[dict[str, Any]] = []

    # 1) Pending review items (VETTED, in review queue)
    if review_status in ("pending", "all"):
        queue = mgr.list_review_queue()
        for r in queue:
            item = r.model_dump(mode="json")
            item["findings_summary"] = findings_summary_from_report(None, r.findings_summary)
            item["status"] = SkillStatus.VETTED.value
            item["approved_by"] = None
            item["approved_at"] = None
            item["reviewed_at"] = None
            item["rejection_reason"] = None
            item["approval_note"] = None
            item["review_note"] = item.get("notes")
            item["sort_at"] = item.get("queued_at")
            data.append(item)

    # 2) Already reviewed items (APPROVED / REJECTED, from registry)
    if review_status in ("reviewed", "all"):
        data.extend(mgr.list_reviewed_summaries())

    # 3) Apply filters
    if risk_level:
        data = [r for r in data if r.get("risk_level") == risk_level]

    if q:
        needle = q.lower()
        data = [
            r for r in data
            if needle in (r.get("skill_name") or "").lower()
            or needle in (r.get("skill_id") or "").lower()
            or needle in (r.get("notes") or "").lower()
            or needle in (r.get("review_note") or "").lower()
            or needle in (r.get("approval_note") or "").lower()
            or needle in (r.get("rejection_reason") or "").lower()
        ]

    # 4) Sort
    reverse = sort_order.lower() != "asc"
    if sort_by == "skill_name":
        data = sorted(data, key=lambda r: (r.get("skill_name") or "").lower(), reverse=reverse)
    elif sort_by == "risk_level":
        data = sorted(data, key=lambda r: r.get("risk_level") or "", reverse=reverse)
    elif sort_by == "submitted_at":
        data = sorted(data, key=lambda r: r.get("submitted_at") or "", reverse=reverse)
    elif sort_by == "reviewed_at":
        data = sorted(data, key=lambda r: r.get("reviewed_at") or "", reverse=reverse)
    elif sort_by == "sort_at":
        data = sorted(data, key=lambda r: r.get("sort_at") or "", reverse=reverse)
    elif sort_by == "status":
        data = sorted(data, key=lambda r: r.get("status") or "", reverse=reverse)
    else:
        data = sorted(data, key=lambda r: r.get("queued_at") or "", reverse=reverse)

    if page is not None or page_size is not None:
        return _paginate(data, page or 1, page_size or 10)
    return data


@router.post("/skills/{skill_id}/approve")
def approve_skill(
    skill_id: str,
    body: ApproveRequest,
    mgr: AgentManager = Depends(get_manager),
):
    if len(body.note or "") > REVIEW_TEXT_MAX_LENGTH:
        raise ApiError(
            422, "skill.review_note_too_long",
            "审批备注不能超过 1000 个字符", "Approval note must not exceed 1000 characters",
        )
    try:
        entry = mgr.approve(skill_id, approver=body.approver, note=body.note)
        from backend.client_task_notifications import notify_all
        notify_all()
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Approved"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/reject")
def reject_skill(
    skill_id: str,
    body: RejectRequest,
    mgr: AgentManager = Depends(get_manager),
):
    if len(body.reason or "") > REVIEW_TEXT_MAX_LENGTH:
        raise ApiError(
            422, "skill.review_reason_too_long",
            "拒绝原因不能超过 1000 个字符", "Rejection reason must not exceed 1000 characters",
        )
    try:
        entry = mgr.reject(skill_id, reviewer=body.reviewer, reason=body.reason)
        from backend.client_task_notifications import notify_all
        notify_all()
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Rejected"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/cancel")
def cancel_skill_scan(
    skill_id: str,
    body: CancelScanRequest,
    mgr: AgentManager = Depends(get_manager),
):
    try:
        entry, cancelled = mgr.cancel_scan(skill_id, reviewer=body.reviewer)
        from backend.client_task_notifications import notify_all
        notify_all()
        scan_pending = any(run.status == "PENDING" for run in mgr.list_scan_runs(entry.skill_id))
        return {
            "skill_id": entry.skill_id,
            "status": entry.status.value,
            "scan_pending": scan_pending,
            "outcome": "cancelled" if cancelled else "no_pending_scan",
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={
            "error_code": "skill_not_found", "message": "Skill 不存在",
        }) from exc


# --------------------------------------------------------------------------- #
# Deploy / Retire                                                               #
# --------------------------------------------------------------------------- #

@router.post("/skills/{skill_id}/deploy")
def deploy_skill(skill_id: str, mgr: AgentManager = Depends(get_manager)):
    try:
        entry = mgr.deploy(skill_id)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Deployed"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/retire")
def retire_skill(
    skill_id: str,
    body: RetireRequest,
    mgr: AgentManager = Depends(get_manager),
):
    try:
        entry = mgr.retire(skill_id, reason=body.reason, actor=body.actor)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Retired"}
    except (KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))


# --------------------------------------------------------------------------- #
# Runtime guard endpoints (called by agents)                                    #
# --------------------------------------------------------------------------- #

@runtime_router.get("/runtime/can-load/{skill_name}", response_model=RuntimeCheckResponse)
def runtime_can_load(
    request: Request,
    skill_name: str,
    skill_path: str | None = Query(None),
    agent_id: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    """Check whether an agent may load a skill (enforces registry + signature)."""
    _legacy_runtime_endpoint_removed()
    allowed, entry, reason = mgr.runtime.can_load(
        skill_name,
        skill_path=skill_path,
        agent_id=agent_id,
        audit_metadata={"agent_id": agent_id, "client_ip": request.client.host if request.client else None},
    )
    return RuntimeCheckResponse(
        allowed=allowed,
        reason=reason,
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
    )


@runtime_router.post("/runtime/verify-skill-signature", response_model=VerifySkillSignatureResponse)
def runtime_verify_skill_signature(
    body: VerifySkillSignatureRequest,
    request: Request,
    mgr: AgentManager = Depends(get_manager),
):
    """Verify a locally computed skill signature sent by an external agent."""
    _legacy_runtime_endpoint_removed()
    allowed, entry, reason = mgr.runtime.verify_local_signature(
        body.skill_name or "",
        body.local_signature,
        skill_id=body.skill_id,
        agent_id=body.agent_id,
        audit_metadata={"agent_id": body.agent_id, "client_ip": request.client.host if request.client else None},
    )
    return VerifySkillSignatureResponse(
        allowed=allowed,
        reason=reason,
        skill_id=entry.skill_id if entry else None,
        skill_name=entry.name if entry else (body.skill_name or ""),
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
        signature_match=allowed,
    )


@runtime_router.get("/runtime/check-tool", response_model=ToolCheckResponse)
def runtime_check_tool(
    request: Request,
    skill_name: str = Query(...),
    tool_name: str = Query(...),
    agent_id: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    """Check whether a skill is permitted to invoke a tool."""
    _legacy_runtime_endpoint_removed()
    allowed = mgr.runtime.check_tool(
        skill_name,
        tool_name,
        agent_id=agent_id,
        audit_metadata={"agent_id": agent_id, "client_ip": request.client.host if request.client else None},
    )
    return ToolCheckResponse(allowed=allowed, skill_name=skill_name, tool_name=tool_name)


@runtime_router.get("/runtime/signing-public-key", response_model=SigningPublicKeyResponse)
def runtime_signing_public_key():
    """Return the non-secret public key used for offline Skill verification."""
    from agent_manager.core.signer import signing_key_id, signing_public_key_base64

    try:
        return SigningPublicKeyResponse(
            key_id=signing_key_id(),
            public_key=signing_public_key_base64(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="signing public key is not initialized",
        ) from exc


# --------------------------------------------------------------------------- #
# Hook endpoints (called by claude_api_hook.py)                                #
# --------------------------------------------------------------------------- #

class HookEventRequest(BaseModel):
    hook_event_name: str
    session_id: str | None = None
    cwd: str | None = None
    file_path: str | None = None
    source: str | None = None
    tool_name: str | None = None
    # Allow any other fields from the hook event
    model_config = {"extra": "allow"}


class HookEventResponse(BaseModel):
    allowed: bool
    message: str


@router.post("/hook/event", response_model=HookEventResponse)
def hook_process_event(
    body: HookEventRequest,
    mgr: AgentManager = Depends(get_manager),
):
    """Process a Claude Code hook event via API."""
    from agent_manager.hooks.agent_hook import process_event

    # Convert the model to a dict, preserving all extra fields
    event = body.model_dump()
    allowed, message = process_event(event)
    return HookEventResponse(allowed=allowed, message=message)


# --------------------------------------------------------------------------- #
# Audit                                                                         #
# --------------------------------------------------------------------------- #

@router.get("/audit")
def get_audit(
    since_hours: float = Query(24.0),
    skill_id: str | None = Query(None),
    event_type: str | None = Query(None),
    event_types: str | None = Query(None),
    actor: str | None = Query(None),
    q: str | None = Query(None),
    sort_order: str = Query("desc"),
    limit: int = Query(100),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: AgentManager = Depends(get_manager),
):
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = mgr.audit(since=since, skill_id=skill_id, limit=limit)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    elif event_types:
        allowed_types = {item.strip() for item in event_types.split(",") if item.strip()}
        events = [e for e in events if e.event_type in allowed_types]
    if actor:
        needle = actor.lower()
        events = [e for e in events if needle in (e.actor or "").lower()]
    if q:
        needle = q.lower()
        events = [
            e for e in events
            if needle in e.skill_name.lower()
            or needle in e.skill_id.lower()
            or needle in (e.actor or "").lower()
            or needle in json.dumps(e.details, ensure_ascii=False).lower()
        ]

    events = sorted(events, key=lambda e: e.timestamp, reverse=(sort_order.lower() != "asc"))
    data = []
    for event in events:
        item = event.model_dump(mode="json")
        details = item.get("details") or {}
        if isinstance(details, dict):
            item["agent_id"] = details.get("agent_id") or item.get("actor")
            item["client_ip"] = details.get("client_ip")
            item["token_name"] = details.get("token_name")
            item["token_type"] = details.get("token_type")
        data.append(item)
    if page is not None or page_size is not None:
        return _paginate(data, page or 1, page_size or 10)
    return data


# --------------------------------------------------------------------------- #
# Prompt endpoints                                                              #
# --------------------------------------------------------------------------- #

# Module-level temp dir for prompt deploys
_prompt_content_temp_dir: Path | None = None


def _get_prompt_content_temp_dir() -> Path:
    global _prompt_content_temp_dir
    if _prompt_content_temp_dir is None or not _prompt_content_temp_dir.exists():
        _prompt_content_temp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-prompts-"))
    return _prompt_content_temp_dir


class PromptSubmitPayload(BaseModel):
    name: str
    content: str
    agent_id: str = ""
    description: str = ""
    author: str | None = None


class PromptApprovePayload(BaseModel):
    approver: str = "admin"
    note: str | None = None


class PromptRejectPayload(BaseModel):
    reviewer: str = "admin"
    reason: str


class PromptDeployPayload(BaseModel):
    target_dir: str | None = None
    actor: str | None = None


class PromptRetirePayload(BaseModel):
    reason: str
    actor: str | None = None


class PromptVerifyPayload(BaseModel):
    prompt_name: str
    local_content: str | None = None
    local_file_path: str | None = None


@router.post("/prompts/submit")
def submit_prompt(body: PromptSubmitPayload, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.submit_prompt(
        name=body.name,
        content=body.content,
        agent_id=body.agent_id,
        description=body.description,
        author=body.author,
    )
    try:
        entry = mgr.vet_prompt(entry.prompt_id)
    except Exception as exc:
        logger.error("Prompt vetting failed for %s: %s", entry.prompt_id, exc)
    return entry.model_dump(mode="json")


@router.get("/prompts")
def list_prompts(
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    if status and "," in status:
        statuses = {PromptStatus(item.strip()) for item in status.split(",") if item.strip()}
        entries = [entry for entry in mgr.list_prompts(agent_id=agent_id) if entry.status in statuses]
    else:
        status_enum = PromptStatus(status) if status else None
        entries = mgr.list_prompts(status=status_enum, agent_id=agent_id)
    return [e.summary() for e in entries]


@router.get("/prompts/loadable")
def list_loadable_prompts(
    agent_id: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    entries = mgr.list_prompts_loadable(agent_id=agent_id)
    return [e.summary() for e in entries]


@router.get("/prompts/review")
def list_prompt_review_queue(mgr: AgentManager = Depends(get_manager)):
    queue = mgr.list_prompt_review_queue()
    return [r.model_dump(mode="json") for r in queue]


@router.get("/prompts/{id_or_name}")
def get_prompt(id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_prompt(id_or_name)
    if not entry:
        raise HTTPException(404, f"Prompt {id_or_name!r} not found")
    return entry.model_dump(mode="json")


@router.get("/prompts/{id_or_name}/content")
def get_prompt_content(id_or_name: str, mgr: AgentManager = Depends(get_manager)):
    entry = mgr.get_prompt(id_or_name)
    if not entry:
        raise HTTPException(404, f"Prompt {id_or_name!r} not found")
    if not entry.is_loadable():
        raise HTTPException(403, f"Prompt {id_or_name!r} is not loadable")
    return {"name": entry.name, "content": entry.content, "signature": entry.signature, "agent_id": entry.agent_id}


@router.post("/prompts/{prompt_id}/approve")
def approve_prompt(prompt_id: str, body: PromptApprovePayload, mgr: AgentManager = Depends(get_manager)):
    try:
        entry = mgr.approve_prompt(prompt_id, body.approver, body.note)
        return entry.model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, f"Prompt {prompt_id!r} not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/prompts/{prompt_id}/reject")
def reject_prompt(prompt_id: str, body: PromptRejectPayload, mgr: AgentManager = Depends(get_manager)):
    try:
        entry = mgr.reject_prompt(prompt_id, body.reviewer, body.reason)
        return entry.model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, f"Prompt {prompt_id!r} not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/prompts/{prompt_id}/deploy")
def deploy_prompt(prompt_id: str, body: PromptDeployPayload | None = None, mgr: AgentManager = Depends(get_manager)):
    target_dir = body.target_dir if body else None
    actor = body.actor if body else None
    try:
        entry = mgr.deploy_prompt(prompt_id, target_dir=target_dir, actor=actor)
        return entry.model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, f"Prompt {prompt_id!r} not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/prompts/{prompt_id}/retire")
def retire_prompt(prompt_id: str, body: PromptRetirePayload, mgr: AgentManager = Depends(get_manager)):
    try:
        entry = mgr.retire_prompt(prompt_id, body.reason, body.actor)
        return entry.model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, f"Prompt {prompt_id!r} not found")


# -- Runtime endpoints for agent-side prompt verification

@runtime_router.get("/runtime/verify-prompt")
def verify_prompt(
    prompt_name: str = Query(...),
    local_content: str | None = Query(None),
    local_file_path: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    _legacy_runtime_endpoint_removed()
    result = mgr.verify_prompt_signature(
        prompt_name=prompt_name,
        local_content=local_content,
        local_file_path=Path(local_file_path) if local_file_path else None,
    )
    return result


@runtime_router.post("/runtime/verify-prompt-signature")
def verify_prompt_signature_endpoint(body: PromptVerifyPayload, mgr: AgentManager = Depends(get_manager)):
    _legacy_runtime_endpoint_removed()
    result = mgr.verify_prompt_signature(
        prompt_name=body.prompt_name,
        local_content=body.local_content,
        local_file_path=Path(body.local_file_path) if body.local_file_path else None,
    )
    return result


@runtime_router.get("/runtime/can-load-prompt/{prompt_name}")
def can_load_prompt(
    prompt_name: str,
    local_file_path: str | None = Query(None),
    agent_id: str | None = Query(None),
    mgr: AgentManager = Depends(get_manager),
):
    _legacy_runtime_endpoint_removed()
    entry = mgr.get_prompt(prompt_name)
    if not entry:
        return {"allowed": False, "status": None, "reason": f"Prompt {prompt_name!r} not found in registry"}
    if not entry.is_loadable():
        return {"allowed": False, "status": entry.status.value, "reason": f"Prompt {prompt_name!r} is {entry.status.value}"}
    if agent_id and entry.agent_id and entry.agent_id != agent_id:
        return {"allowed": False, "status": entry.status.value, "reason": f"Prompt belongs to agent {entry.agent_id!r}, not {agent_id!r}"}
    if local_file_path and entry.signature:
        from agent_manager.core.signer import verify_prompt_signature as _verify
        verified = _verify(Path(local_file_path), entry.signature)
        if not verified:
            return {"allowed": False, "status": entry.status.value, "reason": "Prompt 签名校验失败，文件可能被篡改"}
    return {"allowed": True, "status": entry.status.value, "prompt_id": entry.prompt_id, "agent_id": entry.agent_id}
