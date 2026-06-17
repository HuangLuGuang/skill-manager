"""
AgentManager — high-level API that wires together vetting, registry, signing,
policy, and runtime guard.

This is the main entry point for programmatic use.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    AuditEvent,
    RegistryEntry,
    ReviewRequest,
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
        no_cache: bool = False,
    ) -> RegistryEntry:
        """
        Vet a skill and submit it to the registry.
        """
        entry = self.create_pending_submission(skill_path, source=source, author=author)
        return self.process_pending_submission(
            entry.skill_id,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
            no_cache=no_cache,
        )

    def create_pending_submission(
        self,
        skill_path: str | Path,
        source: SourceInfo | None = None,
        author: str | None = None,
    ) -> RegistryEntry:
        skill_path = Path(skill_path).resolve()

        if source is None:
            source = SourceInfo(origin=SkillOrigin.LOCAL, author=author)

        try:
            name, description, allowed_tools, _license = _load_manifest(skill_path)
        except Exception:
            name = skill_path.name
            description = ""
            allowed_tools = []

        entry = RegistryEntry(
            skill_id=str(uuid.uuid4()),
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

    def process_pending_submission(
        self,
        skill_id: str,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
        no_cache: bool = False,
    ) -> RegistryEntry:
        entry = self._require_entry(skill_id)
        skill_path = Path(entry.skill_path or "").resolve()
        source = entry.source
        content_fingerprint = compute_content_fingerprint(skill_path)
        scan_context_fingerprint = compute_scan_context_fingerprint(
            self.policy,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
        )
        scan_cache_key = compute_scan_cache_key(content_fingerprint, scan_context_fingerprint)
        entry.content_fingerprint = content_fingerprint
        entry.scan_context_fingerprint = scan_context_fingerprint
        entry.scan_cache_key = scan_cache_key
        self.registry.update(entry)

        if not no_cache:
            cached = self.scan_cache.get(scan_cache_key)
            if cached:
                cached_entry = self.registry.get_by_id(cached.get("skill_id", ""))
                if cached_entry and cached_entry.vetting and cached_entry.status != SkillStatus.PENDING:
                    return self._reuse_scan_result(entry, cached_entry, skill_path)

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
                return self._reuse_scan_result(entry, matching_entry, skill_path)

        logger.info("Vetting skill at %s ...", skill_path)

        vetting_result, violations, name, description, allowed_tools = self.vetting.vet(
            skill_path,
            source,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
        )

        # 根据最终 risk_level 决定状态
        status = self.policy.decide(vetting_result.risk_level, violations)
        declared_tools_valid = not any(v.rule in ("tool_not_in_allowlist", "blocked_permission") for v in violations)
        vetting_result.scan_report = {
            **vetting_result.scan_report,
            "scan_reused": False,
            "content_fingerprint": content_fingerprint,
            "scan_context_fingerprint": scan_context_fingerprint,
            "scan_cache_key": scan_cache_key,
        }

        entry.name = name
        entry.description = description
        entry.status = status
        entry.risk_level = vetting_result.risk_level
        entry.vetting = vetting_result
        entry.allowed_tools = allowed_tools
        entry.declared_tools_valid = declared_tools_valid

        if status == SkillStatus.APPROVED:
            entry.signature = compute_signature(skill_path)
            entry.approved_at = datetime.now(timezone.utc)
            entry.approved_by = "auto-policy"

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
                findings_summary={"total": vetting_result.findings_count},
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
        return entry

    def _reuse_scan_result(
        self,
        entry: RegistryEntry,
        cached_entry: RegistryEntry,
        skill_path: Path,
    ) -> RegistryEntry:
        entry.name = cached_entry.name
        entry.description = cached_entry.description
        entry.status = cached_entry.status
        entry.risk_level = cached_entry.risk_level
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
                "content_fingerprint": entry.content_fingerprint,
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
            self.registry.enqueue_review(ReviewRequest(
                skill_id=entry.skill_id,
                skill_name=entry.name,
                risk_level=entry.risk_level,
                findings_summary={"total": entry.vetting.findings_count if entry.vetting else 0},
                submitted_at=entry.submitted_at,
                notes="复用历史扫描结果，仍需人工审核。",
            ))

        self.registry.update(entry)
        self.registry.log_event(make_event(
            "skill_scan_reused",
            entry,
            details={
                "reused_from_skill_id": cached_entry.skill_id,
                "content_fingerprint": entry.content_fingerprint,
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
        entry.status = SkillStatus.REJECTED
        entry.rejection_reason = reason
        self.registry.update(entry)
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
        Approve a VETTED skill.

        Signs the skill and moves it to APPROVED status.
        """
        entry = self._require_entry(skill_id)

        if entry.status != SkillStatus.VETTED:
            raise ValueError(
                f"Skill {entry.name!r} is {entry.status.value}, not VETTED. "
                "Only VETTED skills can be approved."
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
            details={"note": note},
        ))

        logger.info("Approved skill %r by %r", entry.name, approver)
        return entry

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

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def list_skills(self, status: SkillStatus | None = None) -> list[RegistryEntry]:
        return self.registry.list_all(status)

    def get_skill(self, skill_id_or_name: str) -> RegistryEntry | None:
        entry = self.registry.get_by_id(skill_id_or_name)
        return entry or self.registry.get_by_name(skill_id_or_name)

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
        entry = self.registry.get_by_id(skill_id)
        if entry is None:
            raise KeyError(f"Skill ID {skill_id!r} not found in registry")
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
