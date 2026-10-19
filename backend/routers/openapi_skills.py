"""Partner Skill upload, progress, report and finding APIs."""
import copy
import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from agent_manager.api import router as native
from agent_manager.api.import_work import import_endpoint
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.scan_cache import compute_content_fingerprint, compute_scan_context_fingerprint
from agent_manager.core.vetting import _load_manifest
from .. import models
from ..api_errors import ApiError, request_locale
from ..external_access import link_external_resource, require_openapi_scope
from ..external_access_models import ExternalSkillScan, ExternalResultEvent
from ..openapi_contract import success
from ..services import openapi_skills as service
from ..sqlite_db import get_db

router = APIRouter(prefix="/openapi/v1/skill-scans", tags=["openapi-skills"])
submit_access = require_openapi_scope("openapi:skill-submit")
read_access = require_openapi_scope("openapi:skill-read")


def _link(request, row):
    link_external_resource(request, "skill", row.version_id, row.department_id, row.business_request_id)


@router.post("", status_code=202)
@import_endpoint
def submit(request: Request, file: UploadFile = File(...), metadata: str = Form(...),
           context=Depends(submit_access), db: Session = Depends(get_db), mgr=Depends(native.get_manager)):
    try:
        body = service.Metadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise ApiError(422, "INVALID_ARGUMENT", "metadata 字段无效", "Invalid metadata fields",
            params={"details": [{"field": "metadata." + ".".join(str(x) for x in e["loc"]),
                                 "reason": "required" if e["type"] == "missing" else e["type"]} for e in exc.errors()]}) from None
    group_id = context.department_group(body.department_id)
    profile, callback = service.configuration(body, context, mgr.registry.data_dir, db)
    frozen_profile = {**profile.model_dump(), "policy": copy.deepcopy(mgr.policy.to_dict())}
    frozen = AgentManager(policy=CompanyPolicy(frozen_profile["policy"]), registry=mgr.registry)
    opts = service.options(frozen_profile)
    credential = db.get(models.AccessToken, context.token_id)
    max_bytes = credential.max_upload_mb * 1024 * 1024
    max_jobs = credential.max_concurrent_jobs
    db.rollback()  # Release the read transaction before registry writes.
    if file.size and file.size > max_bytes:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Skill ZIP 超过上传大小限制", "Skill ZIP exceeds the upload size limit")
    with tempfile.TemporaryDirectory(prefix="openapi-skill-") as directory:
        root = Path(directory)
        archive, extracted = root / "skill.zip", root / "skill"
        digest, size = hashlib.sha256(), 0
        with archive.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(413, "PAYLOAD_TOO_LARGE", "Skill ZIP 超过上传大小限制", "Skill ZIP exceeds the upload size limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != body.file_sha256:
            raise ApiError(422, "INVALID_ARGUMENT", "ZIP 的 SHA-256 与 metadata 不一致", "ZIP SHA-256 does not match metadata",
                           params={"details": [{"field": "metadata.file_sha256", "reason": "hash_mismatch"}]})
        try:
            native._extract_zip_with_nested_archives(archive, extracted)
            if not (extracted / "SKILL.md").is_file():
                raise ValueError("Root SKILL.md required")
            name, _, _, _ = _load_manifest(extracted)
        except (zipfile.BadZipFile, ValueError, RuntimeError):
            raise ApiError(422, "INVALID_ARGUMENT", "请上传根目录包含有效 SKILL.md 的 ZIP", "Upload a ZIP with a valid SKILL.md at its root") from None
        source = SourceInfo(origin=SkillOrigin.LOCAL, channel="external_api", author=context.platform_id,
                            version=body.skill_version)
        with native._submission_lock:
            # Reconcile finished jobs before applying this credential's job limit.
            for task in db.query(ExternalSkillScan).filter_by(source_token_id=context.token_id).filter(ExternalSkillScan.status.in_(service.ACTIVE)).all():
                service.sync_task(db, task, mgr)
            active_count = db.query(ExternalSkillScan).filter_by(source_token_id=context.token_id).filter(ExternalSkillScan.status.in_(service.ACTIVE)).count()
            db.rollback()
            if active_count >= max_jobs:
                raise ApiError(429, "RATE_LIMITED", "凭证的并发检测任务数已达上限", "The credential's concurrent scan limit has been reached", headers={"Retry-After": "5"})
            existing = mgr.registry.find_version_by_content(name, compute_content_fingerprint(extracted))
            if existing:
                pending = next((r for r in mgr.list_scan_runs(existing.skill_id) if r.status == "PENDING"), None)
                expected = compute_scan_context_fingerprint(frozen.policy, **opts)
                if pending and pending.scan_context_fingerprint != expected:
                    raise ApiError(503, "SERVICE_UNAVAILABLE", "相同内容正在按另一方案检测，请稍后重试", "This content is being scanned with another profile; retry later", headers={"Retry-After": "5"})
            entry, should_process, resolution = frozen.prepare_submission(extracted, source=source, **opts)
            runs = mgr.list_scan_runs(entry.skill_id)
            run = next((r for r in runs if r.status == "PENDING"), runs[0] if runs else None)
            if resolution == "existing_version_reused":
                # Old installations have version reports but no execution snapshots.
                # Produce a new execution instead of assigning old mutable data.
                if run is None or run.status not in {"COMPLETED", "REUSED"} or mgr.registry.get_scan_run_report(run.scan_run_id) is None:
                    entry, should_process = frozen.request_rescan(entry.skill_id, scan_options={k: v for k, v in opts.items() if k != "judgement_mode"})
                    run = next(r for r in mgr.list_scan_runs(entry.skill_id) if r.status == "PENDING")
            row = ExternalSkillScan(task_id="skt_" + uuid.uuid4().hex,
                source_platform_id=context.platform_id, source_token_id=context.token_id,
                source_request_id=context.request_id, department_id=body.department_id, department_group_id=group_id,
                business_request_id=body.business_request_id, external_skill_id=body.skill_id,
                skill_version=body.skill_version, file_sha256=body.file_sha256, version_id=entry.skill_id,
                scan_run_id=run.scan_run_id, owns_scan=should_process, profile_id=body.profile_id,
                profile_json=json.dumps(frozen_profile), callback_id=body.callback_id, callback_version=callback.version)
            row.analyzers_json = json.dumps(service.analyzer_states(frozen_profile, run))
            db.add(row)
            db.commit()
            task_id = row.task_id
            accepted = {"task_id": task_id, "business_request_id": row.business_request_id,
                        "status": "pending", "created_at": service.iso(row.created_at)}
            _link(request, row)
        if should_process:
            service.dispatch(task_id, mgr)
        else:
            service.sync_task(db, row, mgr)
    return success(request, accepted)


@router.get("/{task_id}")
def get_progress(task_id: service.Identifier, request: Request, context=Depends(read_access), db: Session = Depends(get_db), mgr=Depends(native.get_manager)):
    row = service.get_owned_task(db, task_id, context, mgr)
    _link(request, row)
    event = db.query(ExternalResultEvent).filter_by(task_id=row.task_id).first()
    return success(request, service.progress(row, mgr, request_locale(request) == "en-US", event))


@router.get("/{task_id}/result")
def get_result(task_id: service.Identifier, request: Request, context=Depends(read_access), db: Session = Depends(get_db), mgr=Depends(native.get_manager)):
    row = service.get_owned_task(db, task_id, context, mgr)
    _link(request, row)
    service.require_report(row)
    return success(request, json.loads(row.report_json))


@router.get("/{task_id}/findings")
def get_findings(task_id: service.Identifier, request: Request, cursor: str | None = Query(None, max_length=1024),
                 limit: int = Query(50, ge=1, le=200), context=Depends(read_access), db: Session = Depends(get_db), mgr=Depends(native.get_manager)):
    row = service.get_owned_task(db, task_id, context, mgr)
    _link(request, row)
    service.require_report(row)
    return success(request, service.findings_page(row, cursor, limit))
