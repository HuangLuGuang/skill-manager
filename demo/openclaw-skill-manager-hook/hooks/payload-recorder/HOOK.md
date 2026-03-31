---
name: payload-recorder
description: "Record OpenClaw hook payloads for agent bootstrap debugging"
metadata:
  {
    "openclaw": {
      "events": ["agent:bootstrap"],
      "requires": {
        "bins": ["node"]
      }
    }
  }
---

# Payload Recorder

Writes the raw `agent:bootstrap` payload to a JSONL log file so you can adapt the Skill Manager hook to the real gateway event shape.
