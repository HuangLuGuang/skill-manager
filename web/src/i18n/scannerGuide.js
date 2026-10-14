export const scannerGuideMessages = {
  "zh-CN": {
    "title": "参数怎么用",
    "summary": "本地扫描只需路径；上传还需平台地址和 Scanner 凭证。",
    "priority": "地址和凭证可分别通过命令行或环境变量提供，也可混用；同时设置时，命令行优先。设置平台地址即启用上传，仅配置凭证不会上传。",
    "columns": {
      "name": "配置项",
      "required": "何时需要",
      "value": "填写方式 / 默认值",
      "usage": "作用及关系"
    },
    "groups": {
      "connection": {
        "title": "基础与上传配置",
        "help": "平台地址和凭证是上传所需的两项配置，不是两套必须同时填写的参数。"
      },
      "analysis": {
        "title": "服务端分析",
        "help": "仅上传时生效；四个分析开关默认关闭，可独立组合，需服务端对应能力可用。"
      },
      "limits": {
        "title": "本地处理限制",
        "help": "每个 Skill 单独计算，与是否上传无关。超限的 Skill 不上传，其他 Skill 可继续。大小单位按 1024 × 1024 字节计算；默认值不是固定最大可填值。建议正整数；当前实现中，0 或负数关闭对应本地限制。上传仍受服务端及凭证配额约束。"
      }
    },
    "examples": {
      "local": "仅本地发现、预检和打包，不上传（覆盖已有平台地址环境变量）",
      "upload": "上传到平台",
      "all": "上传并启用全部分析",
      "cliTab": "命令行上传",
      "cli": "命令行上传，覆盖对应环境变量",
      "rules": "规则分析",
      "deep": "静态深度扫描",
      "sandbox": "Sandbox 分析",
      "llm": "LLM 分析",
      "combined": "组合分析"
    },
    "rows": {
      "path": {
        "name": "扫描路径",
        "required": "必填",
        "value": "本机可读目录，如 /opt/openclaw/skills；含空格时加引号。",
        "usage": "可填单个 Skill 或多个 Skill 的根目录；递归发现 SKILL.md，一次只支持一个路径。"
      },
      "server": {
        "name": "平台地址",
        "required": "上传时必需",
        "value": "任选一种；默认未配置。例：https://agent-manager.example.com",
        "usage": "命令行优先；有地址即上传。填写扫描机器可访问的平台基础地址，不是 API 路径；127.0.0.1 指扫描机器自身。"
      },
      "token": {
        "name": "Scanner 凭证",
        "required": "上传时必需",
        "value": "任选一种；默认未配置。amat_xxx 仅为示例，请替换为实际凭证。",
        "usage": "命令行优先；凭证中心生成的 Scanner 凭证，包含 scanner:submit。只填 Token，不加 Bearer 前缀。"
      },
      "upload": {
        "name": "显式上传",
        "required": "可选，通常省略",
        "value": "默认关闭；只写开关。",
        "usage": "仍需地址和凭证；缺地址会报错。已有地址时自动上传，--upload=false 也不能抵消；仅本地扫描用 --server=\"\"。"
      },
      "output": {
        "name": "本地报告",
        "required": "可选",
        "value": "默认 skill-scan-report.json；例：--output report.json",
        "usage": "相对路径以命令当前目录为基准，目录需可写。报告含预检和提交信息；上传成功才有 skill_id，不会等待全部后台分析完成。"
      },
      "host": {
        "name": "来源标识",
        "required": "可选",
        "value": "任选一种；默认未填写。例：customer-prod-01",
        "usage": "命令行优先；随上传提交以区分主机/环境，不切换平台、凭证或扫描对象。"
      },
      "timeout": {
        "name": "请求超时",
        "required": "可选，仅上传时生效",
        "value": "默认 120s；例：--timeout 2m。建议正时长。",
        "usage": "限制上传 HTTP 请求时长，不是服务端整个扫描任务的耗时上限。"
      },
      "behavioral": {
        "name": "规则分析",
        "required": "按需，上传时生效",
        "value": "默认关闭；只写开关。",
        "usage": "请求服务端规则/行为分析，不在客户机执行 Skill 脚本。"
      },
      "deep": {
        "name": "静态深度扫描",
        "required": "按需，上传时生效",
        "value": "默认关闭；只写开关。",
        "usage": "不自动启用 LLM；与 --llm 组合时，证据交给最终 LLM 汇总。"
      },
      "sandbox": {
        "name": "Sandbox 分析",
        "required": "按需，上传时生效",
        "value": "默认关闭；只写开关。",
        "usage": "--sandbox 仅请求分析；还需在服务端启用 Sandbox 运行检测并完成可用配置，才会执行。未传此开关时，服务端策略仍可能要求执行。"
      },
      "llm": {
        "name": "LLM 分析",
        "required": "按需，上传时生效",
        "value": "默认关闭；只写开关。",
        "usage": "--llm 仅请求分析；还需在服务端启用 AI 分析并配置模型和凭据，才会调用模型。服务端未启用时显示“未启用”；不自动启用其他分析开关。"
      },
      "judgement": {
        "name": "风险判定模式",
        "required": "可选，上传时生效",
        "value": "strict（严格）、balanced（平衡）、permissive（宽松）。",
        "usage": "命令行优先；未配置沿用服务端策略。不依赖 --llm。"
      },
      "file": {
        "name": "单文件大小",
        "required": "可选",
        "value": "默认 20；例：--max-file-mb 20",
        "usage": "纳入打包的单文件大小上限。"
      },
      "total": {
        "name": "单个 Skill 总大小",
        "required": "可选",
        "value": "默认 50；例：--max-total-mb 50",
        "usage": "纳入打包的原始文件大小总和，不是 ZIP 压缩后大小。"
      },
      "files": {
        "name": "单个 Skill 文件数",
        "required": "可选",
        "value": "默认 2000；例：--max-files 2000",
        "usage": "纳入打包的文件数量上限。"
      },
      "ignore": {
        "name": "忽略名称",
        "required": "可选",
        "value": "默认 .git,.venv,node_modules,__pycache__,dist,build",
        "usage": "逗号分隔名称，不是路径或通配符；自定义值替换默认列表，需保留的默认项一起填写。跳过同名目录，打包时也跳过同名文件。"
      }
    }
  },
  "en-US": {
    "title": "How to use parameters",
    "summary": "Local scanning needs a path. Uploading also needs a platform URL and Scanner credential.",
    "priority": "Choose a source for each URL and credential; sources can be mixed. CLI options override matching environment variables. A platform URL enables upload; a credential alone does not.",
    "columns": {
      "name": "Configuration",
      "required": "When needed",
      "value": "Input / default",
      "usage": "Purpose and relationships"
    },
    "groups": {
      "connection": {
        "title": "Basic and upload configuration",
        "help": "The URL and credential are two required upload settings, not two sets of parameters you must fill in."
      },
      "analysis": {
        "title": "Server-side analysis",
        "help": "Applies only to uploads. The four analysis switches default to off and can be combined independently. Corresponding server capabilities must be available."
      },
      "limits": {
        "title": "Local processing limits",
        "help": "Applied per Skill, with or without upload. A Skill exceeding a limit is not uploaded; others can continue. Size units are 1024 × 1024 bytes. Defaults are not fixed maximum inputs. Use positive integers; the current implementation disables the corresponding local limit for zero or negative values. Server and credential quotas still apply to uploads."
      }
    },
    "examples": {
      "local": "Local discovery, precheck and packaging only (override any platform URL environment variable)",
      "upload": "Upload to the platform",
      "all": "Upload with all analysis options",
      "cliTab": "CLI upload",
      "cli": "CLI upload, overriding matching environment variables",
      "rules": "Rule analysis",
      "deep": "Static deep analysis",
      "sandbox": "Sandbox analysis",
      "llm": "LLM analysis",
      "combined": "Combined analysis"
    },
    "rows": {
      "path": {
        "name": "Scan path",
        "required": "Required",
        "value": "Readable local directory, e.g. /opt/openclaw/skills. Quote paths containing spaces.",
        "usage": "A single Skill or a root containing multiple Skills. Recursively discovers SKILL.md; one path per command."
      },
      "server": {
        "name": "Platform URL",
        "required": "Required for upload",
        "value": "Either source; unset by default. Example: https://agent-manager.example.com",
        "usage": "CLI takes priority. A URL enables upload. Use a platform base URL reachable from the scanner, not an API path; 127.0.0.1 refers to the scanner machine."
      },
      "token": {
        "name": "Scanner credential",
        "required": "Required for upload",
        "value": "Either source; unset by default. Replace the example amat_xxx with your actual credential.",
        "usage": "CLI takes priority. Use a Scanner credential from Credential Center with scanner:submit. Enter the token without a Bearer prefix."
      },
      "upload": {
        "name": "Explicit upload",
        "required": "Optional; usually omitted",
        "value": "Off by default; no value needed.",
        "usage": "Still needs a URL and credential; a missing URL causes an error. A configured URL enables upload even with --upload=false. For local-only scans, use --server=\"\"."
      },
      "output": {
        "name": "Local report",
        "required": "Optional",
        "value": "Default: skill-scan-report.json. Example: --output report.json",
        "usage": "Relative to the working directory; the destination must be writable. Contains precheck and submission data, with skill_id after successful submission. Does not wait for all background analysis."
      },
      "host": {
        "name": "Source identifier",
        "required": "Optional",
        "value": "Either source; unset by default. Example: customer-prod-01",
        "usage": "CLI takes priority. Identifies the upload source; does not switch platforms, credentials or scan targets."
      },
      "timeout": {
        "name": "Request timeout",
        "required": "Optional; uploads only",
        "value": "Default: 120s. Example: --timeout 2m. Use a positive duration.",
        "usage": "Limits the upload HTTP request, not the entire server-side scan task."
      },
      "behavioral": {
        "name": "Rule analysis",
        "required": "As needed; uploads only",
        "value": "Off by default; no value needed.",
        "usage": "Requests server-side rule/behavioral analysis; does not execute Skill scripts on the client."
      },
      "deep": {
        "name": "Static deep scan",
        "required": "As needed; uploads only",
        "value": "Off by default; no value needed.",
        "usage": "Does not enable LLM automatically. With --llm, evidence is included in final LLM reconciliation."
      },
      "sandbox": {
        "name": "Sandbox analysis",
        "required": "As needed; uploads only",
        "value": "Off by default; no value needed.",
        "usage": "--sandbox only requests analysis. Sandbox runtime detection must also be enabled and configured on the server before execution. Server policy may still require execution when this switch is omitted."
      },
      "llm": {
        "name": "LLM analysis",
        "required": "As needed; uploads only",
        "value": "Off by default; no value needed.",
        "usage": "--llm only requests analysis. AI analysis must also be enabled on the server with a model and credentials configured before a model is called. When disabled on the server, the result is Disabled. Does not enable other analysis switches."
      },
      "judgement": {
        "name": "Risk judgement mode",
        "required": "Optional; uploads only",
        "value": "strict, balanced or permissive.",
        "usage": "CLI takes priority; the server policy applies when unset. Does not require --llm."
      },
      "file": {
        "name": "Individual file size",
        "required": "Optional",
        "value": "Default: 20. Example: --max-file-mb 20",
        "usage": "Maximum size of an individual packaged file."
      },
      "total": {
        "name": "Total Skill size",
        "required": "Optional",
        "value": "Default: 50. Example: --max-total-mb 50",
        "usage": "Sum of original packaged file sizes, not the compressed ZIP size."
      },
      "files": {
        "name": "Files per Skill",
        "required": "Optional",
        "value": "Default: 2000. Example: --max-files 2000",
        "usage": "Maximum number of packaged files per Skill."
      },
      "ignore": {
        "name": "Ignored names",
        "required": "Optional",
        "value": "Default: .git,.venv,node_modules,__pycache__,dist,build",
        "usage": "Comma-separated names, not paths or globs. Replaces the default list; include defaults you want to keep. Skips matching directories and, during packaging, matching files."
      }
    }
  }
}
