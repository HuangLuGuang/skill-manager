# Agent Integration Guide

How to connect a new agent with skills to the agent manager, and how the company enforces that only approved skills can run.

---

## Where Do Skills Actually Live?

**Skills are always local files.** Claude Code loads a skill by reading its `SKILL.md` from the filesystem and injecting the content as agent instructions. Agent Manager never stores or serves the skill content — it only keeps a registry of approved names, signatures, and metadata.

`can_load()` does not fetch anything remotely. It answers one question: *"Is this skill on the approved list, and (optionally) have its local files been tampered with?"*

### Three modes of `can_load()`

```
┌──────────────────────────────────────────────────────────────────────┐
│ Mode 1: Name-only check                                              │
│                                                                      │
│   can_load("my-skill")                                               │
│                                                                      │
│   Registry lookup only. Is this skill APPROVED or DEPLOYED?         │
│   No filesystem access. Skill files can be anywhere.                │
│                                                                      │
│   Use when: the directory itself is trusted (read-only, owned by    │
│   CI/CD). The controlled-directory model makes this sufficient.     │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Mode 2: Name + signature verification                                │
│                                                                      │
│   can_load("my-skill", skill_path="/path/to/skill")                 │
│                                                                      │
│   Registry lookup, recomputes the SHA256 content-tree digest, then  │
│   verifies the Ed25519 envelope stored at approval time.            │
│   Blocks if any file was added, removed, or changed since approval. │
│                                                                      │
│   Use when: the skill directory is writable (developer workstation, │
│   shared mount). Provides tamper detection as a second layer.       │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Mode 3: Name-only despite having a path (verify_sig=False)           │
│                                                                      │
│   can_load("my-skill", skill_path="...", verify_sig=False)           │
│                                                                      │
│   Checks registry but skips signature verification.                 │
│   Use for debugging or when directory protection is trusted enough.  │
└──────────────────────────────────────────────────────────────────────┘
```

### Which mode to use?

| Deployment model | Skill location | `can_load()` mode |
|---|---|---|
| Developer workstation | `./my-skill` (writable) | Mode 2 (with path + sig verify) |
| Team shared server | `/mnt/team-skills` (writable by team) | Mode 2 (with path + sig verify) |
| Company controlled dir | `/company-skills` (CI/CD only) | Mode 1 (name-only) — directory IS the guard |
| Fully remote API check | Agent calls REST API | Mode 1 via `GET /api/v1/runtime/can-load/{name}` |

> **Note:** Runtime endpoints under `/api/v1/runtime/` are accessible by Agents without admin authentication. Management endpoints (POST/PUT/DELETE) remain protected.

---

## Prompt Governance

In addition to skills, Agent Manager provides a **Prompt Registry** to govern the system instructions given to AI agents.

### Prompt Lifecycle
1. **Submit**: Developers submit a text prompt (e.g., `customer-service-v1`).
2. **Vet**: Automated scanning for prompt injection (jailbreak, instruction override, data leakage).
3. **Approve**: Manual review for high-risk prompts; auto-approval for safe ones.
4. **Sign**: Once approved, a cryptographic signature is generated for the prompt content.
5. **Verify**: Agents verify the prompt at runtime before initialization.

### Agent Integration (Prompt)

**Check status & loadability:**
```bash
curl "http://agent-manager:8080/api/v1/runtime/can-load-prompt/my-prompt"
# {"allowed": true, "status": "APPROVED"}
```

**Verify content integrity:**
```bash
curl "http://agent-manager:8080/api/v1/runtime/verify-prompt?prompt_name=my-prompt&local_content=..."
# {"valid": true, "reason": "签名校验通过"}
```

---

## Overview

Two roles interact with agent manager differently:

| Role | Concern | Primary interaction |
|---|---|---|
| **Agent developer** | "My new agent uses `file-reader` and `web-searcher` skills. How do I get them approved and running?" | CLI: `submit` → `deploy` |
| **Company / security team** | "No agent may load a skill that hasn't been vetted and approved by us." | Hooks + controlled skills directory |

---

## Part 1: Developer Workflow

### Step 1 — Write your skill

Skills follow the [Agent Skills specification](https://docs.anthropic.com/en/docs/claude-code/skills). Every skill needs a `SKILL.md` at its root with a YAML frontmatter block:

```
my-skill/
├── SKILL.md          ← required: manifest + instructions
└── scripts/
    └── helper.py     ← optional: supporting code
```

```markdown
---
name: file-reader
description: Reads project files and returns their contents. Never writes.
license: internal
allowed-tools: Read, Glob, Grep
---

# File Reader

Read files from the project. Use Read for individual files, Glob to find
files by pattern, and Grep to search file contents.
```

**Best practice: declare `allowed-tools` precisely.** The runtime guard enforces this list. Omitting a tool you actually need will cause it to be blocked at runtime.

### Step 2 — Submit for vetting

```bash
# Basic submission (static scan only)
agent-manager submit ./file-reader --author my-team --origin internal

# With deeper analysis (recommended for production skills)
agent-manager submit ./file-reader --behavioral --llm --author my-team
```

**What happens:**

```
agent-manager submit ./file-reader
        │
        ▼
  Parse SKILL.md      → extract name, description, allowed-tools, license
        │
        ▼
  Run skill-scanner   → static (YARA/regex) + behavioral + LLM analysis
        │
        ▼
  Policy gate:
    LOW risk   ──────────────────────► APPROVED (auto-signed, ready to deploy)
    MEDIUM risk (trusted author) ────► APPROVED
    MEDIUM risk (unknown) ───────────► VETTED   (human review queue)
    HIGH risk  ──────────────────────► VETTED   (human review queue)
    EXTREME    ──────────────────────► REJECTED (auto)
    Blocking policy violation ───────► REJECTED (auto)
```

Sample output for a clean skill:

```
  Skill Submitted
  file-reader  [3f2a1b4c]

  Status:        APPROVED
  Risk:          LOW
  Findings:      0
  Allowed tools: Read, Glob, Grep

Auto-approved. Run agent-manager deploy to activate.
```

Sample output for a HIGH-risk skill:

```
  Status:        VETTED
  Risk:          HIGH
  Findings:      3  (H:1 M:2)
  Policy notes:  [WARN] tool_not_in_allowlist: Tool 'Bash' is not in the company allowlist

Queued for human review. Run agent-manager review list.
```

### Step 3 — Wait for approval (HIGH risk)

If your skill is VETTED, a security reviewer needs to approve it:

```bash
# Reviewer sees the queue
agent-manager review list

# ┌──────────┬─────────────┬──────┬─────────────┬──────────────────┐
# │ ID       │ Skill Name  │ Risk │ Findings    │ Queued At        │
# ├──────────┼─────────────┼──────┼─────────────┼──────────────────┤
# │ 3f2a1b4c │ file-reader │ HIGH │ 0/1/2/0     │ 2026-03-20 09:14 │
# └──────────┴─────────────┴──────┴─────────────┴──────────────────┘

# Reviewer approves after manual review of the scan report
agent-manager review approve 3f2a1b4c --approver alice --note "Checked Bash usage, only reads stdout"

# Or rejects
agent-manager review reject 3f2a1b4c --reviewer alice --reason "Undeclared curl call on line 42"
```

You can see the full scan report to understand what was found:

```bash
agent-manager registry show file-reader --json | jq '.vetting.scan_report'
```

### Step 4 — Deploy

```bash
agent-manager deploy file-reader
# Deployed skill 'file-reader'
```

This sets status to `DEPLOYED`. APPROVED and DEPLOYED are the only two states that allow agents to load a skill.

### Step 5 — Use in your agent

The skill is now in the registry and signed. Your agent can load it — the runtime guard will let it through.

**Python (SDK usage):**

```python
from agent_manager import AgentManager

mgr = AgentManager()

# Check at agent startup
allowed, entry, reason = mgr.runtime.can_load(
    "file-reader",
    skill_path="./file-reader",
    agent_id="my-agent-v1",
)
if not allowed:
    raise RuntimeError(f"Skill blocked: {reason}")

# Check before each tool call
if not mgr.runtime.check_tool("file-reader", "Read", agent_id="my-agent-v1"):
    raise PermissionError("file-reader is not allowed to use Read")
```

**Via API (for agents without direct Python access):**

```bash
# Load check
curl "http://agent-manager:8080/api/v1/runtime/can-load/file-reader?agent_id=my-agent-v1"
# {"allowed": true, "reason": "allowed", "status": "DEPLOYED", "risk_level": "LOW"}

# Tool permission check
curl "http://agent-manager:8080/api/v1/runtime/check-tool?skill_name=file-reader&tool_name=Read"
# {"allowed": true, "skill_name": "file-reader", "tool_name": "Read"}
```

**Via Claude Code hooks (automatic — no code changes needed):**

Once hooks are installed (see Part 2), every tool call is automatically checked. Your agent code doesn't need to call the SDK directly.

---

## Part 2: Company Enforcement

The goal: **no agent can use a skill that hasn't been approved**, regardless of where the skill file came from.

There are three enforcement layers, and the company should use all three together.

---

### Layer 1: Controlled Skills Directory

The company owns the directory that Claude Code reads skills from. Only CI/CD can write there. Developers cannot drop skills into it directly.

**Setup (one-time, done by platform team):**

```bash
# Create the company skills directory (owned by CI/CD service account)
sudo mkdir -p /usr/local/share/company-skills
sudo chown ci-deploy:ci-deploy /usr/local/share/company-skills
sudo chmod 755 /usr/local/share/company-skills

# Tell all agents to use this directory
export AGENT_MANAGER_SKILLS_DIR=/usr/local/share/company-skills
```

**CI/CD deployment step** (runs after each skill is approved):

```bash
# Deploy all approved/deployed skills from registry to the controlled directory
python -m agent_manager.hooks.deploy \
  --dest /usr/local/share/company-skills \
  --clean        # remove skills that were retired
```

This copies approved skill files to the controlled directory and writes a `manifest.json`. Skills that have been retired are removed (`--clean`).

**What agents see:** Only skills that CI/CD deployed — skills the developer wrote locally are invisible unless they submitted and got approved.

---

### Layer 2: Claude Code Hooks

Hooks enforce the registry at two points in every agent session:

| Hook | Event | Enforcement |
|---|---|---|
| `ConfigChange (skills)` | A skill file is loaded mid-session | Verify it's registered + signature check |
| `PreToolUse` | Any tool is about to be invoked | Check allowed_tools of active skills |
| `SessionStart` *(strict mode)* | Agent starts | Scan all skills in skills dir, block if any unregistered |

**Install hooks for a project:**

```bash
# Project scope (.claude/settings.json) — shared with team via git
python -m agent_manager.hooks.install

# Global scope (~/.claude/settings.json) — applies to all your projects
python -m agent_manager.hooks.install --global

# Strict mode — also blocks the entire session if any unregistered skill is present
python -m agent_manager.hooks.install --strict --global
```

This writes the following into `settings.json`:

```json
{
  "hooks": {
    "ConfigChange": [
      {
        "matcher": "skills",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m agent_manager.hooks.agent_hook",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m agent_manager.hooks.agent_hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**How the hooks work:**

```
Agent session starts
        │
        ├─ [SessionStart hook, strict]
        │      Scan /usr/local/share/company-skills/
        │      For each SKILL.md → registry.get_by_name()
        │      Any unregistered? → exit 2 (block session, message to Claude)
        │
        ├─ Agent loads a skill (e.g., file-reader)
        │      [ConfigChange hook, source=skills]
        │      → registry.get_by_name("file-reader")
        │      → verify SHA256 content digest and Ed25519 signature
        │      → not registered or tampered? → exit 2 (block)
        │      → registered? → write AGENT_MANAGER_ACTIVE_SKILLS=file-reader to $CLAUDE_ENV_FILE
        │
        └─ Claude invokes Read tool
               [PreToolUse hook]
               → read AGENT_MANAGER_ACTIVE_SKILLS → ["file-reader"]
               → registry entry for file-reader: allowed_tools = ["Read", "Glob", "Grep"]
               → "Read" in allowed_tools → exit 0 (allow)

               Claude invokes Bash tool
               [PreToolUse hook]
               → "Bash" not in ["Read", "Glob", "Grep"]
               → exit 2: "[agent-manager] Tool 'Bash' is not permitted by active skill(s): 'file-reader'"
```

**When a tool is blocked,** Claude sees the message and understands it cannot use that tool. It will tell the user: *"The agent-manager policy doesn't permit me to use Bash for this skill."*

---

### Layer 3: CI/CD Gate (Prevent Unapproved Skills from Merging)

Add a vetting step to your skill publishing pipeline. Skills cannot reach the controlled directory unless the CI job passes.

**GitHub Actions example:**

```yaml
# .github/workflows/vet-skill.yml
name: Vet Skill

on:
  push:
    paths: ['skills/**']

jobs:
  vet:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install agent-manager
        run: pip install -e ./agent-manager

      - name: Vet changed skills
        env:
          AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH: ${{ runner.temp }}/agent-manager-ed25519.pem
        run: |
          for skill_dir in $(git diff --name-only HEAD~1 | grep 'skills/' | xargs -I{} dirname {} | sort -u); do
            echo "Vetting $skill_dir..."
            agent-manager submit "$skill_dir" --policy company-policy.yaml --json > result.json

            STATUS=$(jq -r '.status' result.json)
            RISK=$(jq -r '.risk_level' result.json)

            echo "Status: $STATUS  Risk: $RISK"

            if [ "$STATUS" = "REJECTED" ]; then
              echo "::error::Skill $skill_dir rejected by policy"
              cat result.json | jq '.vetting.policy_notes'
              exit 1
            fi
          done

      - name: Deploy approved skills (on main branch only)
        if: github.ref == 'refs/heads/main'
        env:
          AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH: ${{ runner.temp }}/agent-manager-ed25519.pem
        run: |
          python -m agent_manager.hooks.deploy \
            --dest /mnt/company-skills \
            --clean
```

---

### Company Policy File

The `company-policy.yaml` is the single source of truth for what the company allows. It lives in the repository and is version-controlled:

```yaml
# Enforce strict auto-approval: only LOW risk gets through automatically
auto_approve_max_risk: LOW

# These always require a security team member to approve
require_human_review:
  - MEDIUM
  - HIGH
  - EXTREME

# EXTREME risk is never allowed, even with human review
auto_reject_risk:
  - EXTREME

# These tool names are never allowed in any skill
blocked_permissions:
  - read_credentials      # blocks access to ~/.aws, .env, etc.
  - write_memory          # blocks writes to MEMORY.md
  - read_identity         # blocks access to IDENTITY.md
  - execute_shell_unrestricted

# Tools that skills may legally declare
allowed_tools_allowlist:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash           # requires security review for any skill using this
  - WebFetch
  - WebSearch
  - Agent

# Declare more than this → flagged
max_allowed_tools: 8

# All skills must have a license
require_license: true
accepted_licenses:
  - MIT
  - Apache-2.0
  - internal

# Use skill-scanner's strict preset for scanning
scanner_policy: strict
```

---

## How the Three Layers Interact

```
Developer pushes new skill
        │
        ▼
[CI/CD Gate]
  agent-manager submit → REJECTED (Bash in blocked_permissions)?
        │                → stop here, PR fails
        │
        ▼ (VETTED or APPROVED)
[Human Review] (if VETTED)
  Security team reviews, approves
        │
        ▼ (APPROVED)
[CI/CD Deploy]
  python -m agent_manager.hooks.deploy --dest /company-skills --clean
        │
        ▼
[Runtime Hooks]
  ConfigChange  → verify signature, register as active
  PreToolUse    → enforce allowed_tools
        │
        ▼
  Skill runs with exactly the permissions it declared,
  nothing more, nothing less.
```

**The key property:** A skill that was never submitted cannot appear in the controlled directory (Layer 1). A skill that somehow appeared could not be loaded without a registry entry (Layer 2 — ConfigChange hook). Even if loaded, it could not invoke undeclared tools (Layer 2 — PreToolUse hook). And if the file was modified after approval, the signature check would catch it.

---

## Retiring a Compromised Skill

If a deployed skill is found to have a vulnerability:

```bash
# Immediate revocation — takes effect on the next tool call in any agent
agent-manager retire file-reader --reason "CVE-2026-4242: exfil via Grep pattern" --actor security-team

# Deploy updated manifest to company skills dir (removes the skill files)
python -m agent_manager.hooks.deploy --dest /company-skills --clean
```

**What each agent experiences:**
- Next `PreToolUse` in any active session → `registry.get_by_name("file-reader")` → `RETIRED` → `is_loadable() = False` → blocked
- New sessions → `SessionStart` scan finds the skill is gone (removed by `--clean`) or blocked by registry

---

## Adding a New Skill to an Existing Agent

Typical developer workflow for adding `web-searcher` to an agent that already uses `file-reader`:

```bash
# 1. Write the skill
mkdir web-searcher
cat > web-searcher/SKILL.md << 'EOF'
---
name: web-searcher
description: Searches the web for information. Read-only.
license: internal
allowed-tools: WebFetch, WebSearch
---
# Web Searcher
Use WebSearch to find relevant pages, WebFetch to read them.
EOF

# 2. Submit
agent-manager submit ./web-searcher --author my-team

# 3. (If auto-approved) Deploy
agent-manager deploy web-searcher

# 4. Verify the agent can now use both skills
agent-manager runtime check file-reader
agent-manager runtime check web-searcher
```

No agent code changes required — the hooks pick up the new skill automatically on next load.

---

## Troubleshooting

**"Skill is not in the registry"**
```bash
agent-manager submit ./my-skill
```

**"Skill has status VETTED and cannot be loaded"**
Someone needs to approve it first:
```bash
agent-manager review list
agent-manager review approve <id> --approver <name>
```

**"Tool 'X' is not permitted by active skill(s)"**
The skill didn't declare that tool in its `allowed-tools`. Options:
1. Update the skill's `SKILL.md` to add the tool, re-submit
2. Use a different tool that is already declared

**"Skill FAILED signature verification"**
The skill files changed on disk after approval. Re-submit:
```bash
agent-manager submit ./my-skill  # creates a new registry entry
agent-manager deploy my-skill
```

**"Secure startup requires AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH"**
Set a persistent private-key path writable only during explicit key provisioning:
```bash
export AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH=/var/lib/agent-manager/signing/skill-ed25519.pem
agent-manager signing-key init
```
Secure production startup never creates a missing identity. All replicas must
mount the same pre-provisioned key; the public-key endpoint is read-only.
Agents and Hooks never receive this private key; they submit a keyless content
digest or verify with the public key.

**Hook not firing**
```bash
# Verify hooks are installed
cat .claude/settings.json | python3 -m json.tool

# Test the hook directly
echo '{"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "."}' \
  | python3 -m agent_manager.hooks.agent_hook
echo "exit: $?"
```
