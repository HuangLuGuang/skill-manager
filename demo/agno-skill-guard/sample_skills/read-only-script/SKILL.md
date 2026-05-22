---
name: read-only-script
description: Skill that declares only Read permission but contains a script, used to demo runtime tool blocking.
license: MIT
allowed-tools:
  - Read
metadata:
  version: "1.0.0"
  author: agent-manager-demo
---

# Read Only Script Skill

This skill intentionally contains a script while only declaring `Read`.

The Agno demo uses it to show that:

1. The skill can be approved and loaded after signature verification.
2. Reading the skill is allowed.
3. Executing the script maps to `Bash`.
4. Agent Manager blocks `Bash` because it is not declared in `allowed-tools`.

## Script

Use `get_skill_script("read-only-script", "maintenance.py", execute=True)` to demonstrate runtime blocking.
