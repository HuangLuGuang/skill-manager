# Frontend API Checklist

本文档用于前后端对齐 Skill Manager 管理台的接口设计。内容分为两部分：

- 已有接口：当前后端已实现，可直接接前端
- 建议补充接口：为了支撑完整前端管理台，建议后端新增

当前已实现的核心 API 来自 [skill_manager/api/router.py](/Users/huangluguang/Desktop/Project/skill-manager/skill_manager/api/router.py)。

## 1. API Base

- Base URL: `/api/v1`
- Content-Type:
  - `application/json`
  - `multipart/form-data` for ZIP upload

## 2. 已有接口

### 2.1 Health

#### `GET /api/v1/health`

用途：
- 系统健康检查

示例响应：

```json
{
  "status": "ok",
  "service": "skill-manager"
}
```

前端页面：
- Settings
- 全局启动检查

### 2.2 Skill 提交

#### `POST /api/v1/skills/submit-zip`

用途：
- 上传 skill ZIP 并触发 vetting

请求参数：
- Query
  - `author?: string`
  - `origin?: "local" | "github" | "clawhub" | "internal" | "unknown"`
  - `use_behavioral?: boolean`
  - `use_llm?: boolean`
- FormData
  - `file: UploadFile`

示例响应：

```json
{
  "skill_id": "uuid",
  "name": "byd-stock-news",
  "status": "APPROVED",
  "risk_level": "LOW",
  "findings_count": 0,
  "message": "Auto-approved. Call /deploy to activate."
}
```

前端页面：
- Submit Skill

注意：
- 当前后端只支持 ZIP 提交，不支持直接传目录路径

### 2.3 Skill 列表

#### `GET /api/v1/skills`

用途：
- 获取 skill 列表

请求参数：
- `status?: PENDING | VETTED | APPROVED | DEPLOYED | REJECTED | RETIRED`

示例响应：

```json
[
  {
    "skill_id": "uuid",
    "name": "byd-stock-news",
    "status": "APPROVED",
    "risk_level": "MEDIUM",
    "approved_by": "auto-policy",
    "submitted_at": "2026-03-25T08:12:00+00:00",
    "approved_at": "2026-03-25T08:12:01+00:00",
    "deployed_at": null
  }
]
```

前端页面：
- Dashboard
- Skills List

现有限制：
- 只支持按 `status` 过滤
- 不支持分页、搜索、排序、作者筛选、风险筛选

### 2.4 Skill 详情

#### `GET /api/v1/skills/{skill_id_or_name}`

用途：
- 获取单个 skill 详情

路径参数：
- `skill_id_or_name`

示例响应字段：
- `skill_id`
- `name`
- `description`
- `source`
- `skill_path`
- `status`
- `risk_level`
- `vetting`
- `allowed_tools`
- `declared_tools_valid`
- `signature`
- `submitted_at`
- `approved_at`
- `deployed_at`
- `retired_at`
- `approved_by`
- `approval_note`
- `rejection_reason`
- `retire_reason`

前端页面：
- Skill Detail

注意：
- 当前接口排除了 `vetting.scan_report`，前端拿不到完整原始扫描报告

### 2.5 Review Queue

#### `GET /api/v1/review`

用途：
- 获取待人工审核的 skill 队列

示例响应：

```json
[
  {
    "skill_id": "uuid",
    "skill_name": "risk-skill",
    "risk_level": "HIGH",
    "findings_summary": {
      "critical": 0,
      "high": 1,
      "medium": 2,
      "low": 0
    },
    "submitted_at": "2026-03-25T08:00:00+00:00",
    "queued_at": "2026-03-25T08:01:00+00:00",
    "notes": "..."
  }
]
```

前端页面：
- Review Queue

### 2.6 Approve Skill

#### `POST /api/v1/skills/{skill_id}/approve`

用途：
- 批准待审核 skill

请求体：

```json
{
  "approver": "alice",
  "note": "Reviewed and approved"
}
```

示例响应：

```json
{
  "skill_id": "uuid",
  "status": "APPROVED",
  "message": "Approved"
}
```

前端页面：
- Review Queue
- Skill Detail

### 2.7 Reject Skill

#### `POST /api/v1/skills/{skill_id}/reject`

用途：
- 拒绝待审核 skill

请求体：

```json
{
  "reviewer": "alice",
  "reason": "Undeclared dangerous behavior"
}
```

示例响应：

```json
{
  "skill_id": "uuid",
  "status": "REJECTED",
  "message": "Rejected"
}
```

前端页面：
- Review Queue
- Skill Detail

### 2.8 Deploy Skill

#### `POST /api/v1/skills/{skill_id}/deploy`

用途：
- 将 APPROVED skill 标记为 DEPLOYED

示例响应：

```json
{
  "skill_id": "uuid",
  "status": "DEPLOYED",
  "message": "Deployed"
}
```

前端页面：
- Deployments
- Skill Detail

### 2.9 Retire Skill

#### `POST /api/v1/skills/{skill_id}/retire`

用途：
- 退役 skill，立即撤销可加载状态

请求体：

```json
{
  "reason": "CVE-2026-0001",
  "actor": "security-team"
}
```

示例响应：

```json
{
  "skill_id": "uuid",
  "status": "RETIRED",
  "message": "Retired"
}
```

前端页面：
- Skill Detail
- Deployments

### 2.10 Runtime Can Load

#### `GET /api/v1/runtime/can-load/{skill_name}`

用途：
- 查询 skill 是否允许被 agent 加载

请求参数：
- `skill_path?: string`
- `agent_id?: string`

示例响应：

```json
{
  "allowed": true,
  "reason": "allowed",
  "status": "DEPLOYED",
  "risk_level": "LOW"
}
```

前端页面：
- Runtime
- Skill Detail

### 2.11 Runtime Check Tool

#### `GET /api/v1/runtime/check-tool`

用途：
- 查询 skill 是否允许调用某个 tool

请求参数：
- `skill_name: string`
- `tool_name: string`
- `agent_id?: string`

示例响应：

```json
{
  "allowed": true,
  "skill_name": "file-reader",
  "tool_name": "Read"
}
```

前端页面：
- Runtime

### 2.12 Audit

#### `GET /api/v1/audit`

用途：
- 获取审计日志

请求参数：
- `since_hours?: float` default `24.0`
- `skill_id?: string`
- `limit?: int` default `100`

示例响应：

```json
[
  {
    "event_id": "uuid",
    "event_type": "skill_deployed",
    "skill_id": "uuid",
    "skill_name": "byd-stock-news",
    "timestamp": "2026-03-25T09:00:00+00:00",
    "actor": "alice",
    "details": {}
  }
]
```

前端页面：
- Dashboard
- Audit
- Skill Detail

现有限制：
- 不支持按 event_type、actor、分页筛选

## 3. 页面到现有接口映射

### Dashboard

可用接口：
- `GET /api/v1/skills`
- `GET /api/v1/review`
- `GET /api/v1/audit`

前端需要自行聚合：
- 状态数量
- 风险分布
- 最近事件

### Skills List

可用接口：
- `GET /api/v1/skills`

缺口：
- 搜索
- 分页
- 多条件过滤

### Skill Detail

可用接口：
- `GET /api/v1/skills/{skill_id_or_name}`
- `POST /api/v1/skills/{skill_id}/approve`
- `POST /api/v1/skills/{skill_id}/reject`
- `POST /api/v1/skills/{skill_id}/deploy`
- `POST /api/v1/skills/{skill_id}/retire`
- `GET /api/v1/audit?skill_id=...`

### Review Queue

可用接口：
- `GET /api/v1/review`
- `POST /api/v1/skills/{skill_id}/approve`
- `POST /api/v1/skills/{skill_id}/reject`

### Deployments

可用接口：
- `GET /api/v1/skills?status=APPROVED`
- `GET /api/v1/skills?status=DEPLOYED`
- `POST /api/v1/skills/{skill_id}/deploy`
- `POST /api/v1/skills/{skill_id}/retire`

### Runtime

可用接口：
- `GET /api/v1/runtime/can-load/{skill_name}`
- `GET /api/v1/runtime/check-tool`
- `GET /api/v1/audit`

缺口：
- 当前没有“运行时最近检查记录”的专门聚合接口
- 只能从 audit 中提取

## 4. 建议补充接口

这些接口不是当前必需，但做管理台会明显更顺。

### 4.1 Dashboard Summary

#### `GET /api/v1/dashboard/summary`

建议返回：

```json
{
  "total_skills": 12,
  "status_counts": {
    "VETTED": 2,
    "APPROVED": 3,
    "DEPLOYED": 4,
    "REJECTED": 1,
    "RETIRED": 2
  },
  "risk_counts": {
    "LOW": 5,
    "MEDIUM": 4,
    "HIGH": 2,
    "EXTREME": 1
  },
  "review_queue_count": 2,
  "recent_audit_count": 28
}
```

### 4.2 Skill Search

#### `GET /api/v1/skills/search`

建议支持：
- `q`
- `status`
- `risk_level`
- `origin`
- `author`
- `page`
- `page_size`
- `sort_by`
- `sort_order`

### 4.3 Full Scan Report

#### `GET /api/v1/skills/{skill_id}/scan-report`

用途：
- 返回完整 `vetting.scan_report`

### 4.4 Re-Scan Skill

#### `POST /api/v1/skills/{skill_id}/rescan`

请求体建议：

```json
{
  "use_behavioral": true,
  "use_llm": false
}
```

### 4.5 Verify Signature

#### `POST /api/v1/skills/{skill_id}/verify-signature`

请求体建议：

```json
{
  "skill_path": "/path/to/skill"
}
```

响应建议：

```json
{
  "verified": true,
  "reason": "signature matches"
}
```

### 4.6 Policy Read/Write

#### `GET /api/v1/policy`
#### `PUT /api/v1/policy`

用途：
- 前端读取和保存公司 policy

### 4.7 Audit Advanced Search

#### `GET /api/v1/audit/search`

建议支持：
- `event_type`
- `actor`
- `skill_id`
- `since_hours`
- `page`
- `page_size`

### 4.8 Runtime Events Summary

#### `GET /api/v1/runtime/events`

用途：
- 返回最近的 `skill_load_*` 和 `tool_*` 事件，便于 Runtime 页面直接消费

## 5. 前端数据模型建议

### SkillListItem

```ts
type SkillListItem = {
  skill_id: string;
  name: string;
  status: string;
  risk_level: string | null;
  approved_by: string | null;
  submitted_at: string;
  approved_at: string | null;
  deployed_at: string | null;
};
```

### SkillDetail

```ts
type SkillDetail = {
  skill_id: string;
  name: string;
  description: string;
  source: {
    origin: string;
    author?: string | null;
    url?: string | null;
    version?: string | null;
    commit_sha?: string | null;
  };
  skill_path?: string | null;
  status: string;
  risk_level?: string | null;
  allowed_tools: string[];
  declared_tools_valid: boolean;
  signature?: string | null;
  submitted_at: string;
  approved_at?: string | null;
  deployed_at?: string | null;
  retired_at?: string | null;
  approved_by?: string | null;
  approval_note?: string | null;
  rejection_reason?: string | null;
  retire_reason?: string | null;
  vetting?: {
    max_severity: string;
    findings_count: number;
    critical_count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
    analyzers_used: string[];
    scan_duration_seconds: number;
    vetted_at: string;
    policy_notes: string[];
  } | null;
};
```

### AuditEvent

```ts
type AuditEvent = {
  event_id: string;
  event_type: string;
  skill_id: string;
  skill_name: string;
  timestamp: string;
  actor?: string | null;
  details: Record<string, unknown>;
};
```

## 6. MVP 接口优先级

第一阶段前端只做管理台 MVP，后端至少需要这些：

- `GET /api/v1/health`
- `POST /api/v1/skills/submit-zip`
- `GET /api/v1/skills`
- `GET /api/v1/skills/{skill_id_or_name}`
- `GET /api/v1/review`
- `POST /api/v1/skills/{skill_id}/approve`
- `POST /api/v1/skills/{skill_id}/reject`
- `POST /api/v1/skills/{skill_id}/deploy`
- `POST /api/v1/skills/{skill_id}/retire`
- `GET /api/v1/audit`

第二阶段再补：

- Dashboard summary
- Full scan report
- Rescan
- Verify signature
- Policy read/write
- Advanced audit search
