# Agent Manager — Design Document

## Overview

Agent Manager is an enterprise governance system for AI agent skills. It enforces a **gate-and-govern** model: skills cannot run inside agents unless they have been vetted, approved, signed, and registered. At runtime, every load and every tool call is checked against the registry.

This document explains the threat model, architecture, and — in depth — how each of the seven key security properties is designed and implemented.

---

## Threat Model

### What we're protecting

| Asset | Threat |
|---|---|
| Agent memory (`MEMORY.md`, `IDENTITY.md`) | Exfiltration by a malicious skill |
| Credentials / API keys | Harvesting via file reads or environment variable access |
| Agent instructions | Prompt injection overriding the agent's behavior |
| Other deployed skills | Tool-chaining attacks that pivot from one skill to another |
| The registry itself | Tampered approvals, unauthorized skill activation |

### Attacker classes

1. **Malicious external skill** — a skill from ClawHub or GitHub that embeds a payload (prompt injection string, hidden curl exfiltration, obfuscated eval)
2. **Compromised internal skill** — a previously-approved skill whose files are modified after approval (tampered on disk, CI/CD supply chain attack)
3. **Privilege-escalating skill** — a legitimate-looking skill that declares more tools than it needs and abuses the excess at runtime
4. **Revocation-evading skill** — an old deployed skill that persists after a security incident because there is no revocation mechanism

### Non-goals

- Agent Manager does not protect against a compromised agent runtime itself
- It does not prevent skills from making network calls that are within their declared tool scope
- Novel zero-day attack patterns not covered by skill-scanner's rule packs may not be detected

---

## Where Skills Live

**Skills are always local files.** Claude Code loads a skill by reading its `SKILL.md` from the filesystem and injecting the content as agent instructions. Agent Manager never stores or serves the skill content — the registry holds only metadata: name, status, approved tools, and a content signature.

```
  Developer's disk / Company-controlled dir / Shared mount
  ┌──────────────────────┐
  │  my-skill/           │  ← skill files live HERE, on disk
  │  ├── SKILL.md        │    (always local; never fetched remotely)
  │  └── scripts/        │
  └──────────────────────┘
            │
            │  submit once
            ▼
  ~/.agent-manager/registry.json
  ┌──────────────────────────────────────────────────────┐
  │  { name: "my-skill",  ← metadata only               │
  │    status: APPROVED,                                 │
  │    allowed_tools: ["Read","Grep"],                   │
  │    signature: "a3f8..."  ← hash of file tree        │
  │  }                                                   │
  └──────────────────────────────────────────────────────┘
            │
            │  can_load() checks this, never the files themselves
            ▼
        ALLOW / BLOCK
```

`can_load()` does not fetch or read skill files. It answers one question: *"Is this skill name on the approved list, and (optionally) do the local files match the approved hash?"*

### Three modes of `can_load()`

The behavior differs based on whether a path is provided:

**Mode 1 — Name-only** (`skill_path` omitted)
```python
can_load("my-skill")
```
Registry lookup only. No filesystem access. Answers: *is this name APPROVED or DEPLOYED?*

Use when the skill directory is already trusted — for example, a read-only company-controlled directory that only CI/CD can write to. Directory ownership IS the tamper protection; a name-only check is sufficient.

**Mode 2 — Name + signature verification** (`skill_path` provided)
```python
can_load("my-skill", skill_path="/path/to/skill")
```
Registry lookup, then recomputes HMAC-SHA256 over every file in the directory and compares to the signature stored at approval time. Catches any modification since approval: added files, changed files, removed files.

Use when the skill directory is writable — developer workstations, shared network mounts, or any environment where files could change between approval and load.

**Mode 3 — Name-only despite having a path** (`verify_sig=False`)
```python
can_load("my-skill", skill_path="...", verify_sig=False)
```
Checks registry but skips signature verification. Useful for debugging or when directory protection is already trusted but a path is still available.

### Deployment models and which mode to use

| Where skills live | Who can write | Recommended `can_load()` mode |
|---|---|---|
| `./my-skill` (developer workstation) | Developer | Mode 2 — directory is writable, verify sig |
| `/mnt/team-skills` (shared mount) | Team members | Mode 2 — multiple writers, verify sig |
| `/company-skills/` (CI/CD only, read-only) | CI/CD service account | Mode 1 — directory ownership is sufficient |
| Agent has no local disk | — | Mode 1 via REST: `GET /api/v1/runtime/can-load/{name}` |

The "company-controlled directory" pattern works like this: CI/CD runs `agent-manager-deploy --dest /company-skills --clean` after each approval. Agents read from `/company-skills/` but cannot write to it. Because only approved skills were ever deployed there, a name-only registry check confirms the skill is sanctioned.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Agent Manager                             │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐  ┌─────────┐   │
│  │  CLI /   │   │  VettingPipe │   │ Registry   │  │ Runtime │   │
│  │  API     │──►│  line        │──►│ (SQLite)   │◄─│ Guard   │   │
│  └──────────┘   └──────┬───────┘   └────────────┘  └─────────┘   │
│                        │           (metadata only)               │
│                 ┌──────▼───────┐                                 │
│                 │ skill-scanner│   ┌─────────────────────────┐   │
│                 │ (external)   │   │   Prompt Management     │   │
│                 └──────────────┘   │  Registry · Vetting     │   │
│                                    └─────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    CompanyPolicy                         │    │
│  │   auto_approve_max_risk · blocked_permissions            │    │
│  │   trusted_authors · allowed_tools_allowlist              │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### Module map

| Module | Responsibility |
|---|---|
| `core/models.py` | Core data types for skills: `RegistryEntry`, `RiskLevel`, `SkillStatus` |
| `core/prompt_models.py` | Data types for prompts: `PromptEntry`, `PromptStatus` |
| `core/policy.py` | Load and enforce `company-policy.yaml` |
| `core/signer.py` | HMAC-SHA256 signatures for both skills and prompts |
| `core/vetting.py` | Skill vetting orchestration |
| `core/prompt_manager.py` | Prompt vetting, approval, and lifecycle management |
| `core/registry.py` | High-level SQLite registry orchestrator |
| `core/prompt_registry.py` | Prompt-specific SQLite persistence |
| `core/runtime.py` | Runtime enforcement for skills and prompts |
| `core/manager.py` | Enterprise orchestrator (Skill + Prompt API) |
| `cli/cli.py` | Unified Click CLI (with local `.env` support) |
| `api/router.py` | Split Admin (Auth) and Runtime (No-Auth) REST API |

### Skill lifecycle states

```
          ┌─────────┐
  submit  │ PENDING │  (vetting in progress)
─────────►│         │
          └────┬────┘
               │ vetting complete
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌───────┐  ┌──────┐  ┌──────────┐
│VETTED │  │APPROV│  │ REJECTED │
│(queue)│  │  ED  │  │          │
└───┬───┘  └──┬───┘  └──────────┘
    │human    │ deploy
    │review   ▼
    │      ┌──────────┐
    │      │ DEPLOYED │
    │      └────┬─────┘
    │           │ retire (any state)
    └───────────┼──────────────────►┌─────────┐
                │                   │ RETIRED │
                └──────────────────►│         │
                                    └─────────┘
```

---

## Key Security Properties

### 1. No Unvetted Skill Runs

**Threat addressed:** A malicious or unreviewed skill gets loaded directly by an agent without any security check.

#### Design

Every skill load is gated by `RuntimeGuard.can_load()`. The guard checks:
1. The skill name is present in the registry
2. The registry entry has status `APPROVED` or `DEPLOYED`
3. (Optionally) the local files' HMAC-SHA256 matches the signature stored at approval time

If any check fails, the load is blocked and logged. There is no bypass path.

The registry is the **single source of truth**. There is no in-memory allowlist, no environment flag that skips the check, no fallback to "allow if the file exists."

The signature check is optional and governed by whether the caller provides a `skill_path`. This is intentional: when a company-controlled directory is in use (only CI/CD can write, only approved skills are present), a name-only check is sufficient and the directory itself provides tamper protection. When skills are on a writable path, the caller passes the path and the HMAC is verified. See *"Where Skills Live"* above for the full decision table.

#### Implementation

`core/runtime.py` — `RuntimeGuard.can_load()`:

```python
def can_load(self, skill_name, skill_path=None, agent_id=None, verify_sig=True):
    entry = self.registry.get_by_name(skill_name)

    if entry is None:
        # Not in registry at all → blocked
        self._emit_blocked(skill_name, agent_id, "not in the registry")
        return False, None, reason

    if not entry.is_loadable():
        # In registry but wrong status (VETTED, REJECTED, RETIRED, PENDING) → blocked
        return False, entry, reason

    if verify_sig and skill_path and entry.signature:
        # skill_path provided → verify local files against stored HMAC
        if not verify_signature(skill_path, entry.signature):
            # Content changed since approval → blocked as tamper
            return False, entry, reason

    # skill_path=None → name-only check, no filesystem access
    return True, entry, "allowed"
```

`core/models.py` — `RegistryEntry.is_loadable()`:

```python
def is_loadable(self) -> bool:
    return self.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED)
```

Only two states grant loadability. All other states — including `VETTED` (pending human review) — are non-loadable. A skill in the review queue cannot run.

---

### 2. Least Privilege — Tool Permission Enforcement

**Threat addressed:** A skill that only needs to read files silently calls `Bash` to exfiltrate data or `Write` to modify MEMORY.md.

#### Design

Every skill declares its tool requirements in `SKILL.md` under `allowed-tools`. This declaration is stored in the registry at submission time. At runtime, `RuntimeGuard.check_tool()` consults the registry before allowing any tool invocation.

Policy adds a second layer: `allowed_tools_allowlist` in `company-policy.yaml` constrains what any skill can even *declare*. A skill that tries to declare `read_credentials` is flagged at vetting time, before it ever reaches the registry.

The two layers are independent:
- **Policy layer** (vetting): blocks skills from declaring dangerous tools at submit time
- **Runtime layer** (enforcement): prevents a skill from invoking tools it didn't declare, at invocation time

#### Implementation

`core/vetting.py` — policy check at submit time:

```python
def check_tool_declarations(self, allowed_tools):
    for tool in allowed_tools:
        if tool.lower() not in allowlist_lower:
            violations.append(PolicyViolation(
                rule="tool_not_in_allowlist",
                message=f"Tool {tool!r} is not in the company allowlist",
            ))
    for perm in self.blocked_permissions:
        if perm.lower() in [t.lower() for t in allowed_tools]:
            violations.append(PolicyViolation(
                rule="blocked_permission",
                message=f"Tool/permission {perm!r} is explicitly blocked",
                blocking=True,  # → auto-reject, not just warn
            ))
```

`core/runtime.py` — enforcement at invocation time:

```python
def check_tool(self, skill_name, tool_name, agent_id=None):
    entry = self.registry.get_by_name(skill_name)

    if not entry.allowed_tools:
        # No declarations → allow all (backwards-compatible for legacy skills)
        return True

    allowed = tool_name in entry.allowed_tools
    if not allowed:
        self._emit_tool_blocked(skill_name, tool_name, agent_id, reason)
    return allowed
```

**Note on empty declarations:** A skill with no `allowed-tools` field is treated as having no restrictions. This preserves backwards-compatibility with skills written before enforcement was introduced. New skills written against this system should always declare their tools; enforcement can be made mandatory via policy (`require_tool_declarations: true`).

---

### 3. Tamper Detection

**Threat addressed:** An approved skill's files are modified on disk after approval — either by a supply chain attack during CI/CD, direct filesystem compromise, or a developer making undeclared changes.

#### Design

When a skill is approved (either automatically or after human review), a **content signature** is computed over the full file tree and stored in the registry. At every load, the signature of the on-disk files is recomputed and compared against the stored value.

If they differ, the load is blocked and a `skill_tamper_detected` audit event is emitted — distinct from a normal `skill_load_blocked` so that security dashboards can alert on it separately.

#### Implementation

`core/signer.py` — signature computation:

```python
def compute_signature(skill_path):
    root = Path(skill_path)
    parts = []
    for fpath in sorted(root.rglob("*")):       # sorted → deterministic
        if fpath.is_file():
            rel = fpath.relative_to(root).as_posix()
            file_hash = _content_hash(fpath)     # SHA256 of file contents
            parts.append(f"{rel}:{file_hash}\n") # "relative/path:sha256hex\n"

    content = "".join(parts).encode()

    if key := _get_key():
        return hmac.new(key, content, hashlib.sha256).hexdigest()  # authenticated
    else:
        return hashlib.sha256(content).hexdigest()                 # dev fallback
```

The signature is a single hex string covering the *entire directory tree*: every file's relative path and content hash. Adding, removing, or modifying any file changes the signature.

**HMAC vs plain SHA256:** In production (when `AGENT_MANAGER_SIGNING_KEY` is set), the signature is an HMAC-SHA256. An attacker who can write to disk could forge a plain SHA256 by recomputing it; they cannot forge an HMAC without the key. The key is an environment variable, kept out of the registry and the codebase.

**Timing-safe comparison** in `core/signer.py` — `verify_signature()`:

```python
return hmac.compare_digest(actual, expected_signature)
```

`hmac.compare_digest` is constant-time, preventing timing oracle attacks against the signature comparison.

`core/runtime.py` — tamper detection emits a distinct event:

```python
if verify_sig and skill_path and entry.signature:
    if not verify_signature(skill_path, entry.signature):
        self._emit_blocked_entry(entry, agent_id, reason, tamper=True)
        # event_type = "skill_tamper_detected" (not just "skill_load_blocked")
        return False, entry, reason
```

---

### 4. Append-Only Audit Trail

**Threat addressed:** Security incidents are undetected or unreconstructable because there is no durable record of what happened — which skills were loaded, by which agents, which tools were invoked, and who approved what.

#### Design

Every significant event in the lifecycle writes a `AuditEvent` to `audit.jsonl` — a newline-delimited JSON file opened in **append mode only**. The file is never truncated, never overwritten, and never read-then-written. Old entries are never modified.

Events cover the full lifecycle:

| Event | Trigger |
|---|---|
| `skill_submitted` | `mgr.submit()` called |
| `skill_vetted` | Vetting pipeline completes |
| `skill_queued_for_review` | suspicious skill enters review queue |
| `skill_approved` | Human approves a vetted skill |
| `skill_rejected` | Skill rejected by policy or reviewer |
| `skill_deployed` | `mgr.deploy()` called |
| `skill_retired` | `mgr.retire()` called |
| `skill_load_allowed` | `RuntimeGuard.can_load()` returns True |
| `skill_load_blocked` | `RuntimeGuard.can_load()` returns False |
| `skill_tamper_detected` | Signature mismatch on load |
| `tool_invoked` | `RuntimeGuard.check_tool()` returns True |
| `tool_blocked` | `RuntimeGuard.check_tool()` returns False |

#### Implementation

`core/registry.py` — append-only write:

```python
def log_event(self, event: AuditEvent) -> None:
    line = json.dumps(event.model_dump(mode="json"), default=str) + "\n"
    with open(self._audit_file, "a") as f:   # "a" = append only, never truncate
        f.write(line)
```

`core/models.py` — `AuditEvent` is a Pydantic model with a timestamp, unique `event_id` (UUID), event type, skill identity, actor, and a flexible `details` dict. Once written to the log, it is never modified.

Each event carries:
- `event_id` — UUID, unique per event
- `timestamp` — UTC ISO-8601
- `skill_id` + `skill_name` — both stored so the log is readable even if registry is lost
- `actor` — the human reviewer or agent ID
- `details` — event-specific payload (reason for rejection, tool name, risk level, etc.)

---

### 5. Fail-Closed on Unanalyzable Content

**Threat addressed:** A skill contains obfuscated code, a compiled binary, or a document embedding that the scanner cannot read. Rather than trusting it, a fail-open system would give it a clean bill of health. An attacker can exploit this by hiding payloads in content that scanners skip.

#### Design

This property is inherited from **skill-scanner** and reinforced by the policy layer. Skill-scanner assigns an `analyzability_score` to each scan and emits `UNANALYZABLE_BINARY` and `LOW_ANALYZABILITY` findings when content cannot be fully inspected. These findings have non-`SAFE` severity.

The vetting pipeline does not suppress or discount these findings — it treats them the same as any other finding. A skill that is 40% unanalyzable gets a risk level driven by the `LOW_ANALYZABILITY` finding, which can push it to `HIGH` and into the human review queue.

At the policy layer, `auto_reject_risk: [EXTREME]` catches skills that skill-scanner marks as fundamentally unanalyzable combined with other signals.

#### Implementation

`core/vetting.py` — no special-casing of analyzability findings:

```python
max_severity = scan_report.get("max_severity", "SAFE")
risk_level = RiskLevel.from_severity(max_severity)
```

`max_severity` is the highest severity across *all* findings, including `UNANALYZABLE_BINARY` and `LOW_ANALYZABILITY`. No finding type is filtered out before computing the risk level.

`core/models.py` — `RiskLevel.from_severity()` maps scanner severities to risk levels:

```python
mapping = {
    "SAFE":     cls.benign,
    "INFO":     cls.benign,
    "LOW":      cls.suspicious,
    "MEDIUM":   cls.suspicious,
    "HIGH":     cls.malicious,
    "EXTREME":  cls.malicious,
    "CRITICAL": cls.malicious,  # includes UNANALYZABLE when scanner flags it CRITICAL
}
```

**When skill-scanner is absent:** The vetting pipeline falls back to a basic manifest check. In this mode, only policy violations (blocked tools, bad license) are detected. The `analyzers_used` field will show `["basic"]`, which is visible in `registry show` and audit logs, making the reduced coverage explicit and auditable.

---

### 6. Human in the Loop for suspicious Risk

**Threat addressed:** Automation approves a skill with significant findings because no human reviewed the scanner report. Automated systems are good at pattern-matching known threats but cannot exercise judgment about novel or ambiguous findings.

#### Design

Skills with `suspicious` risk (configurable in policy) are placed in a **review queue** and given status `VETTED`. They cannot be loaded until a human explicitly calls `approve`. The review queue entry includes a findings summary and the full scan report is accessible via `registry show --json`.

The policy layer allows organizations to tune the threshold:
- `auto_approve_max_risk: benign` — auto-approve benign, review suspicious
- `auto_approve_max_risk: benign` — only auto-approve benign (strict mode)
- `trusted_authors` — named authors get suspicious approved without review (exception for known-good sources)

The approval step re-signs the skill. This means: even if someone manually edits the registry JSON to set a `VETTED` skill to `APPROVED`, the signature will be stale (the signing step runs inside `mgr.approve()`), and the runtime signature check will catch it at load time.

#### Implementation

`core/policy.py` — `CompanyPolicy.decide()`:

```python
def decide(self, risk_level, source, violations):
    if blocking_violations:
        return SkillStatus.REJECTED

    if risk_level in self.auto_reject_risk:
        return SkillStatus.REJECTED

    if risk_level in self.require_human_review:
        if risk_level == RiskLevel.suspicious and source.author in self.trusted_authors:
            return SkillStatus.APPROVED   # trusted author exception
        return SkillStatus.VETTED         # → human review queue

    return SkillStatus.APPROVED           # below threshold → auto-approve
```

`core/manager.py` — `mgr.submit()` enqueues the review request:

```python
if status == SkillStatus.VETTED:
    self.registry.enqueue_review(ReviewRequest(
        skill_id=entry.skill_id,
        risk_level=vetting_result.risk_level,
        findings_summary={"critical": ..., "high": ..., ...},
        notes="; ".join(vetting_result.policy_notes),
    ))
```

`core/manager.py` — `mgr.approve()` re-signs on human approval:

```python
def approve(self, skill_id, approver, note=None):
    entry = self._require_entry(skill_id)
    if entry.status != SkillStatus.VETTED:
        raise ValueError("Only VETTED skills can be approved")

    entry.status = SkillStatus.APPROVED
    entry.approved_by = approver
    entry.approved_at = datetime.now(timezone.utc)
    entry.signature = compute_signature(skill_path)  # fresh signature at approval time
    ...
```

The signature is always computed at the moment of approval against the actual files on disk. This prevents approving a skill based on a scan of version X and then loading version Y.

---

### 7. Immediate Revocability

**Threat addressed:** A deployed skill is found to contain a vulnerability (CVE, undisclosed capability, or compromised dependency). With no revocation mechanism, the skill continues to run in all agents indefinitely.

#### Design

`mgr.retire()` is designed for zero-delay revocation. It sets the registry entry status to `RETIRED` and writes to disk in a single operation. The next `can_load()` call for that skill — from any agent — returns `False` immediately.

There is no cache in the runtime guard. Every `can_load()` call reads the registry from disk. This is intentional: it means retirement takes effect on the *next* skill load, without requiring agent restarts or cache invalidation.

The retire command accepts either a skill ID or a skill name. It works regardless of current status — an `APPROVED` skill that has never been deployed can be retired just as easily as a `DEPLOYED` one.

#### Implementation

`core/manager.py` — `mgr.retire()`:

```python
def retire(self, skill_id_or_name, reason, actor=None):
    entry = self.registry.get_by_id(skill_id_or_name)
    if entry is None:
        entry = self.registry.get_by_name(skill_id_or_name)  # name fallback
    if entry is None:
        raise KeyError(...)

    entry.status = SkillStatus.RETIRED
    entry.retire_reason = reason
    entry.retired_at = datetime.now(timezone.utc)

    self.registry.update(entry)   # atomic write to registry.json
    self.registry.log_event(...)  # audit entry with reason and actor
```

`core/runtime.py` — no caching, reads registry on every call:

```python
def can_load(self, skill_name, ...):
    entry = self.registry.get_by_name(skill_name)  # fresh read from disk
    if not entry.is_loadable():                     # RETIRED → False
        return False, entry, reason
```

`core/models.py` — `is_loadable()` explicitly excludes `RETIRED`:

```python
def is_loadable(self) -> bool:
    return self.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED)
    # RETIRED, VETTED, REJECTED, PENDING all return False
```

**Revocation audit:** The retirement event is logged with `reason` and `actor`, giving a clear forensic record. For incident response, `agent-manager audit --skill <id>` shows the full history of a skill — when it was submitted, approved, deployed, and finally retired.

---

## Data Flow: Submitting a Skill

```
mgr.submit("./my-skill")
    │
    ├─► VettingPipeline.vet()
    │       ├─► _load_manifest()          parse SKILL.md frontmatter
    │       ├─► _run_scanner()            invoke skill-scanner (or basic fallback)
    │       │       └─► SkillScanner.scan_skill()
    │       │               ├─► StaticAnalyzer     (YARA + regex signatures)
    │       │               ├─► BytecodeAnalyzer   (compiled Python without source)
    │       │               └─► PipelineAnalyzer   (shell command taint tracking)
    │       ├─► RiskLevel.from_severity() map max_severity → risk level
    │       └─► _check_manifest_policy()  tool declarations, license, limits
    │
    ├─► CompanyPolicy.decide()            APPROVED / VETTED / REJECTED
    │
    ├─► compute_signature()               if APPROVED: sign now
    │
    ├─► Registry.add()                    persist RegistryEntry to registry.json
    ├─► Registry.enqueue_review()         if VETTED: add to review queue
    └─► Registry.log_event()             audit: skill_submitted + skill_vetted
```

## Data Flow: Agent Loading a Skill

The flow depends on whether the caller provides a `skill_path`.

**Mode 1 — Name-only** (company-controlled directory, no path needed):

```
can_load("my-skill")
    │
    ├─► Registry.get_by_name("my-skill")   disk read of registry.json only
    │       └─► None   → BLOCKED (not in registry)
    │       └─► VETTED → BLOCKED (awaiting human review)
    │       └─► RETIRED→ BLOCKED (revoked)
    │
    └─► APPROVED / DEPLOYED → ALLOWED
            └─► Registry.log_event(skill_load_allowed)

  No filesystem access to the skill files themselves.
  The controlled directory is trusted by construction.
```

**Mode 2 — Name + signature verification** (writable path, tamper detection on):

```
can_load("my-skill", skill_path="/path/to/skill")
    │
    ├─► Registry.get_by_name("my-skill")   disk read of registry.json
    │       └─► None / wrong status → BLOCKED
    │
    ├─► verify_signature("/path/to/skill", entry.signature)
    │       ├─► Walk all files in /path/to/skill, sorted by relative path
    │       ├─► SHA256 each file → "relpath:sha256hex\n" lines
    │       ├─► HMAC-SHA256(key, concatenated lines)
    │       └─► hmac.compare_digest(actual, stored)
    │               └─► False → BLOCKED (skill_tamper_detected event)
    │
    └─► True → ALLOWED
            └─► Registry.log_event(skill_load_allowed)
```

---

## Design Decisions and Trade-offs

### SQLite Registry

Initially stored as JSON, the registry was migrated to **SQLite** to support:
1. **Concurrent Writes** — Safe access from multiple API workers and background scan tasks.
2. **Indexing** — Efficient lookup by content fingerprint and name as the registry grows.
3. **Structured Schemas** — Native support for relational data like review queues and audit trails.

### Split Admin/Runtime API

The API is split into an **Admin Router** (requiring JWT authentication) and a **Runtime Router** (no authentication required). This design allows Agents to perform load-time verification and tool-permission checks without needing to manage long-lived administrative tokens, significantly simplifying Agent integration.

### No In-Memory Cache in RuntimeGuard

Every `can_load()` consults the SQLite registry. This makes retirement instant but adds a database read on every skill load. SQLite's performance is sufficient for the target scale of enterprise agents.

### Lingxi Scenario (Real-World Demo)

The "Lingxi Enterprise Assistant" scenario (located in `demo/enterprise-governance-demo`) serves as the primary demonstration of this architecture. It showcases:
- **Prompt Injection Defense**: Preventing an assistant from revealing executive salaries.
- **Malicious Skill Detection**: Identifying hidden data exfiltration in a welfare calculation tool.
- **Closed-Loop Verification**: An Agno-based agent that refuses to start if its instructions or tools have been tampered with.

### Fail-Open for Empty `allowed_tools`

Skills with no `allowed-tools` declaration are allowed to invoke any tool. The alternative — blocking all tool calls from undeclared skills — would break every existing skill written before this system existed. The right long-term posture is to require declarations via policy (`require_tool_declarations: true`), giving teams a migration window.

### HMAC Key Stored in Environment

The signing key is read from `AGENT_MANAGER_SIGNING_KEY` at runtime. This is a deliberate choice: the key must not be in the codebase, and it must be rotatable without a code change. In production, inject it via your secrets manager (Vault, AWS Secrets Manager, etc.).

---

## Integration Points

### skill-scanner

The vetting pipeline imports `skill_scanner.SkillScanner` if available. If not installed, it falls back to a basic manifest check. Install with:

```bash
pip install -e ".[scanner]"
```

Enable deeper analysis at submit time:

```bash
agent-manager submit ./my-skill --behavioral --llm
```

### CI/CD

Add a vetting step to your skill publishing pipeline:

```yaml
# .github/workflows/publish-skill.yml
- name: Vet skill
  run: |
    agent-manager submit ./my-skill --policy company-policy.yaml --json > result.json
    STATUS=$(jq -r '.status' result.json)
    if [ "$STATUS" = "REJECTED" ]; then
      echo "Skill rejected by policy"
      exit 1
    fi
```

### Agent Startup

Call the runtime check before loading any skill:

```python
guard = RuntimeGuard()
allowed, entry, reason = guard.can_load(skill_name, skill_path=skill_dir)
if not allowed:
    raise RuntimeError(f"Skill {skill_name!r} blocked: {reason}")
```

Or via the API (for agents that don't have direct Python access):

```
GET /api/v1/runtime/can-load/my-skill?skill_path=/path/to/skill&agent_id=agent-1
```

### Audit Monitoring

The `audit.jsonl` file is structured for ingestion by any log aggregation system (Splunk, Datadog, ELK). Filter for high-priority events:

```bash
# Tamper detection events (page immediately)
grep '"skill_tamper_detected"' ~/.agent-manager/audit.jsonl

# Blocked load attempts
grep '"skill_load_blocked"' ~/.agent-manager/audit.jsonl | jq '.details.reason'
```
