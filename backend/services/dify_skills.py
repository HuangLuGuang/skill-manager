"""Dify package identities backed by the existing immutable Skill registry."""
import base64
import binascii
import hashlib
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile

from fastapi import BackgroundTasks
from sqlalchemy.dialects.sqlite import insert

from agent_manager.api.router import _resolve_skill_root, _submit_directory_for_processing
from agent_manager.core.archives import safe_extract_zip
from agent_manager.core.models import SourceInfo, SkillOrigin
from ..dify_runtime_models import DifyRuntimeSkill
from ..api_errors import ApiError


def summary(row, mgr):
    entry = mgr.get_skill(row.version_id, include_scan_report=False)
    pending = entry and any(run.status == "PENDING" for run in mgr.list_scan_runs(entry.skill_id))
    return {"name": row.skill_name, "dify_agent_id": row.dify_agent_id,
            "archive_hash": row.archive_hash, "version_id": row.version_id,
            "status": "PENDING" if pending else entry.status.value if entry else "MISSING",
            "risk_level": entry.risk_level.value if entry and entry.risk_level and not pending else None,
            "seen_at": row.seen_at}


def submit(db, binding, body, mgr):
    try:
        content = base64.b64decode(body.archive_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError(400, "dify_runtime.invalid_skill_archive", "Skill 压缩包无效", "Invalid Skill archive") from None
    archive_hash = hashlib.sha256(content).hexdigest()
    row = db.query(DifyRuntimeSkill).filter_by(binding_id=binding.binding_id,
        dify_agent_id=body.dify_agent_id, archive_hash=archive_hash).first()
    if row and mgr.get_skill(row.version_id, include_scan_report=False):
        row.seen_at = datetime.utcnow()
        db.commit()
        return summary(row, mgr)
    persistent = mgr.registry.data_dir / "scanner_uploaded_skills" / uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="dify-skill-") as folder:
            archive = Path(folder) / "skill.zip"
            archive.write_bytes(content)
            safe_extract_zip(archive, Path(folder) / "content")
            root = _resolve_skill_root(Path(folder) / "content")
            persistent.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, persistent)
        response = _submit_directory_for_processing(mgr, BackgroundTasks(), persistent,
            SourceInfo(origin=SkillOrigin.LOCAL, author=binding.agent_id, channel="dify"),
            True, True, True, True)
    except (BadZipFile, ValueError):
        shutil.rmtree(persistent, ignore_errors=True)
        raise ApiError(400, "dify_runtime.invalid_skill_archive", "Skill 压缩包无效", "Invalid Skill archive") from None
    except Exception:
        shutil.rmtree(persistent, ignore_errors=True)
        raise
    values = dict(binding_id=binding.binding_id, dify_agent_id=body.dify_agent_id,
                  archive_hash=archive_hash, skill_name=response.name,
                  version_id=response.version_id, seen_at=datetime.utcnow())
    db.execute(insert(DifyRuntimeSkill).values(**values).on_conflict_do_update(
        index_elements=["binding_id", "dify_agent_id", "archive_hash"],
        set_={key: values[key] for key in ("skill_name", "version_id", "seen_at")}))
    db.commit()
    row = db.query(DifyRuntimeSkill).filter_by(binding_id=binding.binding_id,
        dify_agent_id=body.dify_agent_id, archive_hash=archive_hash).one()
    return summary(row, mgr)


def admission(db, binding, body, mgr, *, source="dify_publish"):
    results = []
    for item in body.skills:
        row = db.query(DifyRuntimeSkill).filter_by(binding_id=binding.binding_id,
            dify_agent_id=body.dify_agent_id, archive_hash=item.archive_hash).first()
        result = summary(row, mgr) if row else {"name": item.name, "status": "MISSING"}
        allowed = False
        reason = result["status"].lower()
        if row and row.skill_name == item.name and result["status"] in {"APPROVED", "DEPLOYED"}:
            entry = mgr.get_skill(row.version_id, include_scan_report=False)
            if entry.signature and entry.skill_path:
                allowed, _, reason = mgr.runtime.can_load(row.version_id, skill_path=entry.skill_path,
                    agent_id=binding.agent_id, audit_metadata={"source": source,
                        "binding_id": binding.binding_id, "archive_hash": item.archive_hash})
        result["allowed"] = allowed
        result["reason"] = reason
        results.append(result)
    return {"allowed": binding.mode == "observe" or all(item["allowed"] for item in results),
            "mode": binding.mode, "skills": results}
