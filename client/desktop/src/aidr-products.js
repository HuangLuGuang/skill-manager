window.aidrProducts = [
  {
    "id": "claude",
    "name": "Claude Code",
    "entry": "cli",
    "os": [
      "darwin",
      "linux",
      "windows"
    ],
    "logs": "claude-jsonl",
    "roots": [
      ".claude/projects"
    ],
    "hooks": "native-plugin",
    "block": true,
    "approval": true,
    "evidence": "existing",
    "docs": [
      "https://code.claude.com/docs/en/hooks"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PostToolUseFailure": "tool.failure",
      "PermissionRequest": "permission.request",
      "PermissionDenied": "permission.denied",
      "SubagentStart": "agent.start",
      "SubagentStop": "agent.stop",
      "PreCompact": "context.compact.start",
      "PostCompact": "context.compact.end",
      "Stop": "turn.stop",
      "Notification": "notification",
      "TaskCompleted": "task.completed",
      "TeammateIdle": "agent.idle"
    },
    "managed": true,
    "sample_versions": [],
    "log_os": [
      "darwin",
      "linux",
      "windows"
    ],
    "hook_os": [
      "darwin",
      "linux"
    ],
    "skill_usage": {
      "invocation": true,
      "file_access": true,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "codex",
    "name": "Codex",
    "entry": "cli-app-server",
    "os": [
      "darwin",
      "linux",
      "windows"
    ],
    "logs": "codex-jsonl",
    "roots": [
      ".codex/sessions"
    ],
    "hooks": "native-plugin",
    "block": true,
    "approval": true,
    "evidence": "existing",
    "docs": [
      "https://developers.openai.com/codex/"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PermissionRequest": "permission.request",
      "SubagentStart": "agent.start",
      "SubagentStop": "agent.stop",
      "PreCompact": "context.compact.start",
      "PostCompact": "context.compact.end",
      "Stop": "turn.stop",
      "Interrupt": "turn.interrupt"
    },
    "managed": true,
    "sample_versions": [],
    "log_os": [
      "darwin",
      "linux",
      "windows"
    ],
    "hook_os": [
      "darwin",
      "linux"
    ],
    "skill_usage": {
      "invocation": false,
      "file_access": true,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "workbuddy",
    "name": "WorkBuddy",
    "entry": "desktop",
    "os": [
      "darwin"
    ],
    "logs": "workbuddy-jsonl",
    "roots": [
      ".workbuddy/projects"
    ],
    "hooks": "workbuddy-settings",
    "block": true,
    "approval": false,
    "evidence": "local-source-and-log-sample",
    "docs": [
      "https://www.codebuddy.cn/docs/workbuddy/Plugins"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PostToolUseFailure": "tool.failure",
      "Stop": "turn.stop"
    },
    "managed": false,
    "sample_versions": [
      "5.6.2"
    ],
    "log_os": [
      "darwin"
    ],
    "hook_os": [
      "darwin"
    ],
    "skill_usage": {
      "invocation": true,
      "file_access": true,
      "result_source": "native_base_directory",
      "new_call_e2e": "passed_macos_5.6.2_2026-10-07"
    }
  },
  {
    "id": "qoder-cli",
    "name": "Qoder CLI",
    "entry": "cli",
    "os": [
      "darwin"
    ],
    "logs": "qoder-jsonl",
    "roots": [
      ".qoder/projects"
    ],
    "hooks": "",
    "block": false,
    "approval": false,
    "evidence": "local-log-sample",
    "docs": [
      "https://docs.qoder.com/cli/hooks"
    ],
    "hook_events": {},
    "managed": false,
    "sample_versions": [
      "1.1.57",
      "1.1.61"
    ],
    "log_os": [
      "darwin"
    ],
    "hook_os": [],
    "skill_usage": {
      "invocation": true,
      "file_access": true,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "qoder-hooks",
    "name": "Qoder Hooks",
    "entry": "shared-settings",
    "os": [
      "darwin"
    ],
    "logs": "",
    "roots": [],
    "hooks": "qoder-settings",
    "block": true,
    "approval": true,
    "managed": false,
    "evidence": "documented",
    "docs": [
      "https://docs.qoder.com/cli/hooks",
      "https://docs.qoder.com/extensions/hooks"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PostToolUseFailure": "tool.failure",
      "Stop": "turn.stop"
    },
    "sample_versions": [],
    "log_os": [],
    "hook_os": [
      "darwin"
    ],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "cursor",
    "name": "Cursor",
    "entry": "ide-local-agents",
    "os": [
      "darwin",
      "linux"
    ],
    "logs": "",
    "roots": [],
    "hooks": "cursor-settings",
    "block": true,
    "approval": false,
    "evidence": "documented",
    "docs": [
      "https://cursor.com/docs/hooks"
    ],
    "hook_events": {
      "sessionStart": "session.start",
      "sessionEnd": "session.end",
      "beforeSubmitPrompt": "turn.submit",
      "preToolUse": "tool.pre",
      "postToolUse": "tool.post",
      "postToolUseFailure": "tool.failure",
      "stop": "turn.stop"
    },
    "managed": false,
    "sample_versions": [
      "3.12.30"
    ],
    "log_os": [],
    "hook_os": [
      "darwin",
      "linux"
    ],
    "skill_usage": {
      "invocation": false,
      "file_access": true,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "opencode",
    "name": "OpenCode",
    "entry": "cli",
    "os": [
      "darwin"
    ],
    "logs": "opencode-snapshot",
    "roots": [
      ".local/share/opencode/storage"
    ],
    "hooks": "",
    "block": false,
    "approval": false,
    "evidence": "local-log-sample",
    "docs": [
      "https://docs.opencode.ai/docs/plugins/"
    ],
    "hook_events": {},
    "managed": false,
    "sample_versions": [
      "1.1.51"
    ],
    "log_os": [
      "darwin"
    ],
    "hook_os": [],
    "skill_usage": {
      "invocation": true,
      "file_access": true,
      "result_source": "state.metadata.dir",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "qoder-ide",
    "name": "Qoder IDE",
    "entry": "ide",
    "os": [],
    "logs": "",
    "roots": [],
    "hooks": "",
    "block": false,
    "approval": false,
    "evidence": "documented",
    "docs": [
      "https://docs.qoder.com/qoder/hooks"
    ],
    "hook_events": {},
    "managed": false,
    "sample_versions": [],
    "log_os": [],
    "hook_os": [],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "qoder-work",
    "name": "QoderWork",
    "entry": "work",
    "os": [
      "darwin"
    ],
    "logs": "",
    "roots": [],
    "hooks": "qoderwork-settings",
    "block": true,
    "approval": false,
    "evidence": "documented",
    "docs": [
      "https://docs.qoder.com/qoderwork/hooks"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PostToolUseFailure": "tool.failure",
      "Stop": "turn.stop"
    },
    "managed": false,
    "sample_versions": [],
    "log_os": [],
    "hook_os": [
      "darwin"
    ],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "openclaw",
    "name": "OpenClaw",
    "entry": "gateway",
    "os": [],
    "logs": "",
    "roots": [],
    "hooks": "",
    "block": false,
    "approval": false,
    "evidence": "documented",
    "docs": [
      "https://docs.openclaw.ai/automation/hooks",
      "https://docs.openclaw.ai/plugins/hooks"
    ],
    "hook_events": {},
    "managed": false,
    "sample_versions": [],
    "log_os": [],
    "hook_os": [],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  },
  {
    "id": "traework",
    "name": "TraeWork",
    "entry": "work",
    "os": [],
    "logs": "",
    "roots": [],
    "hooks": "",
    "block": false,
    "approval": false,
    "evidence": "unverified",
    "docs": [
      "https://www.trae.ai/work"
    ],
    "hook_events": {},
    "managed": false,
    "sample_versions": [],
    "log_os": [],
    "hook_os": [],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    }
  }
];
