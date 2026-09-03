#!/usr/bin/env python3
"""Update and complete a P7-12 bank acceptance workspace without hand-editing summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

CASE_IDS = {f"BANK-{index:02d}" for index in range(1, 16)}
STATUSES = {"passed", "failed", "unverified", "not_applicable"}
ISSUE_STATUSES = {"open", "resolved", "accepted"}
CASE_MUTATION_CLASSES = {
    "BANK-01": "read_only",
    "BANK-02": "read_only",
    "BANK-03": "creates_records",
    "BANK-04": "authorized_target_calls",
    "BANK-05": "creates_records",
    "BANK-06": "creates_records",
    "BANK-07": "authorized_target_calls",
    "BANK-08": "creates_records",
    "BANK-09": "creates_records",
    "BANK-10": "service_change",
    "BANK-11": "service_change",
    "BANK-12": "platform_install",
    "BANK-13": "platform_install",
    "BANK-14": "read_only",
    "BANK-15": "creates_records",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_text(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def safe_evidence_path(evidence_dir: Path, value: str) -> str:
    relative = PurePosixPath(require_text(value, "evidence path"))
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        raise ValueError(f"evidence path must be safe and relative: {value}")
    path = evidence_dir / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"evidence file is missing or symbolic: {relative}")
    return relative.as_posix()


def load_workspace(evidence_dir: Path) -> tuple[Path, dict[str, object]]:
    if not evidence_dir.is_absolute() or not evidence_dir.is_dir():
        raise ValueError("evidence directory must be an existing absolute directory")
    if any(path.is_symlink() for path in evidence_dir.rglob("*")):
        raise ValueError("evidence directory must not contain symbolic links")
    results_path = evidence_dir / "acceptance-results.json"
    if not results_path.is_file():
        raise ValueError("acceptance-results.json is missing")
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "agent-security-bank-acceptance@1":
        raise ValueError("unsupported acceptance results schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or {item.get("id") for item in cases if isinstance(item, dict)} != CASE_IDS:
        raise ValueError("acceptance workspace must contain exactly BANK-01 through BANK-15")
    return results_path, payload


def update_summary(payload: dict[str, object]) -> None:
    cases = payload["cases"]
    assert isinstance(cases, list)
    counts = {status: 0 for status in STATUSES}
    for item in cases:
        assert isinstance(item, dict)
        status = item.get("status")
        if status not in STATUSES:
            raise ValueError(f"invalid status for {item.get('id')}: {status}")
        counts[str(status)] += 1
    payload["summary"] = {
        "passed": counts["passed"],
        "failed": counts["failed"],
        "unverified": counts["unverified"],
        "not_applicable": counts["not_applicable"],
    }
    if counts["failed"]:
        payload["overall_conclusion"] = "failed"
    elif counts["passed"] == 15:
        payload["overall_conclusion"] = "pending_review"
    else:
        payload["overall_conclusion"] = "unverified"


def regenerate_manifest(evidence_dir: Path) -> None:
    lines = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            lines.append(f"{sha256(path)}  {path.relative_to(evidence_dir).as_posix()}")
    if not lines:
        raise ValueError("refusing to write an empty sha256 manifest")
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=evidence_dir,
        prefix=".manifest.",
        delete=False,
    )
    try:
        with temporary:
            temporary.write("\n".join(lines) + "\n")
        os.replace(temporary.name, evidence_dir / "manifest.sha256")
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def write_results(path: Path, payload: dict[str, object]) -> None:
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".acceptance-results.",
        delete=False,
    )
    try:
        with temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary.name, path)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        with temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary.name, path)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def persist_and_validate(
    evidence_dir: Path,
    results_path: Path,
    payload: dict[str, object],
    *,
    require_complete: bool,
) -> None:
    original_results = results_path.read_bytes()
    manifest_path = evidence_dir / "manifest.sha256"
    original_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    try:
        write_results(results_path, payload)
        regenerate_manifest(evidence_dir)
        validator = Path(__file__).with_name("validate-agent-security-acceptance-evidence.py")
        command = [sys.executable, str(validator), "--evidence-dir", str(evidence_dir)]
        if require_complete:
            command.append("--require-complete")
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or "acceptance validation failed")
    except Exception:
        results_path.write_bytes(original_results)
        if original_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_bytes(original_manifest)
        raise


def update_case(args: argparse.Namespace) -> dict[str, object]:
    evidence_dir = args.evidence_dir
    results_path, payload = load_workspace(evidence_dir)
    if args.case_id not in CASE_IDS:
        raise ValueError("case id must be BANK-01 through BANK-15")
    evidence = [safe_evidence_path(evidence_dir, value) for value in args.evidence]
    item: dict[str, object] = {"id": args.case_id, "status": args.status, "evidence": evidence}
    if args.status == "passed":
        if not evidence:
            raise ValueError("a passed case requires at least one evidence file")
    elif args.status in {"failed", "unverified"}:
        item.update(
            {
                "reason": require_text(args.reason, "reason"),
                "owner": require_text(args.owner, "owner"),
                "closure_condition": require_text(args.closure_condition, "closure condition"),
            }
        )
    else:
        item["rationale"] = require_text(args.rationale, "rationale")

    cases = payload["cases"]
    assert isinstance(cases, list)
    payload["cases"] = [item if case.get("id") == args.case_id else case for case in cases]
    payload["completed_at"] = None
    payload["sensitive_data_reviewed"] = False
    payload.pop("signoff", None)
    update_summary(payload)
    persist_and_validate(evidence_dir, results_path, payload, require_complete=False)
    return payload["summary"]  # type: ignore[return-value]


def start_case(args: argparse.Namespace) -> dict[str, object]:
    evidence_dir = args.evidence_dir
    results_path, payload = load_workspace(evidence_dir)
    if args.case_id not in CASE_IDS:
        raise ValueError("case id must be BANK-01 through BANK-15")
    operator = require_text(args.operator, "operator")
    if payload.get("operator") != operator:
        raise ValueError("operator must match the operator recorded at initialization")

    case = next(item for item in payload["cases"] if item.get("id") == args.case_id)  # type: ignore[index]
    if case.get("status") != "unverified":
        raise ValueError("only an unverified case can be started")
    execution_starts = payload.setdefault("execution_starts", {})
    if not isinstance(execution_starts, dict):
        raise ValueError("execution_starts must be an object")
    if args.case_id in execution_starts:
        raise ValueError(f"case already has an execution start receipt: {args.case_id}")

    config_path = args.readiness_config
    if not config_path.is_absolute() or not config_path.is_file() or config_path.is_symlink():
        raise ValueError("readiness config must be an explicit absolute regular file")
    config_bytes = config_path.read_bytes()
    config_digest = hashlib.sha256(config_bytes).hexdigest()
    checker = Path(__file__).with_name("check-agent-security-bank-readiness.py")
    checked = subprocess.run(
        [sys.executable, str(checker), "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if checked.returncode != 0:
        raise ValueError(checked.stderr.strip() or "bank readiness validation failed")
    if config_path.read_bytes() != config_bytes:
        raise ValueError("readiness config changed during validation")
    config = json.loads(config_bytes.decode("utf-8"))
    people = config["people"]
    if people.get("operator") != operator:
        raise ValueError("readiness config operator does not match the acceptance operator")
    for field in ("environment", "platform_version", "git_commit"):
        if config.get(field) != payload.get(field):
            raise ValueError(f"readiness config {field} does not match the acceptance workspace")

    window = config["change_window"]
    starts_at = datetime.fromisoformat(window["starts_at"].replace("Z", "+00:00"))
    ends_at = datetime.fromisoformat(window["ends_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if not starts_at <= now <= ends_at:
        raise ValueError("current time is outside the approved change window")

    mutation_class = CASE_MUTATION_CLASSES[args.case_id]
    scope_reference = payload["environment"]
    if args.case_id in {"BANK-04", "BANK-07"}:
        scope_reference = config["authorized_agent"]["target_id"]
    elif args.case_id == "BANK-05":
        scope_reference = config["mcp"]["target_id"]
    elif args.case_id == "BANK-12":
        scope_reference = config["hosts"]["amd64"]["id"]
    elif args.case_id == "BANK-13":
        scope_reference = config["hosts"]["arm64"]["id"]
    receipt = {
        "schema": "agent-security-bank-case-start@1",
        "case_id": args.case_id,
        "mutation_class": mutation_class,
        "operator": operator,
        "started_at": now.isoformat().replace("+00:00", "Z"),
        "change_window": {
            "reference": window["reference"],
            "starts_at": window["starts_at"],
            "ends_at": window["ends_at"],
        },
        "approval_reference": config["approvals"][mutation_class],
        "scope_reference": scope_reference,
        "readiness_config_sha256": config_digest,
    }
    relative = f"control/case-starts/{args.case_id}.json"
    receipt_path = evidence_dir / relative
    if receipt_path.exists():
        raise ValueError(f"refusing to overwrite existing start receipt: {relative}")
    write_json(receipt_path, receipt)
    execution_starts[args.case_id] = relative
    try:
        persist_and_validate(evidence_dir, results_path, payload, require_complete=False)
    except Exception:
        receipt_path.unlink(missing_ok=True)
        raise
    return {
        "case_id": args.case_id,
        "mutation_class": mutation_class,
        "started_at": receipt["started_at"],
    }


def update_issue(args: argparse.Namespace) -> dict[str, int]:
    evidence_dir = args.evidence_dir
    results_path, acceptance = load_workspace(evidence_dir)
    issue_relative = PurePosixPath(require_text(acceptance.get("remaining_issues"), "remaining_issues"))
    if issue_relative.is_absolute() or ".." in issue_relative.parts:
        raise ValueError("remaining_issues must be a safe relative path")
    issue_path = evidence_dir / issue_relative
    if not issue_path.is_file() or issue_path.is_symlink():
        raise ValueError("remaining issues file is missing or symbolic")
    payload = json.loads(issue_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "agent-security-bank-remaining-issues@1":
        raise ValueError("unsupported remaining issues schema")
    issues = payload.get("issues")
    if not isinstance(issues, list):
        raise ValueError("remaining issues must contain an issues list")
    if not re.fullmatch(r"GAP-[0-9]{2,}", args.issue_id):
        raise ValueError("issue id must use the GAP-NN format")
    existing = next(
        (item for item in issues if isinstance(item, dict) and item.get("id") == args.issue_id), None
    )
    title = require_text(args.title, "title") if args.title else None
    if existing is None and title is None:
        raise ValueError("--title is required when adding a new issue")
    if existing is not None and title is None:
        existing_title = existing.get("title")
        title = require_text(existing_title if isinstance(existing_title, str) else None, "existing issue title")
    evidence = [safe_evidence_path(evidence_dir, value) for value in args.evidence]
    item: dict[str, object] = {
        "id": args.issue_id,
        "status": args.status,
        "title": title,
        "evidence": evidence,
    }
    if args.status == "open":
        item.update(
            {
                "reason": require_text(args.reason, "reason"),
                "owner": require_text(args.owner, "owner"),
                "closure_condition": require_text(args.closure_condition, "closure condition"),
            }
        )
    elif args.status == "resolved":
        if not evidence:
            raise ValueError("a resolved issue requires at least one evidence file")
        item["resolution"] = require_text(args.resolution, "resolution")
    else:
        if not evidence:
            raise ValueError("an accepted issue requires redacted risk-acceptance evidence")
        review_at_text = require_text(args.review_at, "review at")
        try:
            review_at = datetime.fromisoformat(review_at_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("review at must be an ISO-8601 timestamp") from exc
        if review_at.tzinfo is None:
            raise ValueError("review at must include a timezone")
        if review_at <= datetime.now(timezone.utc):
            raise ValueError("review at must be in the future")
        item.update(
            {
                "reason": require_text(args.reason, "reason"),
                "owner": require_text(args.owner, "owner"),
                "closure_condition": require_text(args.closure_condition, "closure condition"),
                "risk_acceptance_reference": require_text(
                    args.risk_acceptance_reference, "risk acceptance reference"
                ),
                "review_at": review_at.isoformat(),
            }
        )

    payload["issues"] = [
        item if isinstance(issue, dict) and issue.get("id") == args.issue_id else issue
        for issue in issues
    ]
    if existing is None:
        payload["issues"].append(item)
    counts = {status: 0 for status in ISSUE_STATUSES}
    for issue in payload["issues"]:
        if not isinstance(issue, dict) or issue.get("status") not in ISSUE_STATUSES:
            raise ValueError("remaining issue contains an invalid status")
        counts[str(issue["status"])] += 1
    payload["summary"] = counts

    original_issues = issue_path.read_bytes()
    acceptance["completed_at"] = None
    acceptance["sensitive_data_reviewed"] = False
    acceptance.pop("signoff", None)
    update_summary(acceptance)
    try:
        write_json(issue_path, payload)
        persist_and_validate(evidence_dir, results_path, acceptance, require_complete=False)
    except Exception:
        issue_path.write_bytes(original_issues)
        raise
    return counts


def complete_review(args: argparse.Namespace) -> dict[str, object]:
    if not args.confirm_sensitive_data_reviewed:
        raise ValueError("--confirm-sensitive-data-reviewed is required")
    evidence_dir = args.evidence_dir
    results_path, payload = load_workspace(evidence_dir)
    reviewer = require_text(args.reviewer, "reviewer")
    if payload.get("reviewer") != reviewer:
        raise ValueError("reviewer must match the independent reviewer recorded at initialization")
    update_summary(payload)
    summary = payload["summary"]
    if not isinstance(summary, dict) or summary.get("passed") != 15:
        raise ValueError("all 15 mandatory cases must pass before completing review")
    signoff_evidence = [safe_evidence_path(evidence_dir, value) for value in args.signoff_evidence]
    if not signoff_evidence:
        raise ValueError("at least one redacted signoff evidence file is required")
    completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload["completed_at"] = completed_at
    payload["sensitive_data_reviewed"] = True
    payload["overall_conclusion"] = "passed"
    payload["signoff"] = {
        "schema": "agent-security-bank-signoff@1",
        "reviewer": reviewer,
        "signed_at": completed_at,
        "signoff_reference": require_text(args.signoff_reference, "signoff reference"),
        "evidence_storage_reference": require_text(
            args.evidence_storage_reference, "evidence storage reference"
        ),
        "evidence": signoff_evidence,
    }
    persist_and_validate(evidence_dir, results_path, payload, require_complete=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    case_parser = subparsers.add_parser("case", help="Update one BANK case and refresh hashes")
    case_parser.add_argument("--evidence-dir", required=True, type=Path)
    case_parser.add_argument("--case-id", required=True)
    case_parser.add_argument("--status", required=True, choices=sorted(STATUSES))
    case_parser.add_argument("--evidence", action="append", default=[])
    case_parser.add_argument("--reason")
    case_parser.add_argument("--owner")
    case_parser.add_argument("--closure-condition")
    case_parser.add_argument("--rationale")

    start_parser = subparsers.add_parser("start", help="Authorize and record the start of one BANK case")
    start_parser.add_argument("--evidence-dir", required=True, type=Path)
    start_parser.add_argument("--readiness-config", required=True, type=Path)
    start_parser.add_argument("--case-id", required=True)
    start_parser.add_argument("--operator", required=True)

    issue_parser = subparsers.add_parser("issue", help="Update or add one remaining issue")
    issue_parser.add_argument("--evidence-dir", required=True, type=Path)
    issue_parser.add_argument("--issue-id", required=True)
    issue_parser.add_argument("--status", required=True, choices=sorted(ISSUE_STATUSES))
    issue_parser.add_argument("--title")
    issue_parser.add_argument("--evidence", action="append", default=[])
    issue_parser.add_argument("--reason")
    issue_parser.add_argument("--owner")
    issue_parser.add_argument("--closure-condition")
    issue_parser.add_argument("--resolution")
    issue_parser.add_argument("--risk-acceptance-reference")
    issue_parser.add_argument("--review-at")

    complete_parser = subparsers.add_parser("complete", help="Record independent review and final completion")
    complete_parser.add_argument("--evidence-dir", required=True, type=Path)
    complete_parser.add_argument("--reviewer", required=True)
    complete_parser.add_argument("--confirm-sensitive-data-reviewed", action="store_true")
    complete_parser.add_argument("--signoff-reference", required=True)
    complete_parser.add_argument("--evidence-storage-reference", required=True)
    complete_parser.add_argument("--signoff-evidence", action="append", default=[])
    args = parser.parse_args()

    try:
        if args.command == "issue":
            summary = update_issue(args)
            complete = False
        elif args.command == "start":
            summary = start_case(args)
            complete = False
        elif args.command == "case":
            summary = update_case(args)
            complete = False
        else:
            summary = complete_review(args)
            complete = True
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"bank acceptance update failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"updated": True, "complete": complete, "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
