#!/usr/bin/env python3
"""Fail-closed preflight for the inputs required before P7-12 field execution."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "agent-security-bank-readiness@1"
ARCHITECTURES = ("amd64", "arm64")
MUTATION_CLASSES = (
    "read_only",
    "creates_records",
    "authorized_target_calls",
    "service_change",
    "platform_install",
)
REQUIRED_ROLES = {
    "administrator",
    "security_auditor",
    "ordinary_user",
    "security_operator",
    "target_owner",
    "mcp_owner",
    "platform_operator",
}
SENSITIVE_KEY = re.compile(
    r"(^|_)(password|passwd|secret|token|api_?key|authorization|cookie|credential|private_?key)($|_)",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(r"replace[-_ ]with|<[^>]+>|\b(todo|tbd)\b", re.IGNORECASE)


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or PLACEHOLDER.search(value):
        raise ValueError(f"{field} must be a non-placeholder string")
    return value.strip()


def parse_time(value: Any, field: str) -> datetime:
    text = require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def reject_sensitive_keys(value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise ValueError(f"{path}.{key} is a forbidden sensitive field")
            reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_sensitive_keys(nested, f"{path}[{index}]")


def read_provenance(package: Path, architecture: str, version: str, commit: str) -> dict[str, Any]:
    if not package.is_absolute() or not package.is_file() or package.is_symlink():
        raise ValueError(f"packages.{architecture} must be an absolute regular file")
    try:
        with tarfile.open(package, "r:gz") as archive:
            member = archive.getmember("agent-manager/release-provenance.json")
            if not member.isfile() or member.size > 64 * 1024:
                raise ValueError(f"packages.{architecture} has invalid release provenance")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"packages.{architecture} release provenance is unreadable")
            payload = json.loads(stream.read().decode("utf-8"))
    except (KeyError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"packages.{architecture} is not a valid offline package: {exc}") from exc
    expected = {
        "schema": "agent-manager-release-provenance@1",
        "version": version,
        "git_commit": commit,
        "architecture": architecture,
        "platform": f"linux/{architecture}",
        "archive_layout": "x86" if architecture == "amd64" else "arm",
        "source_mode": "git_clone",
        "worktree_dirty": False,
    }
    if not isinstance(payload, dict):
        raise ValueError(f"packages.{architecture} release provenance must be an object")
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise ValueError(
                f"packages.{architecture} provenance {field} mismatch: expected {expected_value!r}"
            )
    return payload


def validate(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    reject_sensitive_keys(config)
    environment = require_text(config.get("environment"), "environment")
    version = require_text(config.get("platform_version"), "platform_version")
    commit = require_text(config.get("git_commit"), "git_commit")
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit) is None:
        raise ValueError("git_commit must be a full hexadecimal identifier")

    people = config.get("people")
    if not isinstance(people, dict):
        raise ValueError("people must be an object")
    operator = require_text(people.get("operator"), "people.operator")
    reviewer = require_text(people.get("reviewer"), "people.reviewer")
    owner = require_text(people.get("acceptance_owner"), "people.acceptance_owner")
    if operator == reviewer:
        raise ValueError("people.operator and people.reviewer must be different")
    assignments = people.get("role_assignments")
    if not isinstance(assignments, dict):
        raise ValueError("people.role_assignments must be an object")
    missing_roles = sorted(REQUIRED_ROLES - set(assignments))
    if missing_roles:
        raise ValueError(f"role assignments missing: {', '.join(missing_roles)}")
    for role in REQUIRED_ROLES:
        require_text(assignments[role], f"people.role_assignments.{role}")

    window = config.get("change_window")
    if not isinstance(window, dict):
        raise ValueError("change_window must be an object")
    require_text(window.get("reference"), "change_window.reference")
    start = parse_time(window.get("starts_at"), "change_window.starts_at")
    end = parse_time(window.get("ends_at"), "change_window.ends_at")
    if end <= start:
        raise ValueError("change_window.ends_at must be after starts_at")

    approvals = config.get("approvals")
    if not isinstance(approvals, dict):
        raise ValueError("approvals must be an object")
    for mutation_class in MUTATION_CLASSES:
        require_text(approvals.get(mutation_class), f"approvals.{mutation_class}")

    hosts = config.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("hosts must be an object")
    for architecture in ARCHITECTURES:
        host = hosts.get(architecture)
        if not isinstance(host, dict):
            raise ValueError(f"hosts.{architecture} must be an object")
        require_text(host.get("id"), f"hosts.{architecture}.id")
        if host.get("architecture") != architecture:
            raise ValueError(f"hosts.{architecture}.architecture must be {architecture}")

    packages = config.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("packages must be an object")
    provenances = {}
    for architecture in ARCHITECTURES:
        package = Path(require_text(packages.get(architecture), f"packages.{architecture}"))
        provenances[architecture] = read_provenance(package, architecture, version, commit)

    authorized_agent = config.get("authorized_agent")
    if not isinstance(authorized_agent, dict):
        raise ValueError("authorized_agent must be an object")
    for field in (
        "target_id",
        "owner",
        "approval_reference",
        "network_boundary",
        "tls_profile",
        "evaluator_model",
    ):
        require_text(authorized_agent.get(field), f"authorized_agent.{field}")
    budget = authorized_agent.get("budget")
    if not isinstance(budget, dict):
        raise ValueError("authorized_agent.budget must be an object")
    for field in ("max_rounds", "max_tokens", "max_cost", "max_response_bytes"):
        value = budget.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"authorized_agent.budget.{field} must be a positive number")
    require_text(budget.get("cost_currency"), "authorized_agent.budget.cost_currency")

    mcp = config.get("mcp")
    if not isinstance(mcp, dict):
        raise ValueError("mcp must be an object")
    for field in ("target_id", "owner", "audit_source"):
        require_text(mcp.get(field), f"mcp.{field}")

    storage = config.get("evidence_storage")
    if not isinstance(storage, dict):
        raise ValueError("evidence_storage must be an object")
    require_text(storage.get("location_reference"), "evidence_storage.location_reference")
    require_text(storage.get("retention_policy"), "evidence_storage.retention_policy")

    return {
        "schema": "agent-security-bank-readiness-result@1",
        "ready": True,
        "environment": environment,
        "platform_version": version,
        "git_commit": commit,
        "operator": operator,
        "reviewer": reviewer,
        "acceptance_owner": owner,
        "architectures": list(ARCHITECTURES),
        "verified_package_provenance": {
            architecture: {
                "version": provenances[architecture]["version"],
                "git_commit": provenances[architecture]["git_commit"],
                "architecture": provenances[architecture]["architecture"],
            }
            for architecture in ARCHITECTURES
        },
        "checked_mutation_classes": list(MUTATION_CLASSES),
        "checked_roles": sorted(REQUIRED_ROLES),
        "note": "No target connection or environment mutation was performed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        if not args.config.is_absolute() or not args.config.is_file() or args.config.is_symlink():
            raise ValueError("config must be an explicit absolute regular file")
        payload = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("config root must be an object")
        result = validate(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"schema": "agent-security-bank-readiness-result@1", "ready": False, "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
