---
name: skill-manager-guard
description: "Verify OpenClaw skills with Skill Manager before bootstrap and before tool execution"
homepage: https://docs.openclaw.ai/automation/hooks
metadata:
  {
    "openclaw": {
      "events": ["agent:bootstrap"],
      "requires": {
        "env": ["SKILL_MANAGER_BASE_URL"]
      }
    }
  }
---

# Skill Manager Guard

This internal hook verifies local skill signatures at bootstrap time.

Runtime tool gating via `before_tool_call` is provided separately in the plugin hook skeleton.

## What It Does

- Enumerates visible skills during `agent:bootstrap`
- Computes local signatures for each skill directory
- Calls Skill Manager:
  - `POST /api/v1/runtime/verify-skill-signature`
  - `GET /api/v1/runtime/can-load/{skill_name}`
- Removes blocked skills from bootstrap-visible context when possible
- Writes verification results into hook context
- Calls `GET /api/v1/runtime/check-tool` during `before_tool_call`

## Requirements

- `SKILL_MANAGER_BASE_URL`
- Optional `SKILL_MANAGER_SIGNING_KEY`

## Status

This is a starter implementation intended for integration and adaptation against a real OpenClaw gateway event payload.
