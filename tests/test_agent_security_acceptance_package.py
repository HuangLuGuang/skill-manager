from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/acceptance/agent-security-vnext"


def test_p7_bank_acceptance_matrix_keeps_external_results_unverified():
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    matrix = (PACKAGE / "bank-acceptance-matrix.md").read_text(encoding="utf-8")

    for required in (
        "不能用本地 pytest、Mock、镜像自检或 Compose 配置渲染替代",
        "P7-12 和银行现场的双架构安装仍为“未验证”",
        "只有以下条件同时满足，才可勾选 P7-12",
        "原始 Prompt、响应、Tool 参数、目标凭据、Worker Token、模型 Key、管理员 JWT",
    ):
        assert required in readme

    for case_id in range(1, 16):
        assert f"BANK-{case_id:02d}" in matrix
    for required in (
        "银行环境结果",
        "未验证",
        "tools/call` 计数为 0",
        "W3C traceparent/OpenTelemetry 自动桥接未实现",
        "socket 级 DNS/IP 固定",
        "未满足原因与关闭条件",
    ):
        assert required in matrix

    dual_arch = (PACKAGE / "local-dual-architecture-offline-2026-08-30.md").read_text(encoding="utf-8")
    assert "ARM64 为本机原生执行" in dual_arch
    assert "x86_64 为 ARM64 Docker 主机上的模拟执行" in dual_arch
    assert "不是银行目标主机验收" in dual_arch

    execution_plan = json.loads((PACKAGE / "bank-acceptance-execution-plan.json").read_text(encoding="utf-8"))
    assert execution_plan["schema"] == "agent-security-bank-execution-plan@1"
    assert [case["id"] for case in execution_plan["cases"]] == [f"BANK-{index:02d}" for index in range(1, 16)]
    assert all(case["mutation_class"] in execution_plan["mutation_classes"] for case in execution_plan["cases"])
    assert all(case["required_roles"] and case["evidence_dir"] for case in execution_plan["cases"])
    mcp_case = next(case for case in execution_plan["cases"] if case["id"] == "BANK-05")
    assert mcp_case["tools_call_zero_required"] is True

    runbook = (PACKAGE / "bank-acceptance-runbook.md").read_text(encoding="utf-8")
    for case_id in (f"BANK-{index:02d}" for index in range(1, 16)):
        assert case_id in runbook
    for required in (
        "模拟执行不能填写通过",
        "`tools/call` 增量为 0",
        "不能用自由文本绕过必验项",
        "只有该命令成功、签署信息完整",
        "check-agent-security-bank-readiness.py",
        "remaining-issues.json",
        "存在任何 open 项时最终门禁失败",
        "脱敏签署证据",
        "清除旧签署",
        "不依赖封包脚本先执行",
        "完整普通文件集合",
        "没有被任何 BANK 用例直接引用",
        "不回显命中内容",
        "不能替代",
    ):
        assert required in runbook or required in (PACKAGE / "README.md").read_text(encoding="utf-8")


def test_bank_readiness_checker_fails_closed_and_accepts_complete_non_secret_input(tmp_path: Path):
    checker = ROOT / "scripts" / "check-agent-security-bank-readiness.py"
    example = json.loads((PACKAGE / "bank-readiness.example.json").read_text(encoding="utf-8"))
    version = "v7.12.0"
    commit = "d" * 40

    def make_package(architecture: str) -> Path:
        package = tmp_path / f"agent-manager_{architecture}.tar.gz"
        payload = {
            "schema": "agent-manager-release-provenance@1",
            "version": version,
            "git_commit": commit,
            "architecture": architecture,
            "platform": f"linux/{architecture}",
            "archive_layout": "x86" if architecture == "amd64" else "arm",
            "source_mode": "git_clone",
            "worktree_dirty": False,
        }
        raw = json.dumps(payload).encode()
        member = tarfile.TarInfo("agent-manager/release-provenance.json")
        member.size = len(raw)
        with tarfile.open(package, "w:gz") as archive:
            archive.addfile(member, io.BytesIO(raw))
        return package

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [fill(nested) for nested in value]
        if isinstance(value, str) and "replace-with" in value:
            return "approved-reference"
        return value

    config = fill(example)
    config["platform_version"] = version
    config["git_commit"] = commit
    config["people"]["operator"] = "operator-a"
    config["people"]["reviewer"] = "reviewer-b"
    config["packages"] = {
        architecture: str(make_package(architecture)) for architecture in ("amd64", "arm64")
    }
    config_path = tmp_path / "readiness.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    ready = subprocess.run(
        [sys.executable, str(checker), "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ready.returncode == 0, ready.stderr
    result = json.loads(ready.stdout)
    assert result["ready"] is True
    assert result["architectures"] == ["amd64", "arm64"]
    assert "password" not in ready.stdout.lower()

    config["admin_password"] = "must-never-be-accepted"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(checker), "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "forbidden sensitive field" in rejected.stderr


def test_p7_acceptance_manifest_and_collector_are_secret_safe_and_non_destructive():
    results = json.loads((PACKAGE / "acceptance-results.example.json").read_text(encoding="utf-8"))
    assert results["schema"] == "agent-security-bank-acceptance@1"
    assert results["summary"]["unverified"] == 15
    assert results["sensitive_data_reviewed"] is False
    assert not (PACKAGE / "evidence-manifest.example.json").exists()

    collector = (ROOT / "scripts/collect-agent-security-acceptance-evidence.sh").read_text(encoding="utf-8")
    for required in (
        "--output-dir must be an explicit absolute path",
        "Refusing to overwrite non-empty evidence directory",
        "docker compose --env-file /dev/null",
        '"${COMPOSE[@]}" config --no-env-resolution --quiet',
        'label=com.docker.compose.project=${COMPOSE_PROJECT}',
        "--compose-project must use lowercase letters",
        'SOURCE_KIND="release_provenance"',
        "verify-agent-manager-release-provenance.py",
        "source-cleanliness-check.txt",
        "release-provenance.json",
        "uv run pytest -q",
        "npm run test:i18n",
        "npm run build",
        "verify-agent-security-worker-image.sh",
        "manifest.sha256",
    ):
        assert required in collector
    for forbidden in ("docker compose up", "docker compose down", "docker compose stop", "docker compose restart"):
        assert forbidden not in collector
    assert 'git diff --check >"$OUTPUT_DIR/source-cleanliness-check.txt"' in collector


def test_e2e_regression_runner_maps_all_scenarios_without_claiming_bank_equivalence():
    mapping = json.loads((PACKAGE / "e2e-regression-cases.json").read_text(encoding="utf-8"))
    assert mapping["schema"] == "agent-security-e2e-regression@1"
    assert mapping["scope"] == "local_repository_regression"
    assert mapping["bank_environment_equivalent"] is False
    assert [case["id"] for case in mapping["cases"]] == [f"E2E-{index:02d}" for index in range(1, 11)]
    assert all(case["tests"] for case in mapping["cases"])
    for case in mapping["cases"]:
        for test_id in case["tests"]:
            test_file, test_name = test_id.split("::", 1)
            content = (ROOT / test_file).read_text(encoding="utf-8")
            assert f"def {test_name}(" in content

    runner = (ROOT / "scripts" / "run-agent-security-e2e-regression.sh").read_text(encoding="utf-8")
    assert "Refusing to overwrite non-empty E2E evidence directory" in runner
    assert 'bank_environment_equivalent": False' in runner
    assert '"source_tree_sha256"' in runner
    assert 'git", "-C", str(root), "ls-files"' in runner
    assert "--junitxml" in runner
    assert "manifest.sha256" in runner


def test_release_packager_supports_current_worktree_without_copying_ignored_files():
    script = (ROOT / "package-release.sh").read_text(encoding="utf-8")
    offline_doc = (ROOT / "docs" / "docker-deployment.md").read_text(encoding="utf-8")

    assert "--source-dir" in script
    assert 'git -C "$SOURCE_DIR" ls-files --cached --others --exclude-standard -z' in script
    assert "cp -pP" in script
    assert "Source directory and work directory must be different" in script
    assert "--source-dir" in offline_doc
    assert "不能替代" in offline_doc


def test_frontend_release_image_fails_closed_on_known_dependency_vulnerabilities():
    dockerfile = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))

    assert "RUN npm install && npm audit --audit-level=low" in dockerfile
    assert package["dependencies"]["axios"].startswith("^1.20.")
    assert package["devDependencies"]["vite"].startswith("^7.3.")
    assert package["overrides"]["esbuild"].startswith("^0.28.")
    assert package["overrides"]["nanoid"].startswith("^3.3.18")
    assert package["overrides"]["postcss"].startswith("^8.5.23")


@pytest.mark.parametrize(("platform", "arch", "version"), [
    ("linux/amd64", "x86", "test"),
    ("linux/arm64", "arm", "test_arm"),
])
def test_release_packager_source_dir_excludes_gitignored_files(tmp_path: Path, platform, arch, version):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / ".gitignore").write_text(".env\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=must-not-ship\n", encoding="utf-8")
    (source / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (source / "new.txt").write_text("untracked-but-not-ignored\n", encoding="utf-8")
    build = source / "build.sh"
    build.write_text(
        "#!/bin/bash\nset -e\n"
        'version=""\narch=x86\nwhile [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "-t" ]; then version="$2"; shift; fi\n'
        '  if [ "$1" = "-p" ] && [ "$2" = "linux/arm64" ]; then arch=arm; fi\n'
        '  shift\ndone\nmkdir -p "docker_images/${arch}"\n'
        'printf image > "docker_images/${arch}/agent-manager-images-${version}.tar.xz"\n',
        encoding="utf-8",
    )
    build.chmod(0o755)
    for relative in (
        "docker-compose.yaml", ".env.example", "deploy/nginx/default.conf",
        "docs/offline-deployment.md", "docs/docker-deployment.md", "docs/license.md",
        "start.sh", "upgrade.sh", "deploy/offline.sh",
    ):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    (source / "scanner/releases").mkdir(parents=True)
    (source / "scanner/releases/skill-scan-report.json").write_text("private scan report")
    subprocess.run(
        ["git", "-C", str(source), "add", ".gitignore", "tracked.txt", "build.sh",
         "docker-compose.yaml", ".env.example", "deploy", "docs", "start.sh", "upgrade.sh"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Acceptance Test",
            "-c",
            "user.email=acceptance@example.invalid",
            "commit",
            "-qm",
            "test source",
        ],
        check=True,
    )

    installer = tmp_path / "installer.tar.gz"
    installer.write_bytes(b"test-installer")
    client_feed = tmp_path / "client-feed"
    client_feed.mkdir()
    (client_feed / "latest.json").write_text('{"version": "test"}')
    (client_feed / "agent-manager-client.exe").write_bytes(b"client-installer")
    output = tmp_path / "output"
    work = tmp_path / "work"
    subprocess.run(
        [
            "bash",
            str(ROOT / "package-release.sh"),
            "--version",
            version,
            "--platform",
            platform,
            "--source-dir",
            str(source),
            "--installer",
            str(installer.relative_to(tmp_path)),
            "--output",
            str(output),
            "--work-dir",
            str(work),
            "--client-releases",
            str(client_feed),
            "--reuse-images",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    with tarfile.open(output / f"agent-manager_test_{arch}.tar.gz") as archive:
        names = set(archive.getnames())
        provenance = json.load(archive.extractfile("agent-manager/release-provenance.json"))
    files = {
        "docker-compose.yaml", ".env.example", "deploy/nginx/default.conf", "release-provenance.json",
        "docs/offline-deployment.md", "docs/docker-deployment.md", "docs/license.md",
        f"docker_images/{arch}/agent-manager-images-{version}.tar.xz",
        "installers/docker-installer-28.5.2-x86-arm.tar.gz",
        "scanner/releases/latest.json", "scanner/releases/agent-manager-client.exe",
        "start.sh", "upgrade.sh", "deploy/offline.sh", "release-info",
    }
    with tarfile.open(output / f"agent-manager_test_{arch}.tar.gz") as archive:
        assert {entry.name for entry in archive if entry.isfile()} == {"agent-manager/" + path for path in files}
        assert archive.extractfile("agent-manager/release-info").read().decode() == f"{version}\n{platform}\n"
        env = archive.extractfile("agent-manager/.env.example").read().decode()
        assert "TAG=" not in env
        assert archive.getmember("agent-manager/start.sh").mode & 0o111
        assert archive.getmember("agent-manager/upgrade.sh").mode & 0o111
        compose = yaml.safe_load(archive.extractfile("agent-manager/docker-compose.yaml"))
        for service in compose["services"].values():
            if service["image"].startswith("agent-manager-"):
                assert service["image"].endswith(":" + version)
                assert "${" not in service["image"]
            for volume in service.get("volumes", []):
                if isinstance(volume, str) and volume.startswith("./"):
                    assert "agent-manager/" + volume.split(":")[0][2:] in names
    assert "agent-manager/scanner/releases" in names
    assert "agent-manager/tracked.txt" not in names
    assert "agent-manager/new.txt" not in names
    assert "agent-manager/scanner/releases/skill-scan-report.json" not in names
    assert "agent-manager/.env" not in names
    assert not any(name.startswith("agent-manager/.git/") for name in names)
    assert provenance["schema"] == "agent-manager-release-provenance@1"
    assert provenance["version"] == version
    assert provenance["platform"] == platform
    assert provenance["architecture"] == platform.split("/")[1]
    assert provenance["archive_layout"] == arch
    assert provenance["source_mode"] == "worktree"
    assert provenance["worktree_dirty"] is True
    assert len(provenance["git_commit"]) == 40

    clone_branch = subprocess.run(
        ["git", "-C", str(source), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "bash",
            str(ROOT / "package-release.sh"),
            "--version",
            "clone-" + version,
            "--branch",
            clone_branch,
            "--platform",
            platform,
            "--repo",
            str(source),
            "--installer",
            str(installer.relative_to(tmp_path)),
            "--output",
            str(output),
            "--work-dir",
            str(tmp_path / "clone-work"),
            "--reuse-images",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    with tarfile.open(output / f"agent-manager_clone-test_{arch}.tar.gz") as archive:
        clone_provenance = json.load(archive.extractfile("agent-manager/release-provenance.json"))
    assert clone_provenance["source_mode"] == "git_clone"
    assert clone_provenance["worktree_dirty"] is False
    assert clone_provenance["git_commit"] == provenance["git_commit"]

    provenance_file = tmp_path / "clone-provenance.json"
    provenance_file.write_text(json.dumps(clone_provenance), encoding="utf-8")
    verifier = ROOT / "scripts" / "verify-agent-manager-release-provenance.py"
    verified = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--file",
            str(provenance_file),
            "--version",
            "clone-" + version,
            "--commit",
            clone_provenance["git_commit"],
            "--platform",
            platform,
            "--require-clean-clone",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr

    clone_provenance["worktree_dirty"] = True
    provenance_file.write_text(json.dumps(clone_provenance), encoding="utf-8")
    dirty = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--file",
            str(provenance_file),
            "--version",
            "clone-" + version,
            "--commit",
            clone_provenance["git_commit"],
            "--platform",
            platform,
            "--require-clean-clone",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert dirty.returncode == 1
    assert "worktree must be clean" in dirty.stderr


def test_bank_acceptance_validator_requires_complete_hashed_evidence(tmp_path: Path):
    validator = ROOT / "scripts" / "validate-agent-security-acceptance-evidence.py"
    finalizer = ROOT / "scripts" / "finalize-agent-security-acceptance-evidence.sh"
    example = json.loads((PACKAGE / "acceptance-results.example.json").read_text(encoding="utf-8"))
    proof = tmp_path / "proof.txt"
    proof.write_text("redacted bank acceptance evidence\n", encoding="utf-8")

    example.update(
        {
            "environment": "bank-staging-a",
            "platform_version": "v7.12.0",
            "git_commit": "a" * 40,
            "started_at": "2026-08-30T01:00:00Z",
            "completed_at": "2026-08-30T02:00:00Z",
            "operator": "authorized-operator",
            "reviewer": "independent-reviewer",
            "sensitive_data_reviewed": True,
            "overall_conclusion": "passed",
            "summary": {"passed": 15, "failed": 0, "unverified": 0, "not_applicable": 0},
            "signoff": {
                "schema": "agent-security-bank-signoff@1",
                "reviewer": "independent-reviewer",
                "signed_at": "2026-08-30T02:00:00Z",
                "signoff_reference": "approved-signoff",
                "evidence_storage_reference": "approved-evidence-vault",
                "evidence": ["proof.txt"],
            },
        }
    )
    for index, case in enumerate(example["cases"], start=1):
        case.clear()
        case.update({"id": f"BANK-{index:02d}", "status": "passed", "evidence": ["proof.txt"]})
    execution_plan = json.loads((PACKAGE / "bank-acceptance-execution-plan.json").read_text(encoding="utf-8"))
    example["execution_starts"] = {}
    for case in execution_plan["cases"]:
        case_id = case["id"]
        relative = f"control/case-starts/{case_id}.json"
        receipt = tmp_path / relative
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "schema": "agent-security-bank-case-start@1",
                    "case_id": case_id,
                    "mutation_class": case["mutation_class"],
                    "operator": "authorized-operator",
                    "started_at": "2026-08-30T01:30:00Z",
                    "change_window": {
                        "reference": "approved-change-1",
                        "starts_at": "2026-08-30T01:00:00Z",
                        "ends_at": "2026-08-30T02:00:00Z",
                    },
                    "approval_reference": "approved-action-1",
                    "scope_reference": "bank-staging-a",
                    "readiness_config_sha256": "e" * 64,
                }
            ),
            encoding="utf-8",
        )
        example["execution_starts"][case_id] = relative
    example["remaining_issues"] = "remaining-issues.json"
    remaining_issues = {
        "schema": "agent-security-bank-remaining-issues@1",
        "summary": {"open": 0, "resolved": 4, "accepted": 3},
        "issues": [],
    }
    for index in range(1, 8):
        issue = {
            "id": f"GAP-{index:02d}",
            "title": f"Acceptance gap {index}",
            "evidence": ["proof.txt"],
        }
        if index <= 4:
            issue.update({"status": "resolved", "resolution": "Field evidence closed the gap."})
        else:
            issue.update(
                {
                    "status": "accepted",
                    "reason": "Known limitation remains.",
                    "owner": "risk-owner",
                    "closure_condition": "Review and close before the next incompatible upgrade.",
                    "risk_acceptance_reference": "approved-risk-acceptance",
                    "review_at": "2027-08-30T00:00:00Z",
                }
            )
        remaining_issues["issues"].append(issue)
    (tmp_path / "remaining-issues.json").write_text(json.dumps(remaining_issues), encoding="utf-8")
    results = tmp_path / "acceptance-results.json"
    results.write_text(json.dumps(example), encoding="utf-8")
    for architecture, archive_layout in (("amd64", "x86"), ("arm64", "arm")):
        provenance_path = tmp_path / "provenance" / architecture / "release-provenance.json"
        provenance_path.parent.mkdir(parents=True)
        provenance_path.write_text(
            json.dumps(
                {
                    "schema": "agent-manager-release-provenance@1",
                    "version": "v7.12.0",
                    "platform": f"linux/{architecture}",
                    "architecture": architecture,
                    "archive_layout": archive_layout,
                    "source_mode": "git_clone",
                    "git_commit": "a" * 40,
                    "git_branch": "v7.12.0",
                    "worktree_dirty": False,
                    "generated_at": "2026-08-30T00:30:00Z",
                }
            ),
            encoding="utf-8",
        )

    finalized = subprocess.run(
        ["bash", str(finalizer), "--evidence-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert finalized.returncode == 0, finalized.stderr
    assert "acceptance-results.json" in (tmp_path / "manifest.sha256").read_text(encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"passed": 15' in completed.stdout

    unreviewed = tmp_path / "unreviewed-extra.txt"
    unreviewed.write_text("not included in manifest\n", encoding="utf-8")
    unlisted = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unlisted.returncode == 1
    assert "manifest file set mismatch" in unlisted.stderr

    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    unreviewed.write_text("tampered after finalization\n", encoding="utf-8")
    unreferenced_tamper = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unreferenced_tamper.returncode == 1
    assert "sha256 mismatch for manifest entry" in unreferenced_tamper.stderr
    unreviewed.unlink()
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)

    leaked = tmp_path / "leaked-authorization.log"
    leaked.write_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret.signature\n", encoding="utf-8")
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    secret_scan = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert secret_scan.returncode == 1
    assert "obvious plaintext secret detected" in secret_scan.stderr
    assert "eyJhbGci" not in secret_scan.stderr
    leaked.write_text("Authorization: Bearer <redacted>\n", encoding="utf-8")
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    redacted_secret = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert redacted_secret.returncode == 0, redacted_secret.stderr
    leaked.unlink()
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)

    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (outside_dir / "escaped-proof.txt").write_text("outside evidence\n", encoding="utf-8")
    linked_dir = tmp_path / "linked-evidence"
    linked_dir.symlink_to(outside_dir, target_is_directory=True)
    linked = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert linked.returncode == 1
    assert "must not contain symbolic links" in linked.stderr
    linked_dir.unlink()
    shutil.rmtree(outside_dir)

    proof.write_text("tampered\n", encoding="utf-8")
    tampered = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert tampered.returncode == 1
    assert "sha256 mismatch" in tampered.stderr

    proof.write_text("redacted bank acceptance evidence\n", encoding="utf-8")
    signoff = example.pop("signoff")
    results.write_text(json.dumps(example), encoding="utf-8")
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    missing_signoff = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing_signoff.returncode == 1
    assert "requires a signoff record" in missing_signoff.stderr
    example["signoff"] = signoff

    bank_15_start = example["execution_starts"].pop("BANK-15")
    results.write_text(json.dumps(example), encoding="utf-8")
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    missing_start = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing_start.returncode == 1
    assert "start receipt for every BANK case" in missing_start.stderr
    example["execution_starts"]["BANK-15"] = bank_15_start

    example["cases"][0] = {
        "id": "BANK-01",
        "status": "not_applicable",
        "evidence": ["proof.txt"],
        "rationale": "reviewer considered the case not applicable",
    }
    example["summary"] = {"passed": 14, "failed": 0, "unverified": 0, "not_applicable": 1}
    results.write_text(json.dumps(example), encoding="utf-8")
    subprocess.run(["bash", str(finalizer), "--evidence-dir", str(tmp_path)], check=True)
    not_applicable = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(tmp_path), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert not_applicable.returncode == 1
    assert "all 15 mandatory cases" in not_applicable.stderr


def test_bank_acceptance_initializer_requires_clean_formal_dual_arch_packages(tmp_path: Path):
    initializer = ROOT / "scripts" / "initialize-agent-security-bank-acceptance.py"
    validator = ROOT / "scripts" / "validate-agent-security-acceptance-evidence.py"
    version = "v7.12.0"
    commit = "c" * 40

    def make_package(architecture: str, *, dirty: bool = False) -> Path:
        package = tmp_path / f"agent-manager_{version}_{architecture}.tar.gz"
        payload = {
            "schema": "agent-manager-release-provenance@1",
            "version": version,
            "platform": f"linux/{architecture}",
            "architecture": architecture,
            "archive_layout": "x86" if architecture == "amd64" else "arm",
            "source_mode": "git_clone",
            "git_commit": commit,
            "git_branch": version,
            "worktree_dirty": dirty,
            "generated_at": "2026-08-30T00:00:00Z",
        }
        raw = json.dumps(payload).encode()
        member = tarfile.TarInfo("agent-manager/release-provenance.json")
        member.size = len(raw)
        member.mode = 0o644
        with tarfile.open(package, "w:gz") as archive:
            archive.addfile(member, io.BytesIO(raw))
        return package

    amd64 = make_package("amd64")
    arm64 = make_package("arm64")
    output = tmp_path / "bank-acceptance"
    command = [
        sys.executable,
        str(initializer),
        "--output-dir",
        str(output),
        "--environment",
        "bank-staging-a",
        "--platform-version",
        version,
        "--git-commit",
        commit,
        "--operator",
        "bank-operator",
        "--reviewer",
        "independent-reviewer",
        "--owner",
        "acceptance-owner",
        "--amd64-package",
        str(amd64),
        "--arm64-package",
        str(arm64),
    ]
    initialized = subprocess.run(command, check=False, capture_output=True, text=True)
    assert initialized.returncode == 0, initialized.stderr
    results = json.loads((output / "acceptance-results.json").read_text(encoding="utf-8"))
    assert results["completed_at"] is None
    assert results["sensitive_data_reviewed"] is False
    assert results["summary"] == {"passed": 0, "failed": 0, "unverified": 15, "not_applicable": 0}
    assert len(results["cases"]) == 15
    issues = json.loads((output / "remaining-issues.json").read_text(encoding="utf-8"))
    assert issues["summary"] == {"open": 7, "resolved": 0, "accepted": 0}
    inventory = json.loads((output / "packages" / "package-inventory.json").read_text(encoding="utf-8"))
    assert set(inventory["packages"]) == {"amd64", "arm64"}
    assert all(len(item["sha256"]) == 64 for item in inventory["packages"].values())

    preliminary = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert preliminary.returncode == 0, preliminary.stderr
    assert '"complete": false' in preliminary.stdout
    final = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(output), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert final.returncode == 1
    assert "completed_at is required" in final.stderr

    manager = ROOT / "scripts" / "manage-agent-security-bank-acceptance.py"
    before_rejected_update = (output / "acceptance-results.json").read_bytes()
    missing_evidence = subprocess.run(
        [
            sys.executable,
            str(manager),
            "case",
            "--evidence-dir",
            str(output),
            "--case-id",
            "BANK-01",
            "--status",
            "passed",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing_evidence.returncode == 1
    assert "requires at least one evidence file" in missing_evidence.stderr
    assert (output / "acceptance-results.json").read_bytes() == before_rejected_update

    readiness = json.loads((PACKAGE / "bank-readiness.example.json").read_text(encoding="utf-8"))

    def fill_readiness(value):
        if isinstance(value, dict):
            return {key: fill_readiness(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [fill_readiness(nested) for nested in value]
        if isinstance(value, str) and "replace-with" in value:
            return "approved-reference"
        return value

    readiness = fill_readiness(readiness)
    readiness["environment"] = "bank-staging-a"
    readiness["platform_version"] = version
    readiness["git_commit"] = commit
    readiness["people"]["operator"] = "bank-operator"
    readiness["people"]["reviewer"] = "independent-reviewer"
    readiness["packages"] = {"amd64": str(amd64), "arm64": str(arm64)}
    now = datetime.now(timezone.utc)
    readiness["change_window"] = {
        "reference": "approved-change-window",
        "starts_at": (now - timedelta(minutes=5)).isoformat(),
        "ends_at": (now + timedelta(minutes=5)).isoformat(),
    }
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

    wrong_operator = subprocess.run(
        [
            sys.executable,
            str(manager),
            "start",
            "--evidence-dir",
            str(output),
            "--readiness-config",
            str(readiness_path),
            "--case-id",
            "BANK-01",
            "--operator",
            "not-the-operator",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert wrong_operator.returncode == 1
    assert "operator must match" in wrong_operator.stderr

    readiness["change_window"] = {
        "reference": "expired-change-window",
        "starts_at": (now - timedelta(minutes=10)).isoformat(),
        "ends_at": (now - timedelta(minutes=5)).isoformat(),
    }
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    outside_window = subprocess.run(
        [
            sys.executable,
            str(manager),
            "start",
            "--evidence-dir",
            str(output),
            "--readiness-config",
            str(readiness_path),
            "--case-id",
            "BANK-01",
            "--operator",
            "bank-operator",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert outside_window.returncode == 1
    assert "outside the approved change window" in outside_window.stderr
    readiness["change_window"] = {
        "reference": "approved-change-window",
        "starts_at": (now - timedelta(minutes=5)).isoformat(),
        "ends_at": (now + timedelta(minutes=5)).isoformat(),
    }
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

    proof = output / "business-cases" / "authorized-proof.txt"
    proof.parent.mkdir()
    proof.write_text("redacted authorized bank evidence\n", encoding="utf-8")
    for index in range(1, 16):
        started = subprocess.run(
            [
                sys.executable,
                str(manager),
                "start",
                "--evidence-dir",
                str(output),
                "--readiness-config",
                str(readiness_path),
                "--case-id",
                f"BANK-{index:02d}",
                "--operator",
                "bank-operator",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert started.returncode == 0, started.stderr
        if index == 1:
            duplicate_start = subprocess.run(
                [
                    sys.executable,
                    str(manager),
                    "start",
                    "--evidence-dir",
                    str(output),
                    "--readiness-config",
                    str(readiness_path),
                    "--case-id",
                    "BANK-01",
                    "--operator",
                    "bank-operator",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert duplicate_start.returncode == 1
            assert "already has an execution start receipt" in duplicate_start.stderr
        updated = subprocess.run(
            [
                sys.executable,
                str(manager),
                "case",
                "--evidence-dir",
                str(output),
                "--case-id",
                f"BANK-{index:02d}",
                "--status",
                "passed",
                "--evidence",
                "business-cases/authorized-proof.txt",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert updated.returncode == 0, updated.stderr
    pending_review = json.loads((output / "acceptance-results.json").read_text(encoding="utf-8"))
    assert pending_review["summary"] == {
        "passed": 15,
        "failed": 0,
        "unverified": 0,
        "not_applicable": 0,
    }
    assert pending_review["overall_conclusion"] == "pending_review"
    assert pending_review["sensitive_data_reviewed"] is False

    open_issues = subprocess.run(
        [
            sys.executable,
            str(manager),
            "complete",
            "--evidence-dir",
            str(output),
            "--reviewer",
            "independent-reviewer",
            "--confirm-sensitive-data-reviewed",
            "--signoff-reference",
            "approved-signoff",
            "--evidence-storage-reference",
            "approved-evidence-vault",
            "--signoff-evidence",
            "business-cases/authorized-proof.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert open_issues.returncode == 1
    assert "open remaining issues" in open_issues.stderr

    for index in range(1, 8):
        command = [
            sys.executable,
            str(manager),
            "issue",
            "--evidence-dir",
            str(output),
            "--issue-id",
            f"GAP-{index:02d}",
            "--evidence",
            "business-cases/authorized-proof.txt",
        ]
        if index <= 4:
            command.extend(["--status", "resolved", "--resolution", "Bank field evidence closed the gap."])
        else:
            command.extend(
                [
                    "--status",
                    "accepted",
                    "--reason",
                    "Known limitation remains.",
                    "--owner",
                    "risk-owner",
                    "--closure-condition",
                    "Review before the next incompatible upgrade.",
                    "--risk-acceptance-reference",
                    "approved-risk-acceptance",
                    "--review-at",
                    (now + timedelta(days=365)).isoformat(),
                ]
            )
        updated_issue = subprocess.run(command, check=False, capture_output=True, text=True)
        assert updated_issue.returncode == 0, updated_issue.stderr

    completed_review = subprocess.run(
        [
            sys.executable,
            str(manager),
            "complete",
            "--evidence-dir",
            str(output),
            "--reviewer",
            "independent-reviewer",
            "--confirm-sensitive-data-reviewed",
            "--signoff-reference",
            "approved-signoff",
            "--evidence-storage-reference",
            "approved-evidence-vault",
            "--signoff-evidence",
            "business-cases/authorized-proof.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed_review.returncode == 0, completed_review.stderr
    final = subprocess.run(
        [sys.executable, str(validator), "--evidence-dir", str(output), "--require-complete"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert final.returncode == 0, final.stderr

    reopened_issue = subprocess.run(
        [
            sys.executable,
            str(manager),
            "issue",
            "--evidence-dir",
            str(output),
            "--issue-id",
            "GAP-05",
            "--status",
            "open",
            "--reason",
            "Risk acceptance requires reassessment.",
            "--owner",
            "risk-owner",
            "--closure-condition",
            "Obtain a renewed decision.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert reopened_issue.returncode == 0, reopened_issue.stderr
    invalidated = json.loads((output / "acceptance-results.json").read_text(encoding="utf-8"))
    assert invalidated["completed_at"] is None
    assert invalidated["sensitive_data_reviewed"] is False
    assert invalidated["overall_conclusion"] == "pending_review"
    assert "signoff" not in invalidated

    dirty_arm64 = make_package("arm64", dirty=True)
    dirty_output = tmp_path / "dirty-output"
    rejected = subprocess.run(
        [
            sys.executable,
            str(initializer),
            "--output-dir",
            str(dirty_output),
            "--environment",
            "bank-staging-a",
            "--platform-version",
            version,
            "--git-commit",
            commit,
            "--operator",
            "bank-operator",
            "--reviewer",
            "independent-reviewer",
            "--owner",
            "acceptance-owner",
            "--amd64-package",
            str(amd64),
            "--arm64-package",
            str(dirty_arm64),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "worktree_dirty mismatch" in rejected.stderr
    assert not dirty_output.exists()


def test_evidence_collector_uses_offline_provenance_without_compose_env_resolution(tmp_path: Path):
    offline_root = tmp_path / "agent-manager"
    scripts = offline_root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "collect-agent-security-acceptance-evidence.sh", scripts)
    (offline_root / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
    provenance = {
        "schema": "agent-manager-release-provenance@1",
        "version": "v7.12.0",
        "platform": "linux/amd64",
        "architecture": "amd64",
        "archive_layout": "x86",
        "source_mode": "git_clone",
        "git_commit": "b" * 40,
        "git_branch": "v7.12.0",
        "worktree_dirty": False,
        "generated_at": "2026-08-30T00:00:00Z",
    }
    (offline_root / "release-provenance.json").write_text(json.dumps(provenance), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        "echo \"$*\" >>\"$DOCKER_CALL_LOG\"\n"
        "if [[ \"$1\" == version ]]; then echo 'docker_client=29 docker_server=29'; exit 0; fi\n"
        "if [[ \"$1 $2\" == 'compose version' ]]; then echo 'Docker Compose version v5'; exit 0; fi\n"
        "case \"$*\" in\n"
        "  *'--services') echo backend;;\n"
        "  *'--profiles') echo examples;;\n"
        "  *'--images') echo agent-manager-backend:v7.12.0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    call_log = tmp_path / "docker-calls.log"
    output = tmp_path / "evidence"
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["DOCKER_CALL_LOG"] = str(call_log)
    completed = subprocess.run(
        ["bash", str(scripts / "collect-agent-security-acceptance-evidence.sh"), "--output-dir", str(output)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert "source=release_provenance" in (output / "git-state.txt").read_text(encoding="utf-8")
    assert json.loads((output / "release-provenance.json").read_text(encoding="utf-8")) == provenance
    docker_calls = call_log.read_text(encoding="utf-8")
    assert "compose --env-file /dev/null" in docker_calls
    assert "config --no-env-resolution" in docker_calls
    assert "compose --env-file /dev/null ps" not in docker_calls
