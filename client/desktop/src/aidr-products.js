window.aidrProducts = [
  {
    "id": "zcode", "name": "ZCode", "entry": "desktop", "os": ["darwin"],
    "logs": "zcode-sqlite", "roots": [".zcode/cli/db"],
    "hooks": "zcode-settings", "hook_setup": {"host_authorization": false, "host_enablement": false},
    "block": true, "approval": true, "evidence": "local-source-and-log-sample",
    "docs": ["https://zcode.z.ai/en/docs/hooks"],
    "hook_events": {"SessionStart": "session.start", "UserPromptSubmit": "turn.submit", "PreToolUse": "tool.pre", "PostToolUse": "tool.post", "PostToolUseFailure": "tool.failure", "Stop": "turn.stop"},
    "managed": false, "sample_versions": ["macOS 3.16.3.8992, embedded 0.17.0"],
    "log_os": ["darwin"], "hook_os": ["darwin"],
    "skill_usage": {"invocation": true, "file_access": true, "result_source": "unverified", "new_call_e2e": "unverified"}
  },
  {
    "id": "qwenwork",
    "name": "QwenWork CN",
    "entry": "desktop",
    "os": [
      "darwin"
    ],
    "logs": "qwenwork-jsonl",
    "roots": [
      ".qwenworkcn/projects"
    ],
    "hooks": "qwenwork-settings",
    "hook_setup": {
      "host_authorization": false,
      "host_enablement": false
    },
    "block": true,
    "approval": true,
    "evidence": "local-source-and-log-sample",
    "docs": [
      "https://docs.qwenwork.cn/desktop/hooks",
      "https://docs.qwenwork.ai/zh/desktop/hooks"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "Stop": "turn.stop"
    },
    "managed": false,
    "sample_versions": [
      "CN 1.4.0 (26102705), embedded 1.1.71"
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
      "result_source": "unverified",
      "new_call_e2e": "passed_macos_1.4.0_2026-10-28"
    }
  },
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
    "hook_setup": {
      "host_authorization": false,
      "host_enablement": false
    },
    "block": true,
    "approval": true,
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
    "id": "codebuddy",
    "name": "CodeBuddy IDE",
    "entry": "ide",
    "os": [
      "darwin"
    ],
    "logs": "codebuddy-session-json",
    "roots": [
      "Library/Application Support/CodeBuddyExtension/Data"
    ],
    "hooks": "codebuddy-settings",
    "hook_setup": {
      "host_authorization": false,
      "host_enablement": false
    },
    "block": true,
    "approval": true,
    "evidence": "local-source-and-log-sample",
    "docs": [
      "https://www.codebuddy.cn/docs/ide/Features/Hooks",
      "https://www.codebuddy.cn/docs/ide/Features/Skills"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "SessionEnd": "session.end",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "PreCompact": "context.compact.start",
      "Stop": "turn.stop"
    },
    "managed": false,
    "sample_versions": [
      "4.12.2"
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
      "new_call_e2e": "passed_macos_4.12.2_2026-10-26"
    },
    "enrollment_log_source": "codebuddy"
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
    "log_entry": "qoder-cli",
    "hook_setup": {
      "host_authorization": false,
      "host_enablement": false
    },
    "block": true,
    "approval": true,
    "managed": false,
    "evidence": "documented",
    "docs": [
      "https://docs.qoder.com/cli/hooks",
      "https://docs.qoder.com/extensions/hooks",
      "https://docs.qoder.com/qoder/hooks"
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
    "collection_visible": false,
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
  },
  {
    "id": "teleagent",
    "name": "TeleAgent",
    "entry": "desktop-native",
    "os": [
      "darwin"
    ],
    "logs": "teleagent-sqlite",
    "roots": [
      ".local/share/TeleAgent/users"
    ],
    "hooks": "native-review-http",
    "block": true,
    "approval": false,
    "managed": false,
    "evidence": "local-isolated-test",
    "docs": [],
    "hook_events": {
      "BeforeToolExecute": "tool.pre",
      "AfterToolExecute": "tool.post",
      "BeforeMCPExecute": "tool.pre",
      "AfterMCPExecute": "tool.post"
    },
    "sample_versions": [
      "2.7.0"
    ],
    "log_os": [
      "darwin"
    ],
    "hook_os": [
      "darwin"
    ],
    "skill_usage": {
      "invocation": false,
      "file_access": true,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    },
    "hook_setup": {
      "host_authorization": false,
      "host_enablement": false
    },
    "enrollment_log_source": "teleagent"
  },
  {
    "id": "doubaowork",
    "name": "Doubao Work",
    "entry": "desktop",
    "os": [
      "darwin"
    ],
    "logs": "doubaowork-jsonl",
    "roots": [
      "Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.sessions",
      "Library/Application Support/DoubaoWork/Default/IndexedDB"
    ],
    "hooks": "",
    "block": false,
    "approval": false,
    "managed": false,
    "evidence": "local-log-sample",
    "docs": [],
    "hook_events": {},
    "sample_versions": [
      "2.33.1",
      "2.33.3"
    ],
    "log_os": [
      "darwin"
    ],
    "hook_os": [],
    "skill_usage": {
      "invocation": false,
      "file_access": false,
      "result_source": "unverified",
      "new_call_e2e": "unverified"
    },
    "enrollment_log_source": "doubaowork"
  },
  {
    "id": "trae",
    "name": "TRAE",
    "entry": "desktop",
    "os": [
      "darwin"
    ],
    "logs": "trae-hook-log",
    "roots": [
      "Library/Application Support/Trae/logs"
    ],
    "hooks": "trae-settings",
    "hook_setup": {
      "host_authorization": true,
      "host_enablement": true
    },
    "block": true,
    "approval": true,
    "evidence": "local-source-and-hook-sample",
    "docs": [
      "https://docs.trae.cn/ide_hook-configuration-reference"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "Stop": "turn.stop",
      "Notification": "notification"
    },
    "managed": false,
    "sample_versions": [
      "3.6.4"
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
      "result_source": "result.metadata",
      "new_call_e2e": "host-hook-and-log"
    }
  },
  {
    "id": "trae-cn",
    "name": "TRAE CN",
    "entry": "desktop",
    "os": [
      "darwin"
    ],
    "logs": "trae-hook-log",
    "roots": [
      "Library/Application Support/Trae CN/logs"
    ],
    "hooks": "trae-settings",
    "hook_setup": {
      "host_authorization": true,
      "host_enablement": true
    },
    "block": true,
    "approval": true,
    "evidence": "local-source-and-hook-sample",
    "docs": [
      "https://docs.trae.cn/ide_hook-configuration-reference"
    ],
    "hook_events": {
      "SessionStart": "session.start",
      "UserPromptSubmit": "turn.submit",
      "PreToolUse": "tool.pre",
      "PostToolUse": "tool.post",
      "Stop": "turn.stop",
      "Notification": "notification"
    },
    "managed": false,
    "sample_versions": [
      "3.3.99",
      "3.4.9"
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
      "result_source": "result.metadata",
      "new_call_e2e": "unverified"
    }
  }
];
