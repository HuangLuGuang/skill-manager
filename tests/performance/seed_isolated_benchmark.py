#!/usr/bin/env python3
"""Seed an isolated Agent Manager instance with benchmark-only data."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from agent_manager.api.router import get_manager
from agent_manager.core.models import SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.signer import signature_content_digest
from backend import models
from backend.sqlite_db import SessionLocal


OUTPUT = Path(os.environ.get("BENCH_CREDENTIALS_PATH", "/bench/credentials.json"))
MODEL_TOKEN = "amat_" + secrets.token_urlsafe(32)
MCP_TOKEN = "amat_" + secrets.token_urlsafe(32)
RUNTIME_TOKEN = "amat_" + secrets.token_urlsafe(32)
SCANNER_TOKEN = "amat_" + secrets.token_urlsafe(32)
SKILL_NAME = "benchmark-runtime-skill"
AGENT_ID = "benchmark-agent"


def require_isolated_opt_in() -> None:
    if os.environ.get("BENCHMARK_ISOLATED") != "YES":
        raise SystemExit("refusing to seed data without BENCHMARK_ISOLATED=YES")


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def access_token(name: str, token_type: str, raw: str, scopes: list[str], **kwargs) -> models.AccessToken:
    return models.AccessToken(
        name=name,
        token_type=token_type,
        token_hash=token_hash(raw),
        token_prefix=raw[:20],
        scopes_json=json.dumps(scopes),
        status="active",
        max_body_kb=1024,
        max_concurrent_requests=100,
        max_upload_mb=50,
        max_concurrent_jobs=2,
        allowed_models_json=json.dumps(kwargs.pop("allowed_models", [])),
        allowed_mcp_gateways_json=json.dumps(kwargs.pop("allowed_mcp_gateways", [])),
        allowed_ips_json="[]",
        **kwargs,
    )


def seed_backend() -> None:
    db = SessionLocal()
    try:
        db.query(models.RequestLease).delete()

        provider = models.ModelProvider(
            name="benchmark-upstream",
            base_url="http://mock:19090/v1",
            api_format="openai",
            enabled=True,
            timeout_seconds=10,
            enable_compression=False,
        )
        db.add(provider)
        db.flush()
        db.add(
            models.ModelEndpoint(
                provider_id=provider.id,
                name="bench-model",
                display_name="Benchmark model",
                enabled=True,
                is_default=True,
            )
        )
        db.add(
            access_token(
                "benchmark-model",
                "model_gateway",
                MODEL_TOKEN,
                ["model:chat"],
                allowed_models=["bench-model"],
            )
        )
        db.add(
            models.PrivacyPolicy(
                name="Benchmark platform-overhead policy",
                enabled=False,
                group_id=None,
                entity_types_json="[]",
                entity_rules_json="{}",
                detect_system_messages=False,
                allow_bypass=True,
                mapping_ttl_days=1,
                dp_enabled=False,
                dp_epsilon=1.0,
                dp_min_count=1,
            )
        )

        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
        schema_text = json.dumps(schema, separators=(",", ":"), sort_keys=True)
        schema_hash = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
        server = models.McpServer(
            slug="bench",
            name="Benchmark MCP",
            endpoint="http://mock:19090/mcp",
            status="active",
            timeout_seconds=10,
            max_response_kb=1024,
        )
        db.add(server)
        db.flush()
        tool = models.McpTool(
            server_id=server.id,
            name="echo",
            exposed_name="bench__echo",
            description="Return the supplied text",
            input_schema_json=schema_text,
            schema_hash=schema_hash,
            enabled=True,
            risk_level="low",
            rate_limit_per_minute=100000,
            max_concurrent=100,
            requires_approval=False,
        )
        gateway = models.McpGateway(slug="benchmark", name="Benchmark gateway", status="active")
        db.add_all([tool, gateway])
        db.flush()
        db.add(
            models.McpGatewayBinding(
                gateway_id=gateway.id,
                server_id=server.id,
                allowed_tools_json=json.dumps(["echo"]),
                approved_schema_hashes_json=json.dumps({"echo": schema_hash}),
            )
        )
        db.add(
            access_token(
                "benchmark-mcp",
                "mcp_gateway",
                MCP_TOKEN,
                ["mcp:connect", "mcp:list-tools", "mcp:call-tools"],
                allowed_mcp_gateways=["benchmark"],
            )
        )

        runtime = access_token(
            "benchmark-runtime",
            "agent_runtime",
            RUNTIME_TOKEN,
            ["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"],
            bound_agent_id=AGENT_ID,
        )
        scanner = access_token(
            "benchmark-scanner",
            "scanner",
            SCANNER_TOKEN,
            ["scanner:submit", "scanner:read-own-results", "scanner:read-own-sessions"],
        )
        db.add_all([runtime, scanner])
        db.flush()
        db.add(
            models.ManagedAgent(
                agent_id=AGENT_ID,
                name="Benchmark Agent",
                status="active",
                skill_names_json=json.dumps([SKILL_NAME]),
                prompt_names_json="[]",
                runtime_token_id=runtime.id,
                runtime_token_name=runtime.name,
                created_by="benchmark",
            )
        )
        db.commit()
    finally:
        db.close()


def seed_runtime_skill() -> dict:
    root = Path("/app/runtime/bench/runtime-skill")
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\nname: benchmark-runtime-skill\ndescription: Deterministic runtime verification benchmark\n---\n\n# Benchmark\n",
        encoding="utf-8",
    )
    manager = get_manager()
    existing = manager.get_skill(SKILL_NAME)
    entry = existing or manager.submit(
        root,
        source=SourceInfo(origin=SkillOrigin.INTERNAL, author="benchmark"),
        use_behavioral=False,
        use_llm=False,
        use_sandbox=False,
    )
    if entry.status not in {SkillStatus.APPROVED, SkillStatus.DEPLOYED}:
        entry = manager.approve(entry.skill_id, reviewer="benchmark", note="isolated performance benchmark")
    return {
        "skill_id": entry.skill_id,
        "family_id": entry.family_id,
        "skill_name": entry.name,
        "local_signature": signature_content_digest(entry.signature or ""),
        "status": entry.status.value,
    }


if __name__ == "__main__":
    require_isolated_opt_in()
    seed_backend()
    runtime_skill = seed_runtime_skill()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "model_token": MODEL_TOKEN,
                "mcp_token": MCP_TOKEN,
                "runtime_token": RUNTIME_TOKEN,
                "scanner_token": SCANNER_TOKEN,
                "agent_id": AGENT_ID,
                "runtime_skill": runtime_skill,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"seeded": True, "runtime_skill": runtime_skill}))
