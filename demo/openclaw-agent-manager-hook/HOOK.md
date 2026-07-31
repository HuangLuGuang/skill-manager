---
name: agent-manager-guard
description: "Verify OpenClaw skills with Agent Manager before bootstrap and before tool execution"
homepage: https://docs.openclaw.ai/automation/hooks
metadata:
  {
    "openclaw": {
      "events": ["agent:bootstrap"],
      "requires": {
        "env": ["AGENT_MANAGER_BASE_URL", "AGENT_MANAGER_ACCESS_TOKEN"]
      }
    }
  }
---

# Agent Manager Guard

This internal hook verifies local skill signatures at bootstrap time.

Runtime tool gating via `before_tool_call` is provided separately in the plugin hook skeleton.

## What It Does

- Enumerates visible skills during `agent:bootstrap`
- Computes local signatures for each skill directory
- Calls Agent Manager:
  - `POST /api/v1/access/runtime/verify-skill-signature`
  - `GET /api/v1/access/runtime/can-load/{skill_name}`
- Removes blocked skills from bootstrap-visible context when possible
- Writes verification results into hook context
- Calls `GET /api/v1/access/runtime/check-tool` during `before_tool_call`

## Requirements

- `AGENT_MANAGER_BASE_URL`
- `AGENT_MANAGER_ACCESS_TOKEN`
- No server signing secret is required; the hook submits a keyless content digest.

## Status

This is a starter implementation intended for integration and adaptation against a real OpenClaw gateway event payload.
