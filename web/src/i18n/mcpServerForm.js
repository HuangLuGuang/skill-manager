export const mcpServerFormMessages = {
  "zh-CN": {
    "fields": {
      "name": "名称",
      "slug": "唯一标识",
      "endpoint": "Streamable HTTP Endpoint",
      "authorization_header": "鉴权 Header",
      "authorization_value": "鉴权值",
      "status": "状态",
      "timeout_seconds": "超时秒数",
      "max_response_kb": "最大响应 KB",
      "description": "描述"
    },
    "reasons": {
      "required": "不能为空",
      "length": "最多 {limit} 个字符",
      "text": "必须是文本",
      "slug": "全文只能包含小写字母、数字、下划线（_）和连字符（-）；首字符必须是小写字母或数字",
      "header": "须为合法 HTTP Header 名称",
      "value": "仅允许可打印 ASCII 字符，不允许换行",
      "status": "须为草稿、启用或停用",
      "integer": "须为 {min}–{max} 范围内的整数",
      "url": "须为有效 HTTP/HTTPS 地址，不含空白、用户名、密码或片段",
      "https": "当前配置要求使用 HTTPS",
      "address": "不允许使用该目标地址",
      "duplicate": "已存在，请使用其他标识",
      "immutable": "创建后不可修改"
    },
    "help": {
      "name": "必填，最多128个字符；保存时去除首尾空白。",
      "slug": "必填，1–128个字符；全文只能包含小写字母、数字、下划线（_）和连字符（-）；首字符必须是小写字母或数字。标识须唯一，创建后不可修改。",
      "endpointLoading": "正在读取服务端地址要求…",
      "endpoint": "必填，最多1024个字符；填写完整{protocols} MCP地址；目标须符合出站访问规则。",
      "authorization_header": "必填，最多128个字符；使用合法HTTP Header名称，如Authorization，不包含冒号、空格或换行。",
      "authorization_value": "可选，最多4096个字符（含前缀和空格），仅允许可打印ASCII字符。Bearer格式：Bearer + 空格 + Token。编辑时留空保留原值。",
      "description": "可选，最多2000个Unicode字符，包含空格和换行；原文保存。",
      "max_response_kb": "必填整数，范围1–10240 KB，默认1024 KB。",
      "timeout_seconds": "必填整数，范围1–300秒，默认30秒。"
    },
    "invalid": "请检查以下字段：",
    "editValue": "更新鉴权值（留空保持原值）"
  },
  "en-US": {
    "fields": {
      "name": "Name",
      "slug": "Identifier",
      "endpoint": "Streamable HTTP Endpoint",
      "authorization_header": "Authentication header",
      "authorization_value": "Authentication value",
      "status": "Status",
      "timeout_seconds": "Timeout (seconds)",
      "max_response_kb": "Maximum response (KB)",
      "description": "Description"
    },
    "reasons": {
      "required": "is required",
      "length": "must not exceed {limit} characters",
      "text": "must be text",
      "slug": "must contain only lowercase letters, digits, underscores (_) and hyphens (-) throughout; the first character must be a lowercase letter or digit",
      "header": "must be a valid HTTP header name",
      "value": "must contain printable ASCII characters without line breaks",
      "status": "must be Draft, Enabled or Disabled",
      "integer": "must be an integer between {min} and {max}",
      "url": "must be a valid HTTP/HTTPS URL without whitespace, user information or fragments",
      "https": "must use HTTPS under the current configuration",
      "address": "uses a prohibited destination address",
      "duplicate": "already exists; choose another identifier",
      "immutable": "cannot be changed after creation"
    },
    "help": {
      "name": "Required, up to 128 characters. Leading and trailing whitespace is removed on save.",
      "slug": "Required, 1–128 characters. Use only lowercase letters, digits, underscores (_) and hyphens (-) throughout. The first character must be a lowercase letter or digit. Must be unique and cannot be changed after creation.",
      "endpointLoading": "Loading endpoint requirements…",
      "endpoint": "Required, up to 1024 characters. Enter a full {protocols} MCP URL. Outbound access rules also apply.",
      "authorization_header": "Required, up to 128 characters. Use a valid HTTP header name, such as Authorization, without colons, spaces or line breaks.",
      "authorization_value": "Optional, up to 4096 characters including prefixes and spaces; printable ASCII only. Bearer format: Bearer + space + token. Leave blank when editing to keep the existing value.",
      "description": "Optional, up to 2000 Unicode characters including spaces and line breaks. Saved as entered.",
      "max_response_kb": "Required integer, 1–10240 KB; default 1024 KB.",
      "timeout_seconds": "Required integer, 1–300 seconds; default 30 seconds."
    },
    "invalid": "Check the following fields:",
    "editValue": "Update authentication value (leave blank to keep)"
  }
}

export const formatMcpFieldError = (issue, locale) => {
  const messages = mcpServerFormMessages[locale] || mcpServerFormMessages['zh-CN']
  const reason = messages.reasons[issue.reason] || issue.reason
  return `${messages.fields[issue.field] || issue.field}: ${reason.replace(/\{(\w+)\}/g, (_, key) => issue[key] ?? `{${key}}`)}`
}
