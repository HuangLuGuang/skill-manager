# QwenWork CN native acceptance samples

Captured on 2026-10-28 from the installed macOS arm64 desktop 1.4.0 (26102705), embedded engine 1.1.71. These are real, disposable-project events, not a protocol copied from another product.

- `session.jsonl`: native desktop conversation with an allowed marker write/read and a denied marker write.
- `hooks.jsonl`: captured SessionStart, UserPromptSubmit, PreToolUse, PostToolUse and Stop command-Hook stdin, including project and user configuration probes.
- `skill.jsonl`: a personal Skill discovered by the native UI and invoked through the native Skill tool. Its extension alias is preserved; the result contains no source directory.

User/project paths are anonymized. Request token anchors, signatures and thinking contents are removed; native session/call/request-set IDs and parent relations remain intact. Canonical transcripts live under `.qwenworkcn/projects`; diagnostic segment logs are a separate source. The `entrypoint: cli` field is emitted by the embedded engine and does not change the desktop product identity.

See `docs/external-agent-integration.md` for supported scope and `outputs/qwenwork-acceptance/README.md` for the local acceptance record. The latter is a local output artifact, not a required test dependency.
