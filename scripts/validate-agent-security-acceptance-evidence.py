#!/usr/bin/env python3
"""Validate a P7-12 bank acceptance evidence directory without exposing its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

CASE_IDS = {f"BANK-{index:02d}" for index in range(1, 16)}
STATUSES = {"passed", "failed", "unverified", "not_applicable"}
OVERALL_CONCLUSIONS = {"unverified", "failed", "pending_review", "passed"}
ISSUE_STATUSES = {"open", "resolved", "accepted"}
REQUIRED_ISSUES = {f"GAP-{index:02d}" for index in range(1, 8)}
OPERATIONAL_ISSUES = {"GAP-01", "GAP-02", "GAP-03", "GAP-04"}
CASE_MUTATION_CLASSES = {
    "BANK-01": "read_only", "BANK-02": "read_only", "BANK-03": "creates_records",
    "BANK-04": "authorized_target_calls", "BANK-05": "creates_records",
    "BANK-06": "creates_records", "BANK-07": "authorized_target_calls",
    "BANK-08": "creates_records", "BANK-09": "creates_records", "BANK-10": "service_change",
    "BANK-11": "service_change", "BANK-12": "platform_install", "BANK-13": "platform_install",
    "BANK-14": "read_only", "BANK-15": "creates_records",
}
PLACEHOLDER_MARKERS = ("replace-with", "example", "填写", "待填写")
TEXT_EVIDENCE_SUFFIXES = {
    ".csv", ".env", ".html", ".json", ".jsonl", ".log", ".md", ".txt", ".xml", ".yaml", ".yml"
}
MAX_SECRET_SCAN_BYTES = 64 * 1024 * 1024
REDACTED_VALUES = {"", "***", "masked", "null", "redacted", "removed", "<redacted>", "[redacted]"}


def fail(message: str) -> None:
    raise ValueError(message)


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{field} must be a non-empty string")
    normalized = value.strip()
    if any(marker in normalized.lower() for marker in PLACEHOLDER_MARKERS):
        fail(f"{field} still contains a placeholder")
    return normalized


def safe_relative_path(value: object, field: str) -> PurePosixPath:
    text = require_text(value, field)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        fail(f"{field} must be a safe relative path")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_timestamp(value: object, field: str) -> datetime:
    text = require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{field} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        fail(f"{field} must include a timezone")
    return parsed


def load_manifest(evidence_dir: Path, manifest_name: object) -> dict[str, str]:
    relative = safe_relative_path(manifest_name, "sha256_manifest")
    manifest_path = evidence_dir / relative
    if not manifest_path.is_file() or manifest_path.is_symlink():
        fail(f"sha256 manifest is missing: {relative}")

    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
        if match is None:
            fail(f"invalid sha256 manifest line {line_number}")
        relative_path = safe_relative_path(match.group(2).removeprefix("./"), f"manifest line {line_number}")
        key = relative_path.as_posix()
        if key in entries:
            fail(f"duplicate sha256 manifest entry: {key}")
        entries[key] = match.group(1).lower()
    if not entries:
        fail("sha256 manifest is empty")
    return entries


def validate_evidence_file(evidence_dir: Path, relative: PurePosixPath, manifest: dict[str, str]) -> None:
    key = relative.as_posix()
    path = evidence_dir / relative
    if not path.is_file() or path.is_symlink():
        fail(f"referenced evidence file is missing: {key}")
    expected = manifest.get(key)
    if expected is None:
        fail(f"referenced evidence is absent from sha256 manifest: {key}")
    actual = sha256(path)
    if actual != expected:
        fail(f"sha256 mismatch for evidence: {key}")


def validate_manifest_tree(
    evidence_dir: Path, manifest_relative: PurePosixPath, manifest: dict[str, str]
) -> None:
    actual_files: set[str] = set()
    for path in evidence_dir.rglob("*"):
        if path.is_symlink():
            fail("evidence directory must not contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            fail(f"evidence directory contains a non-regular file: {path.relative_to(evidence_dir)}")
        relative = path.relative_to(evidence_dir).as_posix()
        if relative != manifest_relative.as_posix():
            actual_files.add(relative)
    manifest_files = set(manifest)
    if actual_files != manifest_files:
        missing_from_manifest = sorted(actual_files - manifest_files)
        missing_from_directory = sorted(manifest_files - actual_files)
        fail(
            "sha256 manifest file set mismatch; "
            f"unlisted={missing_from_manifest or ['none']}; missing={missing_from_directory or ['none']}"
        )
    for relative, expected in manifest.items():
        path = evidence_dir / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            fail(f"manifest entry is not a regular file: {relative}")
        if sha256(path) != expected:
            fail(f"sha256 mismatch for manifest entry: {relative}")


def is_redacted(value: str) -> bool:
    normalized = value.strip().strip("\"'").rstrip(",;}").lower()
    return normalized in REDACTED_VALUES or set(normalized) <= {"*"}


def validate_no_obvious_secrets(evidence_dir: Path, manifest: dict[str, str]) -> None:
    patterns = (
        ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
        ("JWT", re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])")),
        ("credential-bearing URL", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    )
    value_patterns = (
        ("Bearer authorization", re.compile(r"(?im)^\s*Authorization\s*:\s*Bearer\s+(\S+)")),
        ("Cookie header", re.compile(r"(?im)^\s*(?:Cookie|Set-Cookie)\s*:\s*(\S.*)$")),
        (
            "sensitive field",
            re.compile(
                r"(?im)(?:^|[,\s{])['\"]?(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)['\"]?\s*[:=]\s*([^\s,}\]]+)"
            ),
        ),
    )
    for relative in sorted(manifest):
        path = evidence_dir / PurePosixPath(relative)
        if path.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
            continue
        if path.stat().st_size > MAX_SECRET_SCAN_BYTES:
            fail(f"text evidence exceeds the 64 MiB secret-scan limit: {relative}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail(f"text evidence is not valid UTF-8: {relative}")
        for category, pattern in patterns:
            if pattern.search(content):
                fail(f"obvious plaintext secret detected ({category}): {relative}")
        for category, pattern in value_patterns:
            for match in pattern.finditer(content):
                if not is_redacted(match.group(1)):
                    fail(f"obvious plaintext secret detected ({category}): {relative}")


def validate_release_provenance(
    evidence_dir: Path,
    payload: dict[str, object],
    manifest: dict[str, str],
    require_complete: bool,
) -> None:
    provenance_paths = payload.get("release_provenance")
    if not isinstance(provenance_paths, dict) or set(provenance_paths) != {"amd64", "arm64"}:
        fail("release_provenance must provide amd64 and arm64 files")

    expected_version = payload["platform_version"]
    expected_commit = payload["git_commit"]
    for architecture in ("amd64", "arm64"):
        relative = safe_relative_path(provenance_paths[architecture], f"release_provenance.{architecture}")
        validate_evidence_file(evidence_dir, relative, manifest)
        try:
            provenance = json.loads((evidence_dir / relative).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid release provenance JSON for {architecture}: {exc}")
        if not isinstance(provenance, dict):
            fail(f"release provenance for {architecture} must be an object")
        if provenance.get("schema") != "agent-manager-release-provenance@1":
            fail(f"unsupported release provenance schema for {architecture}")
        if provenance.get("version") != expected_version:
            fail(f"release provenance version mismatch for {architecture}")
        if provenance.get("git_commit") != expected_commit:
            fail(f"release provenance commit mismatch for {architecture}")
        if provenance.get("architecture") != architecture:
            fail(f"release provenance architecture mismatch for {architecture}")
        if provenance.get("platform") != f"linux/{architecture}":
            fail(f"release provenance platform mismatch for {architecture}")
        if require_complete and provenance.get("worktree_dirty") is not False:
            fail(f"formal release provenance must be clean for {architecture}")
        if require_complete and provenance.get("source_mode") != "git_clone":
            fail(f"formal release provenance must use git_clone for {architecture}")


def validate_remaining_issues(
    evidence_dir: Path,
    payload: dict[str, object],
    manifest: dict[str, str],
    *,
    require_complete: bool,
    completed_at: datetime | None,
) -> None:
    relative = safe_relative_path(payload.get("remaining_issues"), "remaining_issues")
    validate_evidence_file(evidence_dir, relative, manifest)
    try:
        issue_payload = json.loads((evidence_dir / relative).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid remaining issues JSON: {exc}")
    if not isinstance(issue_payload, dict) or issue_payload.get("schema") != "agent-security-bank-remaining-issues@1":
        fail("unsupported remaining issues schema")
    issues = issue_payload.get("issues")
    if not isinstance(issues, list):
        fail("remaining issues must be a list")
    by_id: dict[str, dict[str, object]] = {}
    counts = {status: 0 for status in ISSUE_STATUSES}
    for index, item in enumerate(issues):
        if not isinstance(item, dict):
            fail(f"remaining issues[{index}] must be an object")
        issue_id = require_text(item.get("id"), f"remaining issues[{index}].id")
        if re.fullmatch(r"GAP-[0-9]{2,}", issue_id) is None:
            fail(f"invalid remaining issue id: {issue_id}")
        if issue_id in by_id:
            fail(f"duplicate remaining issue: {issue_id}")
        by_id[issue_id] = item
        status = item.get("status")
        if status not in ISSUE_STATUSES:
            fail(f"invalid remaining issue status for {issue_id}: {status}")
        counts[str(status)] += 1
        require_text(item.get("title"), f"{issue_id}.title")
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            fail(f"{issue_id}.evidence must be a list")
        evidence_paths = [
            safe_relative_path(value, f"{issue_id}.evidence[{evidence_index}]")
            for evidence_index, value in enumerate(evidence)
        ]
        for evidence_path in evidence_paths:
            validate_evidence_file(evidence_dir, evidence_path, manifest)
        if status == "open":
            require_text(item.get("reason"), f"{issue_id}.reason")
            require_text(item.get("owner"), f"{issue_id}.owner")
            require_text(item.get("closure_condition"), f"{issue_id}.closure_condition")
        elif status == "resolved":
            require_text(item.get("resolution"), f"{issue_id}.resolution")
            if not evidence_paths:
                fail(f"resolved remaining issue requires evidence: {issue_id}")
        else:
            require_text(item.get("reason"), f"{issue_id}.reason")
            require_text(item.get("owner"), f"{issue_id}.owner")
            require_text(item.get("closure_condition"), f"{issue_id}.closure_condition")
            require_text(item.get("risk_acceptance_reference"), f"{issue_id}.risk_acceptance_reference")
            review_at = require_timestamp(item.get("review_at"), f"{issue_id}.review_at")
            if completed_at is not None and review_at <= completed_at:
                fail(f"risk acceptance review must be later than completion for {issue_id}")
            if not evidence_paths:
                fail(f"accepted remaining issue requires redacted approval evidence: {issue_id}")
    missing = REQUIRED_ISSUES - set(by_id)
    if missing:
        fail(f"required remaining issues are missing: {', '.join(sorted(missing))}")
    if issue_payload.get("summary") != counts:
        fail(f"remaining issue summary mismatch: expected {counts}")
    if require_complete:
        if counts["open"]:
            fail("complete acceptance cannot contain open remaining issues")
        not_resolved = sorted(
            issue_id for issue_id in OPERATIONAL_ISSUES if by_id[issue_id].get("status") != "resolved"
        )
        if not_resolved:
            fail(f"operational remaining issues must be resolved: {', '.join(not_resolved)}")


def validate_signoff(
    evidence_dir: Path,
    payload: dict[str, object],
    manifest: dict[str, str],
    *,
    require_complete: bool,
    reviewer: str,
    completed_at: datetime | None,
) -> None:
    signoff = payload.get("signoff")
    if signoff is None:
        if require_complete:
            fail("complete acceptance requires a signoff record")
        return
    if not isinstance(signoff, dict) or signoff.get("schema") != "agent-security-bank-signoff@1":
        fail("unsupported signoff schema")
    if require_text(signoff.get("reviewer"), "signoff.reviewer") != reviewer:
        fail("signoff reviewer does not match the independent reviewer")
    signed_at = require_timestamp(signoff.get("signed_at"), "signoff.signed_at")
    if completed_at is None or signed_at != completed_at:
        fail("signoff timestamp must match acceptance completion")
    require_text(signoff.get("signoff_reference"), "signoff.signoff_reference")
    require_text(signoff.get("evidence_storage_reference"), "signoff.evidence_storage_reference")
    evidence = signoff.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        fail("signoff requires at least one redacted evidence file")
    for index, value in enumerate(evidence):
        relative = safe_relative_path(value, f"signoff.evidence[{index}]")
        validate_evidence_file(evidence_dir, relative, manifest)


def validate(evidence_dir: Path, require_complete: bool) -> dict[str, int]:
    if not evidence_dir.is_absolute():
        fail("evidence directory must be an absolute path")
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        fail(f"evidence directory does not exist: {evidence_dir}")
    if any(path.is_symlink() for path in evidence_dir.rglob("*")):
        fail("evidence directory must not contain symbolic links")

    results_path = evidence_dir / "acceptance-results.json"
    if not results_path.is_file() or results_path.is_symlink():
        fail("acceptance-results.json is missing")
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "agent-security-bank-acceptance@1":
        fail("unsupported acceptance results schema")

    require_text(payload.get("environment"), "environment")
    require_text(payload.get("platform_version"), "platform_version")
    commit = require_text(payload.get("git_commit"), "git_commit")
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit) is None:
        fail("git_commit must be a full hexadecimal commit identifier")

    architectures = payload.get("architectures")
    if not isinstance(architectures, list) or set(architectures) != {"amd64", "arm64"}:
        fail("architectures must contain exactly amd64 and arm64")
    started_at = require_timestamp(payload.get("started_at"), "started_at")
    completed_value = payload.get("completed_at")
    completed_at = None
    if completed_value is not None:
        completed_at = require_timestamp(completed_value, "completed_at")
    elif require_complete:
        fail("completed_at is required for a complete acceptance")
    if completed_at is not None and completed_at < started_at:
        fail("completed_at must not be earlier than started_at")
    operator = require_text(payload.get("operator"), "operator")
    reviewer = require_text(payload.get("reviewer"), "reviewer")
    if operator == reviewer:
        fail("operator and reviewer must be different people")
    sensitive_data_reviewed = payload.get("sensitive_data_reviewed")
    if not isinstance(sensitive_data_reviewed, bool):
        fail("sensitive_data_reviewed must be a boolean")
    if require_complete and sensitive_data_reviewed is not True:
        fail("sensitive_data_reviewed must be true")

    manifest_relative = safe_relative_path(payload.get("sha256_manifest"), "sha256_manifest")
    manifest = load_manifest(evidence_dir, manifest_relative.as_posix())
    validate_manifest_tree(evidence_dir, manifest_relative, manifest)
    validate_no_obvious_secrets(evidence_dir, manifest)
    validate_evidence_file(evidence_dir, PurePosixPath("acceptance-results.json"), manifest)
    validate_release_provenance(evidence_dir, payload, manifest, require_complete)
    validate_remaining_issues(
        evidence_dir,
        payload,
        manifest,
        require_complete=require_complete,
        completed_at=completed_at,
    )
    validate_signoff(
        evidence_dir,
        payload,
        manifest,
        require_complete=require_complete,
        reviewer=reviewer,
        completed_at=completed_at,
    )
    execution_starts = payload.get("execution_starts", {})
    if not isinstance(execution_starts, dict):
        fail("execution_starts must be an object")
    if not set(execution_starts).issubset(CASE_IDS):
        fail("execution_starts contains an unknown BANK case")
    if require_complete and set(execution_starts) != CASE_IDS:
        fail("complete acceptance requires a start receipt for every BANK case")
    for case_id, receipt_value in execution_starts.items():
        relative = safe_relative_path(receipt_value, f"execution_starts.{case_id}")
        validate_evidence_file(evidence_dir, relative, manifest)
        try:
            receipt = json.loads((evidence_dir / relative).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid start receipt JSON for {case_id}: {exc}")
        if not isinstance(receipt, dict) or receipt.get("schema") != "agent-security-bank-case-start@1":
            fail(f"invalid start receipt schema for {case_id}")
        if receipt.get("case_id") != case_id:
            fail(f"start receipt case id mismatch for {case_id}")
        if receipt.get("mutation_class") != CASE_MUTATION_CLASSES[case_id]:
            fail(f"start receipt mutation class mismatch for {case_id}")
        if require_text(receipt.get("operator"), f"{case_id}.start.operator") != operator:
            fail(f"start receipt operator mismatch for {case_id}")
        receipt_started = require_timestamp(receipt.get("started_at"), f"{case_id}.start.started_at")
        if receipt_started < started_at:
            fail(f"start receipt predates acceptance workspace for {case_id}")
        if completed_at is not None and receipt_started > completed_at:
            fail(f"start receipt is later than acceptance completion for {case_id}")
        window = receipt.get("change_window")
        if not isinstance(window, dict):
            fail(f"start receipt change_window must be an object for {case_id}")
        require_text(window.get("reference"), f"{case_id}.start.change_window.reference")
        window_start = require_timestamp(window.get("starts_at"), f"{case_id}.start.change_window.starts_at")
        window_end = require_timestamp(window.get("ends_at"), f"{case_id}.start.change_window.ends_at")
        if not window_start <= receipt_started <= window_end:
            fail(f"start receipt is outside the approved change window for {case_id}")
        require_text(receipt.get("approval_reference"), f"{case_id}.start.approval_reference")
        require_text(receipt.get("scope_reference"), f"{case_id}.start.scope_reference")
        config_hash = require_text(
            receipt.get("readiness_config_sha256"), f"{case_id}.start.readiness_config_sha256"
        )
        if re.fullmatch(r"[0-9a-fA-F]{64}", config_hash) is None:
            fail(f"invalid readiness config sha256 for {case_id}")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        fail("cases must be a list")

    by_id: dict[str, dict[str, object]] = {}
    counts = {status: 0 for status in STATUSES}
    for index, item in enumerate(cases):
        if not isinstance(item, dict):
            fail(f"cases[{index}] must be an object")
        case_id = require_text(item.get("id"), f"cases[{index}].id")
        if case_id in by_id:
            fail(f"duplicate acceptance case: {case_id}")
        by_id[case_id] = item
        status = item.get("status")
        if status not in STATUSES:
            fail(f"invalid status for {case_id}: {status}")
        counts[str(status)] += 1

        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            fail(f"evidence for {case_id} must be a list")
        evidence_paths = [
            safe_relative_path(value, f"{case_id}.evidence[{evidence_index}]")
            for evidence_index, value in enumerate(evidence)
        ]
        if status == "passed" and not evidence_paths:
            fail(f"passed case has no evidence: {case_id}")
        for relative in evidence_paths:
            validate_evidence_file(evidence_dir, relative, manifest)

        if status in {"failed", "unverified"}:
            require_text(item.get("reason"), f"{case_id}.reason")
            require_text(item.get("owner"), f"{case_id}.owner")
            require_text(item.get("closure_condition"), f"{case_id}.closure_condition")
        if status == "not_applicable":
            require_text(item.get("rationale"), f"{case_id}.rationale")

    actual_ids = set(by_id)
    if actual_ids != CASE_IDS:
        missing = ", ".join(sorted(CASE_IDS - actual_ids)) or "none"
        extra = ", ".join(sorted(actual_ids - CASE_IDS)) or "none"
        fail(f"acceptance case set mismatch; missing={missing}; extra={extra}")

    summary = payload.get("summary")
    expected_summary = {
        "passed": counts["passed"],
        "failed": counts["failed"],
        "unverified": counts["unverified"],
        "not_applicable": counts["not_applicable"],
    }
    if summary != expected_summary:
        fail(f"summary does not match case results: expected {expected_summary}")
    if require_complete and counts != {"passed": 15, "failed": 0, "unverified": 0, "not_applicable": 0}:
        fail("complete acceptance requires all 15 mandatory cases to pass")

    overall = payload.get("overall_conclusion")
    if overall not in OVERALL_CONCLUSIONS:
        fail(f"invalid overall_conclusion: {overall}")
    if require_complete and overall != "passed":
        fail("overall_conclusion must be passed for a complete acceptance")
    if overall == "passed" and counts != {"passed": 15, "failed": 0, "unverified": 0, "not_applicable": 0}:
        fail("overall_conclusion can be passed only when all 15 mandatory cases pass")
    return expected_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        summary = validate(args.evidence_dir, args.require_complete)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"acceptance evidence validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"valid": True, "complete": args.require_complete, "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
