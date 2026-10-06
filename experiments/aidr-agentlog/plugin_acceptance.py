#!/usr/bin/env python3
"""Native installation checks in new private host homes; no model invocation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(binary, args, env, cwd):
    result = subprocess.run([str(binary), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"native_command_failed:{args[0]}:{result.returncode}")
    return result.stdout


def check(codex, claude, with_client=False):
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-plugin-check-")).resolve()
    market = root / "market"
    market.mkdir(mode=0o700)
    for host in ("codex", "claude"):
        shutil.copytree(repo / "client/aidr-plugins" / f"aidr-{host}", market / "plugins" / f"aidr-{host}")
    codex_manifest = market / ".agents/plugins/marketplace.json"
    codex_manifest.parent.mkdir(parents=True)
    codex_manifest.write_text(json.dumps({"name": "aidr-test", "interface": {"displayName": "AIDR isolated acceptance"}, "plugins": [{"name": "aidr-codex", "source": {"source": "local", "path": "./plugins/aidr-codex"}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Developer Tools"}]}))
    claude_manifest = market / ".claude-plugin/marketplace.json"
    claude_manifest.parent.mkdir()
    claude_manifest.write_text(json.dumps({"name": "aidr-test", "owner": {"name": "Agent Manager"}, "plugins": [{"name": "aidr-claude", "source": "./plugins/aidr-claude"}]}))
    report = {"root": str(root), "scope": "native_installation_only", "hosts": {}}
    client = root / "agent-manager-client"
    if with_client:
        subprocess.run(["go", "build", "-o", str(client), "./cmd/agent-manager-client"], cwd=repo / "scanner", check=True, capture_output=True, timeout=120)
        market = root / "exported-market"
        run(client, ["aidr-plugin-package", "--source-dir", str(repo / "client/aidr-plugins"), "--destination", str(market)], os.environ.copy(), root)
    market_name = "aidr-local" if with_client else "aidr-test"
    (root / "report.json").write_text(json.dumps(report))
    for host, binary in (("codex", codex), ("claude", claude)):
        home = root / host
        home.mkdir(mode=0o700)
        env = {**os.environ, "CODEX_HOME" if host == "codex" else "CLAUDE_CONFIG_DIR": str(home)}
        info = {"version": run(binary, ["--version"], env, root).strip()}
        report["hosts"][host] = info
        try:
            install = ["plugin", "add", f"aidr-codex@{market_name}", "--json"] if host == "codex" else ["plugin", "install", f"aidr-claude@{market_name}", "--scope", "user"]
            def install_once():
                if with_client:
                    return json.loads(run(client, ["aidr-plugin-install", "--agent", host, "--host-bin", str(binary), "--host-config-dir", str(home), "--marketplace-path", str(market)], env, root))
                run(binary, ["plugin", "marketplace", "add", str(market)], env, root)
                run(binary, install, env, root)
                return None
            info["client_first"] = install_once()
            first = json.loads(run(binary, ["plugin", "list", "--json"], env, root))
            info["client_second"] = install_once()
            second = json.loads(run(binary, ["plugin", "list", "--json"], env, root))
            rows = second["installed"] if host == "codex" else second
            assert first == second
            assert len(rows) == 1 and rows[0]["enabled"] is True and rows[0]["version"] == "0.1.0"
            assert rows[0]["pluginId" if host == "codex" else "id"] == f"aidr-{host}@{market_name}"
            info.update(first=first, second=second, repeated_install=True, hook_trust="not_verified", receiver="not_started")
            if host == "claude":
                run(binary, ["plugin", "disable", f"aidr-claude@{market_name}"], env, root)
                info["disable_method"] = "native_plugin_disable"
            else:
                # This exact file was generated in the new isolated host home.
                # Codex exposes enabled in configuration but no disable command.
                config = home / "config.toml"
                original = config.read_text()
                fragment = f'[plugins."aidr-codex@{market_name}"]\nenabled = true'
                assert original.count(fragment) == 1
                config.write_text(original.replace(fragment, fragment.replace("true", "false")))
                info["disable_method"] = "isolated_native_config"
            info["disabled"] = json.loads(run(binary, ["plugin", "list", "--json"], env, root))
            disabled_rows = info["disabled"]["installed"] if host == "codex" else info["disabled"]
            assert len(disabled_rows) == 1 and disabled_rows[0]["enabled"] is False
            if with_client:
                info["disabled_reinstall"] = install_once()
                assert info["disabled_reinstall"]["enabled"] is False
            info["status"] = "native_commands_passed"
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            info["status"] = "failed"
            info["error"] = type(exc).__name__ + ":" + str(exc)[:100]
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root / "report.json"), "hosts": {host: {key: value for key, value in info.items() if key in {"version", "status", "error"}} for host, info in report["hosts"].items()}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    parser.add_argument("--claude", required=True)
    parser.add_argument("--with-client", action="store_true")
    options = parser.parse_args()
    check(options.codex, options.claude, options.with_client)
