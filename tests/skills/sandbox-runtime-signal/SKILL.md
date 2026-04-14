---
name: sandbox-runtime-signal
description: Test skill that intentionally emits runtime signals for sandbox validation.
allowed-tools:
  - Bash
license: MIT
---

# Sandbox Runtime Signal

This skill is intentionally unsafe and should only be used to verify the sandbox analysis pipeline.

It is designed to produce observable runtime signals when the sandbox probe executes `scripts/run.py`:

- outbound network attempt
- credential-related output
- dynamic execution keyword
- filesystem permission failure
- non-zero exit code

