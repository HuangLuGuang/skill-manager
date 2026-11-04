#!/usr/bin/env python3
"""Generate a Compose override without modifying the original deployment."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

SUPPORTED_IMAGES = {"langgenius/dify-api:1.15.0": "0.5.3", "langgenius/dify-api:1.16.1": "0.6.0"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose", action="append", required=True, help="Every original Compose file, in order")
    parser.add_argument("--project", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    command = ["docker", "compose", "-p", args.project]
    for path in args.compose:
        command += ["-f", str(Path(path).resolve())]
    resolved = json.loads(subprocess.check_output([*command, "config", "--format", "json"]))
    config = json.loads(args.config.read_text())
    credentials = json.loads(args.credentials.read_text())
    if not config.get("server_url", "").startswith(("http://", "https://")):
        parser.error("server_url must be an HTTP(S) URL")
    for application in config["applications"]:
        if not all(application.get(k) for k in ("binding_id", "app_id", "workspace_id")):
            parser.error("Each application requires binding_id, app_id and workspace_id")
        if not credentials.get(application["binding_id"]):
            parser.error("Missing application credential")
    root = args.output.resolve()
    if root.exists():
        parser.error("Output must be a new directory")
    services = {}
    names = ["api", "worker"]
    if resolved["services"]["api"].get("image") == "langgenius/dify-api:1.16.1":
        names.append("agent_backend")
    for name in names:
        if name not in resolved["services"]:
            parser.error(f"Missing required service: {name}")
        service = resolved["services"][name]
        if name == "agent_backend" and service.get("image") != "langgenius/dify-agent-backend:1.16.1":
            parser.error("agent_backend: requires langgenius/dify-agent-backend:1.16.1")
        if name != "agent_backend" and service.get("image") not in SUPPORTED_IMAGES:
            parser.error(f"{name}: supported images: {', '.join(SUPPORTED_IMAGES)}")
        if name != "agent_backend" and service["image"] != resolved["services"]["api"]["image"]:
            parser.error("api and worker must use the same supported image")
        existing = subprocess.check_output(["docker", "run", "--rm", "--entrypoint", "/app/api/.venv/bin/python",
            service["image"], "-c", "import importlib.util; print(bool(importlib.util.find_spec('sitecustomize')))"],
            text=True).strip()
        if existing != "False":
            parser.error(f"{name}: existing sitecustomize requires an explicit integration review")
        previous = service.get("environment", {}).get("PYTHONPATH") or "/app/api"
        services[name] = {
            "environment": {"AM_DIFY_CONFIG": "/opt/am-dify/config.json",
                            "PYTHONPATH": "/opt/am-dify/bootstrap:/opt/am-dify/python:" + previous},
            "volumes": [
                {"type": "bind", "source": str(root), "target": "/opt/am-dify", "read_only": True},
                {"type": "bind", "source": str(root / "data" / name), "target": "/var/lib/am-dify"},
            ],
        }
    root.mkdir(parents=True, mode=0o700)
    source = Path(__file__).parent
    for name in ("bootstrap", "python"):
        shutil.copytree(source / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in services:
        directory = root / "data" / name
        directory.mkdir(parents=True, mode=0o700)
    config.update(credentials_file="/opt/am-dify/credentials.json", queue_dir="/var/lib/am-dify",
                  dify_version=resolved["services"]["api"]["image"].rsplit(":", 1)[1])
    for name, value in (("config.json", config), ("credentials.json", credentials)):
        path = root / name
        path.write_text(json.dumps(value, indent=2))
        path.chmod(0o600)
    override = root / "compose.json"
    override.write_text(json.dumps({"services": services}, indent=2))
    for name in services:
        version_check = ("import dify_agent; " if name == "agent_backend" else
            f"assert importlib.metadata.version('graphon') == {SUPPORTED_IMAGES[resolved['services'][name]['image']]!r}; ")
        check = subprocess.run([
            "docker", "run", "--rm", "--entrypoint", "/app/api/.venv/bin/python",
            "-v", f"{root}:/opt/am-dify:ro", "-v", f"{root / 'data' / name}:/var/lib/am-dify",
            resolved["services"][name]["image"], "-c",
            "import json,tempfile,importlib.metadata; "
            + version_check +
            "json.load(open('/opt/am-dify/config.json')); "
            "json.load(open('/opt/am-dify/credentials.json')); "
            "f=tempfile.TemporaryFile(dir='/var/lib/am-dify'); f.close()",
        ], capture_output=True, text=True)
        if check.returncode:
            parser.error(f"{name}: mount preflight failed. Verify the supported runtime and container-user "
                         f"read/write permissions on {root}; no running Dify services were changed.")
    print(f"Created {override}. Recreate {'/'.join(names)} using the original Compose arguments plus this file.")


if __name__ == "__main__":
    main()
