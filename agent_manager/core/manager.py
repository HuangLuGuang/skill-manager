"""
AgentManager — high-level API that wires together vetting, registry, signing,
policy, and runtime guard.

This is the main entry point for programmatic use.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    AuditEvent,
    RegistryEntry,
    ReviewRequest,
    RiskLevel,
    ScanRun,
    SkillStatus,
    SourceInfo,
    SkillOrigin,
    VettingResult,
)
from .policy import CompanyPolicy
from .registry import Registry, make_event
from .prompt_manager import PromptManager
from .prompt_models import PromptEntry, PromptStatus, PromptAuditEvent, PromptReviewRequest
from .runtime import RuntimeGuard
from .scan_cache import (
    ScanCacheStore,
    compute_content_fingerprint,
    compute_scan_cache_key,
    compute_scan_context_fingerprint,
)
from .signer import compute_signature, compute_prompt_signature
from .vetting import VettingPipeline, _load_manifest
from .governance_card import read_or_write_governance_card, write_governance_card

logger = logging.getLogger(__name__)


def findings_summary_from_report(
    scan_report: dict[str, Any] | None,
    fallback: dict[str, int] | None = None,
) -> dict[str, int]:
    """Return normalized C/H/M/L counts from a scan report."""
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    findings = scan_report.get("findings") if isinstance(scan_report, dict) else None
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity") or "").lower()
            if severity in summary:
                summary[severity] += 1
        summary["total"] = sum(summary.values())
        return summary

    raw = fallback
    if raw is None and isinstance(scan_report, dict):
        maybe_summary = scan_report.get("findings_summary")
        raw = maybe_summary if isinstance(maybe_summary, dict) else None
    if raw:
        for key in ("critical", "high", "medium", "low"):
            summary[key] = int(raw.get(key) or raw.get(key.upper()) or 0)
        summary["total"] = int(raw.get("total") or sum(summary.values()))
    else:
        summary["total"] = 0
    return summary


class AgentManager:
    """
    Lifecycle manager for AI agent skills.

    Usage::

        mgr = AgentManager()

        # Submit and vet a skill
        entry = mgr.submit("./my-skill")

        # Approve a VETTED skill (human review)
        mgr.approve(entry.skill_id, approver="alice", note="LGTM")

        # Mark as deployed
        mgr.deploy(entry.skill_id)

        # Runtime check
        allowed, _, _ = mgr.runtime.can_load("my-skill", "./my-skill")
    """

    def __init__(
        self,
        policy: CompanyPolicy | None = None,
        registry: Registry | None = None,
        data_dir: str | Path | None = None,
    ):
        self.registry = registry or Registry(data_dir)
        self.policy = policy or CompanyPolicy.default()
        self.prompts = PromptManager(self)
        self.vetting = VettingPipeline(self.policy)
        self.runtime = RuntimeGuard(self.registry)
        self.scan_cache = ScanCacheStore(self.registry.data_dir)

    # ------------------------------------------------------------------ #
    # Submit                                                               #
    # ------------------------------------------------------------------ #

    def submit(
        self,
        skill_path: str | Path,
        source: SourceInfo | None = None,
        author: str | None = None,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
        use_skillspector: bool = False,
        judgement_mode: str | None = None,
    ) -> RegistryEntry:
        """
        Vet a skill and submit it to the registry.
        """
        entry, should_process, _reason = self.prepare_submission(
            skill_path,
            source=source,
            author=author,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            judgement_mode=judgement_mode,
        )
        if not should_process:
            return entry
        return self.process_pending_submission(
            entry.skill_id,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            force_scan=False,
            judgement_mode=judgement_mode,
        )

    def prepare_submission(
        self,
        skill_path: str | Path,
        source: SourceInfo | None = None,
        author: str | None = None,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
        use_skillspector: bool = False,
        judgement_mode: str | None = None,
    ) -> tuple[RegistryEntry, bool, str]:
        """Resolve a submission to an immutable version and decide whether to scan it."""
        from .licensing import require_license
        require_license("skill_governance")
        require_license("security_scanning")
        resolved = Path(skill_path).resolve()
        if source is None:
            source = SourceInfo(origin=SkillOrigin.LOCAL, author=author)
        name, description, allowed_tools, _license = _load_manifest(resolved)
        content_fingerprint = compute_content_fingerprint(resolved)
        scan_context_fingerprint = compute_scan_context_fingerprint(
            self.policy,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            judgement_mode=judgement_mode,
        )
        existing = self.registry.find_version_by_content(name, content_fingerprint)
        scan_options = {
            "use_behavioral": use_behavioral, "use_llm": use_llm,
            "use_sandbox": use_sandbox, "use_skillspector": use_skillspector,
        }
        reuse_enabled = self.policy.scan_result_reuse_enabled
        if existing:
            runs = self.registry.list_scan_runs(existing.skill_id)
            if any(run.status == "PENDING" for run in runs):
                return existing, False, "scan_in_progress"
            if (
                reuse_enabled
                and existing.scan_context_fingerprint == scan_context_fingerprint
                and existing.vetting is not None
            ):
                self.scan_cache.put(
                    existing.scan_cache_key or compute_scan_cache_key(content_fingerprint, scan_context_fingerprint),
                    existing,
                    content_fingerprint,
                    scan_context_fingerprint,
                )
                existing, resolution = self.registry.record_scan_reuse(
                    existing.skill_id, content_fingerprint, scan_context_fingerprint,
                )
                if resolution != "existing_version_rescan":
                    return existing, False, resolution
            entry = existing
            entry.scan_options = scan_options
            entry.scan_context_fingerprint = scan_context_fingerprint
            entry.scan_cache_key = compute_scan_cache_key(content_fingerprint, scan_context_fingerprint)
            entry.scan_reused = False
            entry.reused_from_skill_id = None
            self.registry.update(entry)
            self._start_scan_run(entry, forced=not reuse_enabled)
            return entry, True, "existing_version_rescan"

        family_id, version_no = self.registry.next_version_no(name)
        family_id = family_id or str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        snapshot_path = self.registry.data_dir / "skill_versions" / family_id / version_id
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(resolved, snapshot_path, symlinks=True)
        entry = RegistryEntry(
            skill_id=version_id,
            family_id=family_id,
            version_no=version_no,
            source_version=source.version,
            name=name,
            description=description,
            source=source,
            skill_path=str(snapshot_path),
            status=SkillStatus.PENDING,
            scan_options=scan_options,
            allowed_tools=allowed_tools,
            content_fingerprint=content_fingerprint,
            scan_context_fingerprint=scan_context_fingerprint,
            scan_cache_key=compute_scan_cache_key(content_fingerprint, scan_context_fingerprint),
        )
        self.registry.add(entry)
        self._start_scan_run(entry, forced=not reuse_enabled)
        self.registry.log_event(make_event(
            "skill_submitted",
            entry,
            details={"skill_path": str(resolved), "status": SkillStatus.PENDING.value},
        ))
        self.registry.log_event(make_event(
            "skill_version_submitted",
            entry,
            details={
                "family_id": entry.family_id,
                "version_id": entry.skill_id,
                "version_no": entry.version_no,
                "content_fingerprint": content_fingerprint,
            },
        ))
        return entry, True, "new_version"

    def create_pending_submission(
        self,
        skill_path: str | Path,
        source: SourceInfo | None = None,
        author: str | None = None,
    ) -> RegistryEntry:
        from .licensing import require_license
        require_license("skill_governance")
        require_license("security_scanning")
        skill_path = Path(skill_path).resolve()

        if source is None:
            source = SourceInfo(origin=SkillOrigin.LOCAL, author=author)

        try:
            name, description, allowed_tools, _license = _load_manifest(skill_path)
        except Exception:
            name = skill_path.name
            description = ""
            allowed_tools = []

        family_id, version_no = self.registry.next_version_no(name)
        entry = RegistryEntry(
            skill_id=str(uuid.uuid4()),
            family_id=family_id,
            version_no=version_no,
            source_version=source.version,
            name=name,
            description=description,
            source=source,
            skill_path=str(skill_path),
            status=SkillStatus.PENDING,
            allowed_tools=allowed_tools,
        )
        self.registry.add(entry)
        self.registry.log_event(make_event(
            "skill_submitted",
            entry,
            details={"skill_path": str(skill_path), "status": SkillStatus.PENDING.value},
        ))
        return entry

    def _start_scan_run(self, entry: RegistryEntry, *, forced: bool) -> ScanRun:
        run = ScanRun(
            scan_run_id=str(uuid.uuid4()),
            version_id=entry.skill_id,
            scan_context_fingerprint=entry.scan_context_fingerprint or "",
            forced=forced,
        )
        self.registry.add_scan_run(run)
        return run

    def _pending_scan_run(self, entry: RegistryEntry, *, forced: bool = False) -> ScanRun:
        runs = self.registry.list_scan_runs(entry.skill_id)
        for run in runs:
            if run.status == "PENDING":
                return run
        return self._start_scan_run(entry, forced=forced)

    def _finish_scan_run(
        self,
        entry: RegistryEntry,
        *,
        status: str,
        reused_from_scan_run_id: str | None = None,
    ) -> None:
        run = self._pending_scan_run(entry)
        run.status = status
        run.reused_from_scan_run_id = reused_from_scan_run_id
        run.finished_at = datetime.now(timezone.utc)
        run.result = {**run.result, **ScanRun.result_for(entry)}
        # Commit the execution's report with its terminal state. A failed rescan
        # may preserve the version's previous report, which belongs to another run.
        report = entry.vetting.model_dump(mode="json") if entry.vetting and status in {"COMPLETED", "REUSED"} else None
        self.registry.update_scan_run(run, report=report)

    @staticmethod
    def _reset_version_for_scan(entry: RegistryEntry) -> RegistryEntry:
        entry.status = SkillStatus.PENDING
        entry.risk_level = None
        entry.vetting = None
        entry.signature = None
        entry.approved_at = None
        entry.approved_by = None
        entry.approval_note = None
        entry.rejection_reason = None
        entry.retire_reason = None
        entry.retired_at = None
        entry.deployed_at = None
        entry.scan_reused = False
        entry.reused_from_skill_id = None
        return entry

    def process_pending_submission(
        self,
        skill_id: str,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
        use_skillspector: bool = False,
        force_scan: bool = False,
        judgement_mode: str | None = None,
    ) -> RegistryEntry:
        from .licensing import require_license
        require_license("security_scanning")
        entry = self._require_entry(skill_id)
        runs = self.registry.list_scan_runs(entry.skill_id)
        if runs and runs[0].status == "CANCELLED":
            return entry
        active_run_id = next((run.scan_run_id for run in runs if run.status == "PENDING"), None)

        def report_progress(stage: str) -> None:
            if active_run_id:
                self.registry.update_scan_progress(active_run_id, stage)

        def report_analyzer(analyzer: str, status: str) -> None:
            if active_run_id:
                self.registry.update_scan_analyzer(active_run_id, analyzer, status)

        report_progress("preparing")
        skill_path = Path(entry.skill_path or "").resolve()
        source = entry.source
        content_fingerprint = compute_content_fingerprint(skill_path)
        scan_context_fingerprint = compute_scan_context_fingerprint(
            self.policy,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            judgement_mode=judgement_mode,
        )
        scan_cache_key = compute_scan_cache_key(content_fingerprint, scan_context_fingerprint)
        if entry.content_fingerprint is not None:
            entry.content_fingerprint = content_fingerprint
        entry.scan_context_fingerprint = scan_context_fingerprint
        entry.scan_cache_key = scan_cache_key
        entry.scan_options = {
            "use_behavioral": use_behavioral, "use_llm": use_llm,
            "use_sandbox": use_sandbox, "use_skillspector": use_skillspector,
        }
        self.registry.update(entry, backfill_content_fingerprint=content_fingerprint)

        reuse_enabled = self.policy.scan_result_reuse_enabled and not force_scan
        if reuse_enabled:
            cached = self.scan_cache.get(scan_cache_key)
            if cached:
                cached_entry = self.registry.get_by_id(cached.get("skill_id", ""))
                if cached_entry and cached_entry.vetting and cached_entry.status != SkillStatus.PENDING:
                    reused = self._reuse_scan_result(entry, cached_entry, skill_path, content_fingerprint)
                    source_runs = self.registry.list_scan_runs(cached_entry.skill_id)
                    self._finish_scan_run(
                        reused,
                        status="REUSED",
                        reused_from_scan_run_id=source_runs[0].scan_run_id if source_runs else None,
                    )
                    return reused

            matching_entry = self._find_completed_scan_match(
                entry.skill_id,
                content_fingerprint,
                scan_context_fingerprint,
            )
            if matching_entry:
                self.scan_cache.put(
                    scan_cache_key,
                    matching_entry,
                    content_fingerprint,
                    scan_context_fingerprint,
                )
                reused = self._reuse_scan_result(entry, matching_entry, skill_path, content_fingerprint)
                source_runs = self.registry.list_scan_runs(matching_entry.skill_id)
                self._finish_scan_run(
                    reused,
                    status="REUSED",
                    reused_from_scan_run_id=source_runs[0].scan_run_id if source_runs else None,
                )
                return reused

        logger.info("Vetting skill at %s ...", skill_path)

        vetting_result, violations, name, description, allowed_tools = self.vetting.vet(
            skill_path,
            source,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            use_skillspector=use_skillspector,
            judgement_mode=judgement_mode,
            progress_callback=report_progress,
            analyzer_callback=report_analyzer,
        )
        current_entry = self.registry.get_by_id(skill_id)
        pending_run = next(
            (run for run in self.registry.list_scan_runs(skill_id)
             if run.status == "PENDING" and (active_run_id is None or run.scan_run_id == active_run_id)),
            None,
        )
        if current_entry and pending_run is None:
            logger.info(
                "Skip processing result for skill %r because its scan run is no longer pending",
                current_entry.name,
            )
            return current_entry

        # 根据最终 risk_level 决定状态
        status = self.policy.decide(vetting_result.risk_level, violations)
        declared_tools_valid = not any(v.rule in ("tool_not_in_allowlist", "blocked_permission") for v in violations)
        vetting_result.scan_report = {
            **(vetting_result.scan_report or {}),
            "scan_reused": False,
            "content_fingerprint": content_fingerprint,
            "scan_context_fingerprint": scan_context_fingerprint,
            "scan_cache_key": scan_cache_key,
        }
        findings_summary = findings_summary_from_report(vetting_result.scan_report)
        vetting_result.scan_report["findings_summary"] = findings_summary

        entry.name = name
        entry.description = description
        entry.status = status
        entry.risk_level = vetting_result.risk_level
        entry.rejection_reason = None
        entry.vetting = vetting_result
        # 实际重扫完成后清除上一轮的复用标记。
        entry.scan_reused = False
        entry.reused_from_skill_id = None
        entry.allowed_tools = allowed_tools
        entry.declared_tools_valid = declared_tools_valid

        if status == SkillStatus.APPROVED:
            entry.signature = compute_signature(skill_path)
            entry.approved_at = datetime.now(timezone.utc)
            entry.approved_by = "auto-policy"
        else:
            # A completed rescan replaces the previous effective decision. Do
            # not leave stale approval evidence or a usable signature attached
            # to a version that is now pending review or rejected.
            entry.signature = None
            entry.approved_at = None
            entry.approved_by = None
            entry.approval_note = None
            entry.deployed_at = None

        card = write_governance_card(entry, self.registry)
        if entry.vetting:
            entry.vetting.scan_report = {
                **entry.vetting.scan_report,
                "governance_card_path": card["path"],
                "governance_card_generated_at": card["generated_at"],
            }

        self.registry.update(entry)
        self.registry.log_event(make_event(
            "skill_processing_completed",
            entry,
            details={
                "risk_level": vetting_result.risk_level.value,
                "pre_llm_risk_level": vetting_result.scan_report.get("pre_llm_risk_level"),
                "max_severity": vetting_result.scan_report.get("max_severity"),
                "status": status.value,
                "violations": [v.rule for v in violations],
            },
        ))

        if status == SkillStatus.VETTED:
            self.registry.enqueue_review(ReviewRequest(
                skill_id=entry.skill_id,
                skill_name=name,
                risk_level=entry.risk_level,
                findings_summary=findings_summary,
                submitted_at=entry.submitted_at,
                notes="; ".join(vetting_result.policy_notes) if vetting_result.policy_notes else None,
            ))
            self.registry.log_event(make_event("skill_queued_for_review", entry))

        self.registry.log_event(make_event(
            "skill_vetted", entry,
            details={"risk_level": vetting_result.risk_level.value, "status": status.value},
        ))

        logger.info("Processed skill %r: status=%s risk=%s", name, status.value, vetting_result.risk_level.value)
        self.scan_cache.put(scan_cache_key, entry, content_fingerprint, scan_context_fingerprint)
        self._finish_scan_run(entry, status="COMPLETED")
        return entry

    def _reuse_scan_result(
        self,
        entry: RegistryEntry,
        cached_entry: RegistryEntry,
        skill_path: Path,
        content_fingerprint: str,
    ) -> RegistryEntry:
        entry.name = cached_entry.name
        entry.description = cached_entry.description
        entry.status = cached_entry.status
        entry.risk_level = cached_entry.risk_level
        entry.rejection_reason = cached_entry.rejection_reason
        entry.vetting = cached_entry.vetting.model_copy(deep=True) if cached_entry.vetting else None
        entry.allowed_tools = list(cached_entry.allowed_tools)
        entry.declared_tools_valid = cached_entry.declared_tools_valid
        entry.scan_reused = True
        entry.reused_from_skill_id = cached_entry.skill_id
        if entry.vetting:
            entry.vetting.scan_report = {
                **entry.vetting.scan_report,
                "scan_reused": True,
                "reused_from_skill_id": cached_entry.skill_id,
                "reused_from_skill_name": cached_entry.name,
                "content_fingerprint": content_fingerprint,
                "scan_context_fingerprint": entry.scan_context_fingerprint,
                "scan_cache_key": entry.scan_cache_key,
            }
            entry.vetting.policy_notes = [
                *entry.vetting.policy_notes,
                f"[CACHE] reused scan result from {cached_entry.skill_id}",
            ]

        if entry.status == SkillStatus.APPROVED:
            entry.signature = compute_signature(skill_path)
            entry.approved_at = datetime.now(timezone.utc)
            entry.approved_by = "auto-policy-cache"
        elif entry.status == SkillStatus.VETTED and entry.risk_level:
            findings_summary = findings_summary_from_report(entry.vetting.scan_report if entry.vetting else None)
            self.registry.enqueue_review(ReviewRequest(
                skill_id=entry.skill_id,
                skill_name=entry.name,
                risk_level=entry.risk_level,
                findings_summary=findings_summary,
                submitted_at=entry.submitted_at,
                notes="复用历史扫描结果，仍需人工审核。",
            ))

        self.registry.update(entry)
        self.registry.log_event(make_event(
            "skill_scan_reused",
            entry,
            details={
                "reused_from_skill_id": cached_entry.skill_id,
                "content_fingerprint": content_fingerprint,
                "scan_context_fingerprint": entry.scan_context_fingerprint,
                "scan_cache_key": entry.scan_cache_key,
                "status": entry.status.value,
                "risk_level": entry.risk_level.value if entry.risk_level else None,
            },
        ))
        self.registry.log_event(make_event(
            "skill_vetted",
            entry,
            details={
                "risk_level": entry.risk_level.value if entry.risk_level else None,
                "status": entry.status.value,
                "scan_reused": True,
            },
        ))
        logger.info("Reused scan result for skill %r from %s", entry.name, cached_entry.skill_id)
        return entry

    def mark_submission_failed(self, skill_id: str, reason: str, actor: str | None = None) -> RegistryEntry:
        entry = self._require_entry(skill_id)
        runs = self.registry.list_scan_runs(entry.skill_id)
        if runs and runs[0].status == "CANCELLED":
            return entry
        if entry.status != SkillStatus.PENDING and entry.vetting is not None:
            self._finish_scan_run(entry, status="FAILED")
            self.registry.log_event(make_event(
                "skill_processing_failed",
                entry,
                actor=actor,
                details={"reason": reason, "effective_result_preserved": True},
            ))
            return entry
        entry.status = SkillStatus.REJECTED
        entry.risk_level = RiskLevel.BENIGN
        entry.rejection_reason = reason
        entry.vetting = VettingResult(
            risk_level=RiskLevel.BENIGN,
            findings_count=1,
            analyzers_used=["scanner:error"],
            scan_report={
                "risk_level": RiskLevel.BENIGN.value,
                "max_severity": "INFO",
                "risk_max_severity": "INFO",
                "findings": [
                    {
                        "source": "system",
                        "severity": "INFO",
                        "rule": "VETTING_FAILED",
                        "title": "后台分析失败",
                        "message": reason,
                    }
                ],
                "analyzers_used": ["scanner:error"],
                "vetting_failed": True,
                "vetting_error": reason,
            },
            policy_notes=[f"[BLOCK] vetting_failed: {reason}"],
        )
        self.registry.update(entry)
        self._finish_scan_run(entry, status="FAILED")
        self.registry.log_event(make_event(
            "skill_processing_failed",
            entry,
            actor=actor,
            details={"reason": reason},
        ))
        return entry

    # ------------------------------------------------------------------ #
    # Approve / Reject                                                     #
    # ------------------------------------------------------------------ #

    def approve(
        self,
        skill_id: str,
        approver: str,
        note: str | None = None,
    ) -> RegistryEntry:
        """
        Approve a reviewed skill.

        Signs the skill and moves it to APPROVED status.
        """
        from .licensing import require_license
        require_license("skill_governance")
        entry = self._require_entry(skill_id)

        manual_policy_override = False
        if entry.status == SkillStatus.REJECTED:
            manual_policy_override = self._can_manually_override_rejection(entry)
        if entry.status != SkillStatus.VETTED and not manual_policy_override:
            raise ValueError(
                f"Skill {entry.name!r} is {entry.status.value}. "
                "Only VETTED skills or low-risk policy rejections can be approved manually."
            )

        skill_path = entry.skill_path
        if not skill_path or not Path(skill_path).exists():
            raise ValueError(
                f"Skill path {skill_path!r} is not accessible. "
                "The skill directory must still be present to compute its signature."
            )

        entry.status = SkillStatus.APPROVED
        entry.approved_by = approver
        entry.approved_at = datetime.now(timezone.utc)
        entry.approval_note = note
        entry.signature = compute_signature(skill_path)

        self.registry.update(entry)
        self.registry.dequeue_review(skill_id)
        self.registry.log_event(make_event(
            "skill_approved", entry, actor=approver,
            details={
                "note": note,
                "manual_policy_override": manual_policy_override,
                "previous_status": SkillStatus.REJECTED.value if manual_policy_override else SkillStatus.VETTED.value,
            },
        ))

        logger.info("Approved skill %r by %r", entry.name, approver)
        return entry

    def _can_manually_override_rejection(self, entry: RegistryEntry) -> bool:
        if entry.vetting and entry.vetting.scan_report.get("vetting_failed"):
            return True
        if str(entry.rejection_reason or "").startswith("后台分析失败"):
            return True
        if entry.risk_level not in (RiskLevel.BENIGN, RiskLevel.SUSPICIOUS):
            return False
        notes = entry.vetting.policy_notes if entry.vetting else []
        blocking_notes = [str(note) for note in notes if str(note).startswith("[BLOCK]")]
        if not blocking_notes:
            return False
        return all(
            "tool_not_in_allowlist" in note or "blocked_permission" in note or "unaccepted_license" in note
            for note in blocking_notes
        )

    def cancel_scan(self, skill_id: str, reviewer: str) -> tuple[RegistryEntry, bool]:
        """Cancel scanning while preserving a completed version's effective decision."""
        entry = self._require_entry(skill_id)
        if entry.status == SkillStatus.PENDING:
            return self.reject(entry.skill_id, reviewer, "用户取消后台分析任务"), True
        pending = [run for run in self.registry.list_scan_runs(entry.skill_id) if run.status == "PENDING"]
        for run in pending:
            run.status = "CANCELLED"
            run.finished_at = datetime.now(timezone.utc)
            self.registry.update_scan_run(run)
            self.registry.log_event(make_event(
                "skill_scan_cancelled", entry, actor=reviewer,
                details={"scan_run_id": run.scan_run_id},
            ))
        return entry, bool(pending)

    def reject(
        self,
        skill_id: str,
        reviewer: str,
        reason: str,
    ) -> RegistryEntry:
        """Reject a VETTED skill."""
        entry = self._require_entry(skill_id)

        if entry.status not in (SkillStatus.VETTED, SkillStatus.PENDING):
            raise ValueError(f"Skill {entry.name!r} is {entry.status.value}, cannot be rejected")

        entry.status = SkillStatus.REJECTED
        entry.rejection_reason = reason

        self.registry.update(entry)
        self.registry.dequeue_review(skill_id)
        for run in self.registry.list_scan_runs(entry.skill_id):
            if run.status == "PENDING":
                run.status = "CANCELLED"
                run.finished_at = datetime.now(timezone.utc)
                self.registry.update_scan_run(run)
        self.registry.log_event(make_event(
            "skill_rejected", entry, actor=reviewer,
            details={"reason": reason},
        ))

        logger.info("Rejected skill %r by %r: %s", entry.name, reviewer, reason)
        return entry

    # ------------------------------------------------------------------ #
    # Deploy / Retire                                                      #
    # ------------------------------------------------------------------ #

    def deploy(self, skill_id: str, actor: str | None = None) -> RegistryEntry:
        """Mark an APPROVED skill as DEPLOYED."""
        from .licensing import require_license
        require_license("skill_governance")
        entry = self._require_entry(skill_id)

        if entry.status != SkillStatus.APPROVED:
            raise ValueError(f"Skill {entry.name!r} must be APPROVED before deploying")

        entry.status = SkillStatus.DEPLOYED
        entry.deployed_at = datetime.now(timezone.utc)

        self.registry.update(entry)
        self.registry.log_event(make_event("skill_deployed", entry, actor=actor))

        logger.info("Deployed skill %r", entry.name)
        return entry

    def retire(
        self,
        skill_id_or_name: str,
        reason: str,
        actor: str | None = None,
    ) -> RegistryEntry:
        """
        Retire a skill — immediately revokes loadability.

        Accepts either a skill_id (UUID) or skill name.
        """
        # Try UUID first, then name
        entry = self.registry.get_by_id(skill_id_or_name)
        if entry is None:
            entry = self.registry.get_by_name(skill_id_or_name)
        if entry is None:
            raise KeyError(f"Skill {skill_id_or_name!r} not found in registry")

        entry.status = SkillStatus.RETIRED
        entry.retire_reason = reason
        entry.retired_at = datetime.now(timezone.utc)

        self.registry.update(entry)
        self.registry.log_event(make_event(
            "skill_retired", entry, actor=actor,
            details={"reason": reason},
        ))

        logger.info("Retired skill %r: %s", entry.name, reason)
        return entry

    def delete_skill(self, skill_id: str, actor: str | None = None) -> RegistryEntry:
        exact = self.registry.get_by_id(skill_id)
        targets = [exact] if exact else self.registry.list_versions(skill_id)
        targets = [entry for entry in targets if entry is not None]
        if not targets:
            raise KeyError(f"Skill {skill_id!r} not found in registry")
        selected = targets[0]
        version_root = (self.registry.data_dir / "skill_versions").resolve()
        for entry in targets:
            self.registry.log_event(make_event("skill_deleted", entry, actor=actor))
            self.registry.delete(entry.skill_id)
            if entry.skill_path:
                path = Path(entry.skill_path).resolve()
                if version_root in path.parents:
                    shutil.rmtree(path, ignore_errors=True)
        return selected

    def rescan_skill(self, skill_id: str, actor: str | None = None) -> RegistryEntry:
        entry, started = self.request_rescan(skill_id, actor=actor)
        if not started:
            raise ValueError(f"Skill version {entry.skill_id!r} already has a pending scan")
        return entry

    def request_rescan(
        self, skill_id: str, actor: str | None = None,
        scan_options: dict[str, bool] | None = None,
    ) -> tuple[RegistryEntry, bool]:
        """Start a rescan, or return the existing in-progress request."""
        from .licensing import require_license
        require_license("security_scanning")
        entry = self._require_entry(skill_id)
        if not entry.skill_path or not Path(entry.skill_path).exists():
            raise ValueError(f"Skill path {entry.skill_path!r} is not accessible")

        if any(run.status == "PENDING" for run in self.registry.list_scan_runs(entry.skill_id)):
            return entry, False
        if scan_options is not None:
            entry.scan_options = dict(scan_options)
            self.registry.update(entry)
        self._start_scan_run(entry, forced=True)
        self.registry.log_event(make_event("skill_rescan_requested", entry, actor=actor))
        return entry, True

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def list_skills(self, status: SkillStatus | None = None) -> list[RegistryEntry]:
        return self.registry.list_all(status)

    def list_skills_by_names(self, names: list[str] | set[str]) -> list[RegistryEntry]:
        return self.registry.list_by_names(names)

    def list_skills_by_statuses(self, statuses: list[SkillStatus]) -> list[RegistryEntry]:
        return self.registry.list_by_statuses(statuses)

    def list_skill_summaries(self, **kwargs: Any) -> dict[str, Any]:
        return self.registry.list_skill_summaries(**kwargs)

    def dashboard_stats(self) -> dict[str, Any]:
        return self.registry.dashboard_stats()

    def get_skill(self, skill_id_or_name: str, *, include_scan_report: bool = True) -> RegistryEntry | None:
        entry = self.registry.get_by_id(skill_id_or_name, include_scan_report=include_scan_report)
        return (
            entry
            or self.registry.get_by_family_id(skill_id_or_name, include_scan_report=include_scan_report)
            or self.registry.get_by_name(skill_id_or_name, include_scan_report=include_scan_report)
        )

    def get_trusted_skill(self, skill_id_or_name: str) -> RegistryEntry | None:
        entry = self.registry.get_by_id(skill_id_or_name)
        if entry and entry.is_loadable():
            return entry
        if entry and entry.family_id:
            return self.registry.get_by_family_id(entry.family_id, trusted=True)
        return self.registry.get_by_family_id(skill_id_or_name, trusted=True)

    def list_skill_versions(self, skill_id_or_name: str) -> list[RegistryEntry]:
        return self.registry.list_versions(skill_id_or_name)

    def list_scan_runs(self, version_id: str) -> list[ScanRun]:
        return self.registry.list_scan_runs(version_id)

    def list_scan_runs_for_versions(self, version_ids: list[str]) -> dict[str, list[ScanRun]]:
        return self.registry.list_scan_runs_for_versions(version_ids)

    def skill_version_activity(self, version_ids: list[str]) -> dict[str, dict[str, int | bool]]:
        return self.registry.skill_version_activity(version_ids)

    def get_governance_card(self, skill_id_or_name: str) -> dict[str, Any]:
        entry = self.get_skill(skill_id_or_name)
        if entry is None:
            raise KeyError(f"skill {skill_id_or_name!r} not found")
        return read_or_write_governance_card(entry, self.registry)

    def refresh_governance_card(self, skill_id_or_name: str) -> dict[str, Any]:
        entry = self.get_skill(skill_id_or_name)
        if entry is None:
            raise KeyError(f"skill {skill_id_or_name!r} not found")
        card = write_governance_card(entry, self.registry)
        if entry.vetting:
            entry.vetting.scan_report = {
                **entry.vetting.scan_report,
                "governance_card_path": card["path"],
                "governance_card_generated_at": card["generated_at"],
            }
            self.registry.update(entry)
        return card

    def list_review_queue(self) -> list[ReviewRequest]:
        return self.registry.list_review_queue()

    def list_reviewed_summaries(self) -> list[dict[str, Any]]:
        return self.registry.list_reviewed_summaries()

    def audit(
        self,
        since: datetime | None = None,
        skill_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        return self.registry.read_audit(since=since, skill_id=skill_id, limit=limit)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _require_entry(self, skill_id: str) -> RegistryEntry:
        # Lifecycle mutations must target one immutable version. Resolving a
        # family ID here can silently apply an action intended for an older
        # version to the family's latest version instead.
        entry = self.registry.get_by_id(skill_id)
        if entry is None:
            raise KeyError(f"Skill version ID {skill_id!r} not found in registry")
        return entry

    def _find_completed_scan_match(
        self,
        current_skill_id: str,
        content_fingerprint: str,
        scan_context_fingerprint: str,
    ) -> RegistryEntry | None:
        for candidate in self.registry.list_all():
            if candidate.skill_id == current_skill_id:
                continue
            if candidate.status == SkillStatus.PENDING or candidate.vetting is None:
                continue
            if candidate.content_fingerprint != content_fingerprint:
                continue
            if candidate.scan_context_fingerprint != scan_context_fingerprint:
                continue
            return candidate
        return None

    # ------------------------------------------------------------------ #
    # Prompt lifecycle delegation                                          #
    # ------------------------------------------------------------------ #

    def submit_prompt(self, *args, **kwargs):
        return self.prompts.submit(*args, **kwargs)

    def vet_prompt(self, *args, **kwargs):
        return self.prompts.vet(*args, **kwargs)

    def approve_prompt(self, *args, **kwargs):
        return self.prompts.approve(*args, **kwargs)

    def reject_prompt(self, *args, **kwargs):
        return self.prompts.reject(*args, **kwargs)

    def deploy_prompt(self, *args, **kwargs):
        return self.prompts.deploy(*args, **kwargs)

    def retire_prompt(self, *args, **kwargs):
        return self.prompts.retire(*args, **kwargs)

    def list_prompts(self, *args, **kwargs):
        return self.prompts.list_all(*args, **kwargs)

    def get_prompt(self, *args, **kwargs):
        return self.prompts.get_by_id(*args, **kwargs) or self.prompts.get_by_name(*args, **kwargs)

    def list_prompts_loadable(self, *args, **kwargs):
        return self.prompts.list_loadable(*args, **kwargs)

    def list_prompt_review_queue(self, *args, **kwargs):
        return self.prompts.list_review_queue(*args, **kwargs)

    def prompt_audit(self, *args, **kwargs):
        return self.prompts.read_audit(*args, **kwargs)

    def verify_prompt_signature(self, *args, **kwargs):
        return self.prompts.verify_signature(*args, **kwargs)

    # Private delegations for tests
    def _basic_prompt_scan(self, *args, **kwargs):
        return self.prompts._basic_scan(*args, **kwargs)

    def _require_prompt(self, *args, **kwargs):
        return self.prompts._require_prompt(*args, **kwargs)
