#!/usr/bin/env python3
"""Initialize a P7-12 bank acceptance workspace from two formal offline packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

CASE_CLOSURES = {
    "BANK-01": "Verify release identity, image IDs, upstream lock, licenses, NOTICE, and SBOM hashes.",
    "BANK-02": "Verify default pages and the bank role matrix in both languages, including denied access audit.",
    "BANK-03": "Run the fixed Agent Mock scan and attach task, redacted artifact, and evidence hashes.",
    "BANK-04": "Run one authorized real Agent within approved target, network, TLS, budget, and evaluator boundaries.",
    "BANK-05": "Scan authorized MCP metadata and prove the upstream tools/call count remains zero.",
    "BANK-06": "Verify Sandbox, Test, Staging, and Production policies plus one-time approval behavior.",
    "BANK-07": "Exercise Kill Switch and read-only write blocking, then attach task and trace timelines.",
    "BANK-08": "Capture redacted full and gateway-only traces and verify their completeness labels.",
    "BANK-09": "Verify role access, one-time raw authorization, redacted PDF, hashes, and access audit.",
    "BANK-10": "Interrupt a Worker task, recover its lease, and attach attempt and recovery evidence.",
    "BANK-11": "Upgrade and explicitly roll back only the Worker, with one successful task after each change.",
    "BANK-12": "Install the formal amd64 package on an amd64 bank host and complete migration and business regression.",
    "BANK-13": "Install the formal arm64 package on an arm64 bank host and complete migration and business regression.",
    "BANK-14": "Review report semantics and TC260 boundaries in both languages without claiming certification.",
    "BANK-15": "Run backend, frontend, documentation, page, and API regression on the deployed commit.",
}
REMAINING_ISSUES = {
    "GAP-01": {
        "title": "Bank acceptance environment is not yet deployed.",
        "reason": "Bank host, network zone, architecture, release, and change window evidence is pending.",
        "closure_condition": "Resolve after BANK-12 and BANK-13 deployment evidence is accepted.",
    },
    "GAP-02": {
        "title": "Authorized real Agent has not yet been exercised.",
        "reason": "Authorized target and evaluator evidence is pending.",
        "closure_condition": "Resolve after BANK-04 redacted evidence is accepted.",
    },
    "GAP-03": {
        "title": "Worker interruption, recovery, upgrade, and rollback are not field-verified.",
        "reason": "Only isolated local resilience evidence exists.",
        "closure_condition": "Resolve after BANK-10 and BANK-11 field evidence is accepted.",
    },
    "GAP-04": {
        "title": "Formal dual-architecture installation is not field-verified.",
        "reason": "Formal packages have not been installed on both native bank architectures.",
        "closure_condition": "Resolve after BANK-12 and BANK-13 native installation evidence is accepted.",
    },
    "GAP-05": {
        "title": "Target connections do not pin DNS results at the socket layer.",
        "reason": "HTTP and WebSocket connection setup can perform another DNS resolution.",
        "closure_condition": "Implement pinned transport with rebinding tests or record approved network-control risk acceptance.",
    },
    "GAP-06": {
        "title": "Automatic W3C traceparent and OpenTelemetry bridging is not implemented.",
        "reason": "The platform currently uses correlation fields and SDK metadata.",
        "closure_condition": "Implement cross-system tracing or record approved interoperability risk acceptance.",
    },
    "GAP-07": {
        "title": "Python runtime and tests emit a large deprecation-warning baseline.",
        "reason": "Deprecated datetime, Pydantic, passlib/crypt, and websockets APIs remain.",
        "closure_condition": "Migrate before incompatible upgrades or record time-bounded compatibility risk acceptance.",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or "replace-with" in normalized.lower():
        raise ValueError(f"{field} must be a non-placeholder value")
    return normalized


def read_provenance(
    package: Path,
    *,
    architecture: str,
    version: str,
    commit: str,
) -> dict[str, object]:
    if not package.is_absolute() or not package.is_file() or package.is_symlink():
        raise ValueError(f"{architecture} package must be an explicit absolute regular file")
    try:
        with tarfile.open(package, "r:gz") as archive:
            member = archive.getmember("agent-manager/release-provenance.json")
            if not member.isfile() or member.size > 64 * 1024:
                raise ValueError(f"invalid release provenance member for {architecture}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"release provenance is unreadable for {architecture}")
            payload = json.loads(stream.read().decode("utf-8"))
    except (KeyError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {architecture} offline package: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"release provenance must be an object for {architecture}")
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
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise ValueError(
                f"{architecture} release provenance {field} mismatch: expected {expected_value!r}"
            )
    return payload


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--platform-version", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--owner", required=True, help="Default owner for all initially unverified cases")
    parser.add_argument("--amd64-package", required=True, type=Path)
    parser.add_argument("--arm64-package", required=True, type=Path)
    args = parser.parse_args()

    try:
        output_dir = args.output_dir
        if not output_dir.is_absolute():
            raise ValueError("output directory must be an explicit absolute path")
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"refusing to overwrite non-empty output directory: {output_dir}")
        environment = validate_text(args.environment, "environment")
        version = validate_text(args.platform_version, "platform_version")
        commit = validate_text(args.git_commit, "git_commit")
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit) is None:
            raise ValueError("git_commit must be a full hexadecimal identifier")
        operator = validate_text(args.operator, "operator")
        reviewer = validate_text(args.reviewer, "reviewer")
        owner = validate_text(args.owner, "owner")
        if operator == reviewer:
            raise ValueError("operator and reviewer must be different people")

        package_paths = {"amd64": args.amd64_package, "arm64": args.arm64_package}
        provenance = {
            architecture: read_provenance(
                package,
                architecture=architecture,
                version=version,
                commit=commit,
            )
            for architecture, package in package_paths.items()
        }
        package_inventory = {
            "schema": "agent-security-bank-package-inventory@1",
            "platform_version": version,
            "git_commit": commit,
            "packages": {
                architecture: {
                    "filename": package.name,
                    "size_bytes": package.stat().st_size,
                    "sha256": sha256(package),
                }
                for architecture, package in package_paths.items()
            },
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        for architecture, payload in provenance.items():
            target = output_dir / "provenance" / architecture / "release-provenance.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json(target, payload)
        package_dir = output_dir / "packages"
        package_dir.mkdir()
        write_json(package_dir / "package-inventory.json", package_inventory)

        issues = {
            "schema": "agent-security-bank-remaining-issues@1",
            "summary": {"open": len(REMAINING_ISSUES), "resolved": 0, "accepted": 0},
            "issues": [
                {"id": issue_id, "status": "open", "owner": owner, **details}
                for issue_id, details in REMAINING_ISSUES.items()
            ],
        }
        write_json(output_dir / "remaining-issues.json", issues)

        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        results = {
            "schema": "agent-security-bank-acceptance@1",
            "environment": environment,
            "platform_version": version,
            "git_commit": commit,
            "architectures": ["amd64", "arm64"],
            "started_at": started_at,
            "completed_at": None,
            "operator": operator,
            "reviewer": reviewer,
            "sensitive_data_reviewed": False,
            "sha256_manifest": "manifest.sha256",
            "release_provenance": {
                "amd64": "provenance/amd64/release-provenance.json",
                "arm64": "provenance/arm64/release-provenance.json",
            },
            "execution_starts": {},
            "remaining_issues": "remaining-issues.json",
            "overall_conclusion": "unverified",
            "summary": {"passed": 0, "failed": 0, "unverified": 15, "not_applicable": 0},
            "cases": [
                {
                    "id": case_id,
                    "status": "unverified",
                    "evidence": [],
                    "reason": "Bank environment execution has not been recorded.",
                    "owner": owner,
                    "closure_condition": CASE_CLOSURES[case_id],
                }
                for case_id in CASE_CLOSURES
            ],
        }
        write_json(output_dir / "acceptance-results.json", results)

        manifest_lines = []
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path.name != "manifest.sha256":
                manifest_lines.append(f"{sha256(path)}  {path.relative_to(output_dir).as_posix()}")
        (output_dir / "manifest.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"bank acceptance initialization failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "initialized": True,
                "complete": False,
                "output_dir": str(output_dir),
                "summary": results["summary"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
