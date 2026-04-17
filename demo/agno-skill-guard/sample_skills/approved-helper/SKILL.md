---
name: approved-helper
description: Safe skill used by the Agno customer demo to explain governed skill loading.
license: MIT
allowed-tools:
  - Read
metadata:
  version: "1.0.0"
  author: skill-manager-demo
---

# Approved Helper Skill

Use this skill when you need to explain how Skill Manager protects Agno skill loading.

## What To Explain

1. Skill Manager scans the skill before use.
2. Approved skills are signed.
3. Agno computes the local signature before loading the skill.
4. Runtime tool calls are checked by Skill Manager.

## Demo Talking Points

- A local skill directory is not trusted just because it exists on disk.
- The agent must verify registry status and content signature.
- Tool calls are checked at runtime, not only during submission.
