# Agent Manager

Enterprise skill lifecycle manager for AI agents. Gate-and-govern model: every skill is vetted before deployment and governed at runtime via signature verification and permission enforcement.

Built on top of [skill-scanner](../skill-scanner) for deep threat detection.

For a full project guide covering principles, architecture, admin console, runtime governance, and usage, see:
[docs/project-guide.md](docs/project-guide.md)

For external agent integration patterns, see:
[docs/external-agent-integration.md](docs/external-agent-integration.md)

For agent-side signature verification details, see:
[docs/agent-signature-verification.md](docs/agent-signature-verification.md)

For sandbox backend architecture and isolated execution service design, see:
[docs/sandbox-service-architecture.md](docs/sandbox-service-architecture.md)

For a quick start using the local mock remote sandbox service, see:
[docs/remote-sandbox-mock-quickstart.md](docs/remote-sandbox-mock-quickstart.md)

For the production-oriented isolated sandbox service, see:
[services/isolated-sandbox-service/README.md](services/isolated-sandbox-service/README.md)

For Dockerfiles and docker-compose based deployment, see:
[docs/docker-deployment.md](docs/docker-deployment.md)

For the built-in LLM model gateway and privacy router, see:
[docs/model-gateway.md](docs/model-gateway.md)

For OpenClaw hook integration with Agent Manager, see:
[docs/openclaw-agent-manager-hooks.md](docs/openclaw-agent-manager-hooks.md)

For a starter OpenClaw hook pack demo, see:
[demo/openclaw-agent-manager-hook/README.md](demo/openclaw-agent-manager-hook/README.md)

---

## How Skills Are Stored

**Skills are always local files** — Claude Code loads a skill by reading its `SKILL.md` from the filesystem. Agent Manager never stores or serves skill content. The registry holds only metadata: name, approval status, allowed tools, and a content hash.

`can_load()` does not fetch anything remotely. It checks the registry and (optionally) verifies that the on-disk files haven't changed since approval.

### Three modes of `can_load()`

```python
# Mode 1 — Name-only: just checks registry, no filesystem access
#   Use when: skill lives in a read-only company-controlled directory
can_load("my-skill")

# Mode 2 — Name + signature: checks registry then verifies local files
#   Use when: skill directory is writable (developer workstation, shared mount)
can_load("my-skill", skill_path="/path/to/skill")

# Mode 3 — Skip sig even with path (debug / trusted dir)
can_load("my-skill", skill_path="...", verify_sig=False)
```

### Which mode fits your deployment

| Where skills live | Who can write | Use |
|---|---|---|
| `./my-skill` (developer workstation) | Developer | Mode 2 — writable, verify signature |
| `/mnt/team-skills` (shared mount) | Team | Mode 2 — multiple writers |
| `/company-skills/` (CI/CD only) | CI/CD service account | Mode 1 — directory ownership is sufficient |
| No local disk | — | Mode 1 via REST API |

In the company-controlled directory model, CI/CD runs `agent-manager-deploy` after each approval to write the approved files to `/company-skills/`. Agents can read from there but cannot write to it, so a name-only check is as strong as a signature check.

---

## The Problem

AI agent skills are code that runs with the agent's full permissions. A compromised skill can:

- Exfiltrate credentials and memory files
- Inject instructions into the agent's context
- Chain tool calls to escalate privileges
- Execute arbitrary commands through `Bash`

Without a governance layer, any skill — from any source — can be loaded by any agent. Agent Manager closes this gap.

---

## How It Works

```
Developer / External Source
        │
        ▼
   [SUBMIT]  ──── agent-manager submit ./my-skill
        │
        ▼
   [VET]     ──── skill-scanner (static + behavioral + LLM) + policy checks
        │
        ├── benign risk       → APPROVED (auto, signed)
        ├── suspicious risk   → VETTED (human review queue)
        └── malicious risk  → REJECTED (auto)
        │
        ▼
   [REVIEW]  ──── Human reviewer approves or rejects (suspicious)
        │
        ▼
   [SIGN]    ──── HMAC-SHA256 over full content tree → stored in registry
        │
        ▼
   [DEPLOY]  ──── agent-manager deploy my-skill
        │
        ▼
   [RUNTIME] ──── Registry check + signature verification on every load
                  Tool permission enforcement on every tool call
                  Audit logging for every event
        │
        ▼
   [RETIRE]  ──── agent-manager retire my-skill --reason "CVE-2026-0001"
                  Immediate revocation — all agents blocked instantly
```

Agent Manager also includes an LLM model gateway:

```
Client / Agent
        │
        ▼
   [LLM API KEY] ── model scope / body size / concurrency checks
        │
        ▼
   [PRIVACY]     ── PII detection → pseudonym tokens → upstream model call
        │
        ▼
   [RESTORE]     ── response de-pseudonymization
        │
        ▼
   [TRACE]       ── request audit + four-stage pipeline trace
```

It exposes OpenAI-compatible `POST /v1/chat/completions`, compatibility aliases `POST /` and `POST /chat/completions`, `GET /v1/models`, and the namespaced `POST /api/v1/llm/chat/completions`. Configure providers, models, API keys, user groups, and privacy policies in the admin console under **模型网关**. See [docs/model-gateway.md](docs/model-gateway.md).

---

## Installation

```bash
# Install base (no scanner)
pip install -e .

# Install with skill-scanner integration
pip install -e ".[scanner]"

# Development
pip install -e ".[dev]"
```

Set the signing key (required in production):

```bash
export AGENT_MANAGER_SIGNING_KEY="$(openssl rand -hex 32)"
```

Override the default data directory (`~/.agent-manager/`):

```bash
export AGENT_MANAGER_DATA_DIR="/var/lib/agent-manager"
```

---

## Quick Start

```bash
# 1. Vet and submit a skill
agent-manager submit ./my-skill

# 2. Check what happened
agent-manager registry show my-skill

# 3. Deploy it (if auto-approved)
agent-manager deploy my-skill

# 4. Runtime check (call from agent startup)
agent-manager runtime check my-skill --path ./my-skill

# 5. If a HIGH-risk skill is pending review
agent-manager review list
agent-manager review approve <id> --approver alice --note "Reviewed, no issues"

# 6. Revoke a compromised skill immediately
agent-manager retire my-skill --reason "CVE-2026-0001"
```

---

## CLI Reference

### `submit`

Vet a skill directory and submit it to the registry.

```
agent-manager submit <path> [OPTIONS]

Options:
  --author TEXT       Author/publisher identifier
  --origin TEXT       Source origin: local|github|clawhub|internal (default: local)
  --behavioral        Enable behavioral/dataflow analysis (slower)
  --llm               Enable LLM semantic analysis (requires API key)
  --policy PATH       Path to company-policy.yaml
  --json              Output result as JSON
```

### `review`

```
agent-manager review list
agent-manager review approve <skill-id> --approver <name> [--note TEXT]
agent-manager review reject  <skill-id> --reviewer <name>  --reason TEXT
```

### `registry`

```
agent-manager registry list [--status PENDING|VETTED|APPROVED|DEPLOYED|REJECTED|RETIRED]
agent-manager registry show <name-or-id> [--json]
```

### `deploy`

```
agent-manager deploy <name-or-id> [--actor TEXT]
```

### `retire`

```
agent-manager retire <name-or-id> --reason TEXT [--actor TEXT]
```

### `audit`

```
agent-manager audit [--since HOURS] [--skill SKILL_ID] [--limit N] [--json]
```

### `runtime`

```
agent-manager runtime check  <skill-name> [--path PATH] [--agent AGENT_ID]
agent-manager runtime verify <skill-name> <path>
```

---

## API Server

```bash
agent-manager-api --host 0.0.0.0 --port 8080
```

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/skills/submit-zip` | Submit a skill ZIP for vetting |
| `GET`  | `/api/v1/skills` | List registry entries |
| `POST` | `/api/v1/skills/{id}/approve` | Approve a vetted skill |
| `POST` | `/api/v1/skills/{id}/reject` | Reject a vetted skill |
| `POST` | `/api/v1/skills/{id}/deploy` | Mark a skill as deployed |
| `POST` | `/api/v1/skills/{id}/retire` | Retire a skill immediately |
| `POST` | `/api/v1/access/runtime/verify-skill-signature` | Token-auth runtime signature check for external agents |
| `GET`  | `/api/v1/access/runtime/can-load/{name}` | Token-auth runtime load check for external agents |
| `GET`  | `/api/v1/access/runtime/check-tool` | Token-auth tool permission check for external agents |
| `POST` | `/` | Compatibility alias for clients that treat the configured endpoint as the full chat URL |
| `POST` | `/v1/chat/completions` | OpenAI-compatible privacy model gateway |
| `POST` | `/chat/completions` | Compatibility alias for clients whose base URL omits `/v1` |
| `GET`  | `/v1/models` | OpenAI-compatible model list for the current LLM API Key |
| `GET`  | `/api/v1/audit` | Audit trail |

---

## Python SDK

```python
from agent_manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.models import SourceInfo, SkillOrigin

policy = CompanyPolicy.load("company-policy.yaml")
mgr = AgentManager(policy=policy)

# Submit and vet a skill
entry = mgr.submit("./my-skill", source=SourceInfo(origin=SkillOrigin.GITHUB, author="my-team"))

# Deploy if approved
if entry.status.value == "APPROVED":
    mgr.deploy(entry.skill_id)

# --- Runtime checks (choose the mode that matches your deployment) ---

# Mode 1: name-only — skill is in a company-controlled read-only directory
allowed, entry, reason = mgr.runtime.can_load("my-skill")

# Mode 2: name + signature — skill is on a writable local path
allowed, entry, reason = mgr.runtime.can_load("my-skill", skill_path="./my-skill")

if not allowed:
    raise RuntimeError(f"Skill load blocked: {reason}")

# Tool permission check (works regardless of mode above)
if not mgr.runtime.check_tool("my-skill", "Bash"):
    raise PermissionError("Skill not permitted to use Bash")
```

---

## Company Policy

Copy `company-policy.example.yaml` to `company-policy.yaml` and customize:

```yaml
auto_approve_max_risk: benign          # AUTO-APPROVE up to this risk level
require_human_review: [suspicious]
auto_reject_risk: [malicious]

blocked_permissions:
  - read_credentials
  - write_memory
  - read_identity

trusted_authors:
  - internal-team
  - vetted-vendor-a               # MEDIUM risk auto-approved for trusted authors

allowed_tools_allowlist:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep

scanner_policy: balanced           # strict | balanced | permissive
```

---

## Storage Layout

Data is stored in `~/.agent-manager/` (override with `AGENT_MANAGER_DATA_DIR`):

```
~/.agent-manager/
├── registry.json      # Skill registry (list of RegistryEntry objects)
├── audit.jsonl        # Append-only audit log (one JSON event per line)
└── review.json        # Pending human review queue
```

---

## Tests

```bash
pytest
pytest tests/test_runtime.py -v      # runtime guard tests
pytest tests/test_manager.py -v      # integration tests
```

---

## Security

See [DESIGN.md](DESIGN.md) for the full security architecture and implementation details.

To report a vulnerability, contact your internal security team.
