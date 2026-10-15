#!/usr/bin/env python3
"""Start or upgrade an Agent Manager offline installation (Python standard library only)."""

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


DEPLOY_FILES = (
    "docker-compose.yaml", ".env.example", "release-provenance.json",
    "start.sh", "upgrade.sh", "deploy/offline.py", "deploy/nginx/default.conf",
    "docs/offline-deployment.md", "docs/docker-deployment.md", "docs/license.md",
)
COMPOSE_COMMAND = ("docker", "compose")


class DeploymentError(RuntimeError):
    pass


def probe(args):
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=20,
                              env=dict(os.environ, LC_ALL="C", LANG="C"))
    except subprocess.TimeoutExpired:
        raise DeploymentError(f"检查 {' '.join(args[:2])} 超时；请检查 Docker 服务、当前 context 和连接配置") from None
    except PermissionError:
        raise DeploymentError(f"没有执行 {args[0]} 的权限；请检查程序文件权限") from None


def check_runtime():
    if not shutil.which("docker"):
        raise DeploymentError("未找到 docker 命令：Docker 未安装或未加入 PATH；请先使用 installers/ 中的离线安装程序安装 Docker")
    result = probe(["docker", "info", "--format", "{{.Architecture}}"])
    if result.returncode:
        error = (result.stdout + result.stderr).lower()
        if any(text in error for text in ("permission denied", "access is denied", "operation not permitted")):
            raise DeploymentError("当前用户无权访问 Docker 服务；请使用有 Docker 权限的账号，或由管理员配置 Docker 用户组后重新登录（rootless Docker 请检查当前用户的 socket/context）")
        if any(text in error for text in ("cannot connect", "connection refused", "is the docker daemon running", "no such file or directory")):
            raise DeploymentError("无法连接 Docker 服务：服务可能未启动，或当前 context/DOCKER_HOST 指向不可达地址；本机 systemd 环境请检查 systemctl status docker，确认后执行 sudo systemctl start docker；rootless 环境检查 systemctl --user status docker")
        raise DeploymentError("Docker 服务检查失败；请运行 docker info 查看详情，并检查当前 context、DOCKER_HOST、TLS 或认证配置")
    architecture = result.stdout.strip()
    candidates = [("docker", "compose")]
    if shutil.which("docker-compose"):
        candidates.append(("docker-compose",))
    incompatible = []
    for command in candidates:
        if probe([*command, "version"]).returncode:
            continue
        supported = True
        for action, options in (("up", ("--wait", "--wait-timeout")), ("config", ("--format",))):
            help_result = probe([*command, action, "--help"])
            if help_result.returncode or any(not re.search(r"(?<![\w-])" + re.escape(option) + r"(?![\w-])", help_result.stdout) for option in options):
                supported = False
                break
        if supported:
            print(f"[INFO] Docker 服务可用；使用 {' '.join(command)}", flush=True)
            return architecture, command
        incompatible.append(" ".join(command))
    if incompatible:
        raise DeploymentError(f"Compose 版本不兼容（{', '.join(incompatible)}）：需支持 up --wait、--wait-timeout 和 config --format json；请升级 Compose，旧版 Python docker-compose v1 不满足要求")
    raise DeploymentError("未找到可用的 Docker Compose：docker compose 和 docker-compose 均不可用；请安装 Compose 插件或支持所需功能的独立 docker-compose，并确认可通过 version 命令运行")


def run(args, *, capture=False, cwd=None, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE if capture else None)
    if result.returncode:
        # Compose config can contain credentials; never print its captured output.
        raise DeploymentError(f"命令失败（退出码 {result.returncode}）：{' '.join(map(str, args))}")
    return result.stdout.strip() if capture else None


def compose(root, *args, source=None, capture=False):
    command = [*COMPOSE_COMMAND, "--project-directory", str(root),
               "-f", str((source or root) / "docker-compose.yaml")]
    if (root / ".env").exists():
        command += ["--env-file", str(root / ".env")]
    env = dict(os.environ)
    # The installation's saved port also applies when upgrading from another shell.
    env.pop("HTTP_PORT", None)
    return run(command + list(args), capture=capture, cwd=root, env=env)


def prepare_environment(root, port=None):
    path = root / ".env"
    if not path.exists():
        shutil.copyfile(root / ".env.example", path)
        path.chmod(0o600)
        print("[INFO] 已从配置模板创建 .env；生产配置说明见 docs/offline-deployment.md", flush=True)
    if port is not None:
        text = path.read_text()
        pattern = r"(?m)^[ \t]*(?:export[ \t]+)?HTTP_PORT[ \t]*=.*$"
        if re.search(pattern, text):
            text = re.sub(pattern, f"HTTP_PORT={port}", text)
        else:
            text = text.rstrip("\n") + f"\nHTTP_PORT={port}\n"
        path.write_text(text)
        print(f"[INFO] 访问端口 {port} 已保存到 .env（HTTP_PORT）", flush=True)


@contextmanager
def installation_lock(root):
    with (root / ".offline-deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError("该安装目录正在执行启动或升级，请等待现有操作结束") from None
        yield


def read_release(source):
    for name in DEPLOY_FILES:
        if not (source / name).is_file():
            raise DeploymentError(f"安装包缺少部署文件：{name}")
    release = json.loads((source / "release-provenance.json").read_text())
    if not isinstance(release, dict):
        raise DeploymentError("安装包版本信息必须为 JSON 对象")
    version = release.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", version):
        raise DeploymentError("安装包版本号无效")
    architecture = {"linux/amd64": "x86", "linux/arm64": "arm"}.get(release.get("platform"))
    if not architecture:
        raise DeploymentError("安装包架构必须为 linux/amd64 或 linux/arm64")
    image = Path("docker_images") / architecture / f"agent-manager-images-{version}.tar.xz"
    if not (source / image).is_file() or (source / image).stat().st_size == 0:
        raise DeploymentError(f"安装包缺少离线镜像：{image}")
    return release, image


def preflight(root, source):
    global COMPOSE_COMMAND
    release, image = read_release(source)
    architecture, COMPOSE_COMMAND = check_runtime()
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(architecture, architecture)
    if release["platform"] != f"linux/{architecture}":
        raise DeploymentError(f"安装包架构 {release['platform']} 与 Docker 架构 {architecture} 不一致")
    try:
        config = json.loads(compose(root, "config", "--format", "json", source=source, capture=True))
    except (DeploymentError, ValueError):
        raise DeploymentError("Compose 无法解析部署配置；请检查 .env 和 docker-compose.yaml，并确认 Compose 支持当前编排格式（包括 env_file.required）") from None
    images = {service["image"] for service in config["services"].values()}
    for name in images:
        if name.startswith("agent-manager-") and name.rsplit(":", 1)[-1] != release["version"]:
            raise DeploymentError("Compose 应用镜像版本与安装包版本不一致")
    return release, image, images


def load_images(source, image, images, platform):
    print(f"[INFO] 加载离线镜像：{image}", flush=True)
    run(["docker", "load", "--input", str(source / image)])
    for name in sorted(images):
        actual = run(["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", name], capture=True)
        if actual != platform:
            raise DeploymentError(f"镜像 {name} 架构为 {actual}，期望 {platform}")


def start_services(root, timeout, *, upgrade=False):
    prepare_environment(root)
    # The CLI keeps an existing signing key and only creates a missing identity.
    compose(root, "run", "--rm", "--no-deps", "--pull", "never",
            "backend", "agent-manager", "signing-key", "init")
    args = ["up", "-d", "--pull", "never", "--no-build", "--wait", "--wait-timeout", str(timeout)]
    if upgrade:
        args.append("--force-recreate")
    try:
        compose(root, *args)
        compose(root, "exec", "-T", "backend", "python", "-m", "backend.aidr_signing", "--check")
        compose(root, "exec", "-T", "nginx", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/")
    except DeploymentError:
        compose(root, "ps", "--all")
        raise
    compose(root, "ps")
    print("[INFO] 服务健康检查及 Nginx 页面检查通过", flush=True)


def extract_package(archive, destination):
    """Extract regular files under agent-manager/ without following archive links."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.parts[0] != "agent-manager"
                    or not (member.isdir() or member.isfile())):
                raise DeploymentError(f"安装包包含不安全路径或文件类型：{member.name}")
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as incoming, target.open("wb") as output:
                    shutil.copyfileobj(incoming, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return destination / "agent-manager"


def backup_installation(root):
    backups = root / "backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=backups))
    for name in (*DEPLOY_FILES, ".env", "scanner/releases"):
        original = root / name
        if original.exists():
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if original.is_dir():
                shutil.copytree(original, target)
            else:
                shutil.copy2(original, target)
    print(f"[INFO] 部署文件备份完成：{backup}（不含数据库和数据卷）", flush=True)
    return backup


def install_release(root, source, image):
    files = [Path(name) for name in DEPLOY_FILES] + [image]
    if (source / "scanner/releases").is_dir():
        files += [path.relative_to(source) for path in (source / "scanner/releases").rglob("*") if path.is_file()]
    for name in files:
        destination = root / name
        # Installation directories are reused; avoid writing through a pre-existing symlink.
        if destination.resolve() != destination:
            raise DeploymentError(f"部署目标路径包含软链接：{name}")
    for name in files:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Source and destination are on the same filesystem (upgrade staging is inside root).
        os.replace(source / name, destination)
    (root / "scanner/releases").mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "upgrade"))
    parser.add_argument("archive", nargs="?", type=Path, help="升级用安装包 .tar.gz")
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--wait-timeout", type=int, default=300, help="服务健康检查等待秒数，默认 300")
    parser.add_argument("--port", type=int, help="启动时保存 HTTP 端口（1–65535）；未指定时沿用 .env，首次默认 80")
    args = parser.parse_intermixed_args()
    if args.port is not None and (args.action != "start" or not 1 <= args.port <= 65535):
        parser.error("--port 仅用于 start，取值必须为 1–65535；升级沿用 .env 中的 HTTP_PORT")
    if args.wait_timeout < 1:
        parser.error("--wait-timeout 必须大于 0")
    root = args.install_dir.resolve(strict=True)
    with installation_lock(root):
        if args.action == "start":
            read_release(root)
            prepare_environment(root, args.port)
            release, image, images = preflight(root, root)
            load_images(root, image, images, release["platform"])
            start_services(root, args.wait_timeout)
            print(f"[INFO] 版本 {release['version']} 启动完成")
        else:
            if args.archive is None or not args.archive.is_file():
                parser.error("upgrade 需要指定存在的安装包")
            if not (root / "docker-compose.yaml").is_file():
                raise DeploymentError("目标目录缺少现有 docker-compose.yaml，请指定已有安装目录")
            with tempfile.TemporaryDirectory(prefix=".upgrade-", dir=root) as staging:
                source = extract_package(args.archive, Path(staging))
                release, image, images = preflight(root, source)
                backup = backup_installation(root)
                try:
                    load_images(source, image, images, release["platform"])
                    install_release(root, source, image)
                    start_services(root, args.wait_timeout, upgrade=True)
                except Exception:
                    print(f"[ERROR] 升级未完成，部署文件备份保留在 {backup}；请检查服务状态及数据迁移情况", file=sys.stderr)
                    raise
                print(f"[INFO] 已升级到 {release['version']}；备份：{backup}")


if __name__ == "__main__":
    try:
        main()
    except (DeploymentError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
