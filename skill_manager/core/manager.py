"""
SkillManager — high-level API that wires together vetting, registry, signing,
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
    RiskLevel,
    SkillStatus,
    SourceInfo,
    SkillOrigin,
)
from .policy import CompanyPolicy
from .registry import Registry, make_event
from .runtime import RuntimeGuard
from .signer import compute_signature
from .vetting import VettingPipeline, _load_manifest

logger = logging.getLogger(__name__)


class SkillManager:
    """
    Lifecycle manager for AI agent skills.

    Usage::

        mgr = SkillManager()

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
        self.vetting = VettingPipeline(self.policy)
        self.runtime = RuntimeGuard(self.registry)

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
    ) -> RegistryEntry:
        """
        Vet a skill and submit it to the registry.

        The skill is scanned, policy-checked, and assigned a status:
        - APPROVED  — auto-approved (risk below threshold, no violations)
        - VETTED    — needs human review
        - REJECTED  — auto-rejected (EXTREME risk or blocking violation)

        Returns the new RegistryEntry.
        """
        entry = self.create_pending_submission(skill_path, source=source, author=author)
        return self.process_pending_submission(
            entry.skill_id,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
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
    ) -> RegistryEntry:
        entry = self._require_entry(skill_id)
        skill_path = Path(entry.skill_path or "").resolve()
        source = entry.source

        logger.info("Vetting skill at %s ...", skill_path)

        vetting_result, violations, name, description, allowed_tools = self.vetting.vet(
            skill_path,
            source,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
            use_sandbox=use_sandbox,
        )

        status = self.policy.decide(vetting_result.risk_level, source, violations)
        declared_tools_valid = not any(v.rule in ("tool_not_in_allowlist", "blocked_permission") for v in violations)

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

        self.registry.update(entry)
        self.registry.log_event(make_event(
            "skill_processing_completed",
            entry,
            details={
                "risk_level": vetting_result.risk_level.value,
                "status": status.value,
                "violations": [v.rule for v in violations],
            },
        ))

        if status == SkillStatus.VETTED:
            self.registry.enqueue_review(ReviewRequest(
                skill_id=entry.skill_id,
                skill_name=name,
                risk_level=vetting_result.risk_level,
                findings_summary={
                    "critical": vetting_result.critical_count,
                    "high": vetting_result.high_count,
                    "medium": vetting_result.medium_count,
                    "low": vetting_result.low_count,
                },
                submitted_at=entry.submitted_at,
                notes="; ".join(vetting_result.policy_notes) if vetting_result.policy_notes else None,
            ))
            self.registry.log_event(make_event("skill_queued_for_review", entry))

        self.registry.log_event(make_event(
            "skill_vetted", entry,
            details={"risk_level": vetting_result.risk_level.value, "status": status.value},
        ))

        logger.info("Processed skill %r: status=%s risk=%s", name, status.value, vetting_result.risk_level.value)
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
