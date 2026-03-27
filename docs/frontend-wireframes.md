# Frontend Wireframes

本文档给出 Skill Manager 管理台的文字版页面原型。目标是让产品、设计、前端、后端在同一套信息架构上工作。

当前前端技术栈已在 [web/package.json](/Users/huangluguang/Desktop/Project/skill-manager/web/package.json) 中存在：

- Vue 3
- Vue Router
- Ant Design Vue
- Axios
- ECharts

## 1. 导航结构

建议左侧主导航：

- Dashboard
- Skills
- Review Queue
- Deployments
- Runtime
- Audit
- Policy
- Settings

顶部全局区：

- 全局搜索
- 当前环境标识
- 最近告警入口
- 用户菜单

## 2. Dashboard

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Top Bar: Search | Env Badge | Alerts | User                                     |
+----------------------+-----------------------------------------------------------+
| Sidebar              | Dashboard                                                 |
| - Dashboard          |                                                           |
| - Skills             | [Total Skills] [Review Queue] [Approved] [Deployed]       |
| - Review Queue       | [Rejected] [Retired] [Audit Events 24h]                   |
| - Deployments        |                                                           |
| - Runtime            | [Risk Distribution Chart]   [Status Distribution Chart]   |
| - Audit              |                                                           |
| - Policy             | [Pending Review Table]                                   |
| - Settings           |                                                           |
|                      | [Recent Critical Events Timeline]                        |
|                      |                                                           |
+----------------------+-----------------------------------------------------------+
```

### 模块说明

#### 2.1 KPI 卡片

字段：
- Total Skills
- Review Queue Count
- Approved Count
- Deployed Count
- Rejected Count
- Retired Count
- Audit Events in 24h

交互：
- 点击卡片跳转到对应列表页并带筛选

#### 2.2 Risk Distribution

展示：
- ECharts 饼图或柱状图

字段：
- LOW
- MEDIUM
- HIGH
- EXTREME

#### 2.3 Pending Review Table

列：
- Skill Name
- Risk Level
- Findings Summary
- Submitted At
- Source
- Author
- Action

操作：
- Review
- View Detail

#### 2.4 Recent Critical Events

列：
- Timestamp
- Event Type
- Skill Name
- Actor
- Summary

操作：
- Open Skill
- Open Audit

## 3. Skills List

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Skills                                                                           |
|----------------------------------------------------------------------------------|
| Search [________]  Status [All v] Risk [All v] Source [All v] Author [_____]    |
| Date Range [____] Sort [Submitted At v] [Asc/Desc]                               |
|----------------------------------------------------------------------------------|
| [Export] [Batch Deploy] [Batch Retire]                                           |
|----------------------------------------------------------------------------------|
| Table                                                                            |
| Name | Status | Risk | Source | Author | Allowed Tools | Submitted | Actions     |
|----------------------------------------------------------------------------------|
| ...                                                                              |
|----------------------------------------------------------------------------------|
| Pagination                                                                       |
+----------------------------------------------------------------------------------+
```

### 关键交互

- 点击 `Name` 进入详情页
- `Actions` 包含：
  - View
  - Deploy
  - Retire
  - Verify Signature
  - Audit

### 抽屉/快捷预览

可选右侧抽屉：
- 基础信息
- 最近 vetting 结果
- 最近 audit

## 4. Skill Detail

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Skill Detail: byd-stock-news                              [Approve] [Deploy]     |
| Status: APPROVED   Risk: MEDIUM                           [Retire] [Rescan]      |
|----------------------------------------------------------------------------------|
| Tabs: Overview | Vetting | Signature | Audit | Raw                              |
|----------------------------------------------------------------------------------|
| Overview Tab                                                                     |
| [Basic Info Card]           [Lifecycle Timeline]                                 |
| [Source Info Card]          [Manifest Card]                                      |
|----------------------------------------------------------------------------------|
| Vetting Tab                                                                      |
| [Risk Summary] [Findings Counts] [Analyzers Used]                                |
| [Policy Notes]                                                                   |
| [Findings Table]                                                                 |
|----------------------------------------------------------------------------------|
| Signature Tab                                                                    |
| [Signature Card] [Verify Result]                                                 |
|----------------------------------------------------------------------------------|
| Audit Tab                                                                        |
| [Related Events Table]                                                           |
|----------------------------------------------------------------------------------|
| Raw Tab                                                                          |
| [JSON Viewer]                                                                    |
+----------------------------------------------------------------------------------+
```

### Tab 设计

#### 4.1 Overview

Basic Info Card：
- Skill Name
- Skill ID
- Description
- Status
- Risk Level
- Skill Path

Source Info Card：
- Origin
- Author
- URL
- Version
- Commit SHA

Manifest Card：
- License
- Allowed Tools
- Declared Tools Valid

Lifecycle Timeline：
- Submitted
- Approved
- Deployed
- Retired
- Approved By
- Approval Note
- Reject Reason
- Retire Reason

#### 4.2 Vetting

Risk Summary：
- Max Severity
- Findings Count
- Scan Duration
- Vetted At

Findings Counts：
- Critical
- High
- Medium
- Low

Findings Table：
- Severity
- Rule ID
- Title
- File Path
- Line Number
- Analyzer
- Description
- Remediation

#### 4.3 Signature

字段：
- Signature Exists
- Signature Preview
- Last Verification Result
- Last Verification Time

按钮：
- Verify Signature
- Re-sign

#### 4.4 Audit

列：
- Timestamp
- Event Type
- Actor
- Details

#### 4.5 Raw

内容：
- 原始 skill JSON
- 原始 scan report JSON

## 5. Submit Skill

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Submit Skill                                                                     |
|----------------------------------------------------------------------------------|
| Upload ZIP [ Select File ]                                                       |
| Author [____________]                                                            |
| Origin [local v]                                                                 |
| [ ] Use Behavioral Analysis                                                      |
| [ ] Use LLM Analysis                                                             |
|----------------------------------------------------------------------------------|
| [Submit] [Reset]                                                                 |
|----------------------------------------------------------------------------------|
| Result                                                                           |
| Skill ID | Name | Status | Risk | Findings | Message                            |
| [View Detail]                                                                    |
+----------------------------------------------------------------------------------+
```

### 交互说明

- 提交按钮 loading
- 上传过程显示进度
- 返回结果后允许直接跳详情页

## 6. Review Queue

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Review Queue                                                                     |
|----------------------------------------------------------------------------------|
| Filters: Risk [All v] Author [____] Source [All v]                               |
|----------------------------------------------------------------------------------|
| Left: Queue Table                 | Right: Review Drawer / Panel                 |
|----------------------------------------------------------------------------------|
| Name | Risk | Findings | Queued   | Basic Info                                   |
| ...                               | Policy Notes                                 |
|                                   | Findings Table                               |
|                                   |----------------------------------------------|
|                                   | Approver [__________]                        |
|                                   | Note     [__________]                        |
|                                   | Reject   [__________]                        |
|                                   | [Approve] [Reject]                           |
+----------------------------------------------------------------------------------+
```

### 审核面板重点

- 风险等级必须明显
- findings 需要按 severity 分组
- 对应文件路径应可点击

## 7. Deployments

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Deployments                                                                      |
|----------------------------------------------------------------------------------|
| Tabs: Ready To Deploy | Deployed | Retired                                       |
|----------------------------------------------------------------------------------|
| Table                                                                            |
| Name | Status | Risk | Approved At | Deployed At | Signature | Actions          |
|----------------------------------------------------------------------------------|
| ...                                                                              |
+----------------------------------------------------------------------------------+
```

### 操作

- Deploy
- Retire
- Verify Signature
- View Detail

## 8. Runtime

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Runtime Governance                                                               |
|----------------------------------------------------------------------------------|
| Query Bar                                                                        |
| Skill Name [________] Skill Path [________] Agent ID [________] [Check Load]     |
| Tool Name  [________]                                            [Check Tool]    |
|----------------------------------------------------------------------------------|
| Result Cards                                                                     |
| [Can Load Result] [Check Tool Result]                                            |
|----------------------------------------------------------------------------------|
| Recent Runtime Events                                                            |
| Timestamp | Event Type | Skill | Tool | Agent | Allowed | Reason                |
+----------------------------------------------------------------------------------+
```

### 两种使用模式

#### 8.1 手动校验

输入：
- skill name
- skill path
- agent id
- tool name

输出：
- allowed / blocked
- reason
- status
- risk level

#### 8.2 事件浏览

通过 audit 展示：
- `skill_load_allowed`
- `skill_load_blocked`
- `skill_tamper_detected`
- `tool_invoked`
- `tool_blocked`

## 9. Audit

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Audit                                                                            |
|----------------------------------------------------------------------------------|
| Filters                                                                          |
| Event Type [All v] Skill [________] Actor [________] Since [24h v] [Search]      |
|----------------------------------------------------------------------------------|
| Table                                                                            |
| Time | Event Type | Skill Name | Actor | Details | Action                        |
|----------------------------------------------------------------------------------|
| Drawer: Event JSON                                                               |
+----------------------------------------------------------------------------------+
```

### 高亮规则

- `skill_tamper_detected`: red
- `skill_load_blocked`: red
- `tool_blocked`: orange
- `skill_retired`: gray/red
- `skill_deployed`: green

## 10. Policy

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Policy                                                                           |
|----------------------------------------------------------------------------------|
| Auto Approve Max Risk      [LOW v]                                               |
| Require Human Review       [HIGH, EXTREME]                                       |
| Auto Reject Risk           [EXTREME]                                             |
| Blocked Permissions        [ editable tags ]                                     |
| Trusted Authors            [ editable tags ]                                     |
| Allowed Tools Allowlist    [ editable tags ]                                     |
| Max Allowed Tools          [ 10 ]                                                |
| Require License            [ true/false ]                                        |
| Accepted Licenses          [ editable tags ]                                     |
| Scanner Policy             [balanced v]                                          |
|----------------------------------------------------------------------------------|
| [Save] [Reset] [Export YAML]                                                     |
+----------------------------------------------------------------------------------+
```

### 设计建议

- 不直接暴露 YAML 文本作为主编辑模式
- 标签输入和下拉优先
- 高风险选项改动应二次确认

## 11. Settings

### 页面结构

```text
+----------------------------------------------------------------------------------+
| Settings                                                                         |
|----------------------------------------------------------------------------------|
| API Base URL            [ http://localhost:8080 ]                                |
| Data Directory          [ ~/.skill-manager ]                                     |
| Policy Path             [ ~/.skill-manager/policy.yaml ]                         |
| Signing Key Configured  [ Yes / No ]                                             |
| Scanner Installed       [ Yes / No ]                                             |
| Hooks Installed         [ Yes / No ]                                             |
| App Version             [ 0.1.0 ]                                                |
|----------------------------------------------------------------------------------|
| [Health Check] [Test Scanner] [Reload Config]                                    |
+----------------------------------------------------------------------------------+
```

## 12. 移动端和响应式建议

管理台核心仍以桌面端优先，但需兼容平板和小屏：

- Dashboard 图表改为上下堆叠
- 表格进入小屏时转卡片
- Skill Detail 的 tabs 改成下拉切换
- Review Queue 由双栏改为单栏详情抽屉

## 13. MVP 页面优先级

第一阶段建议只做：

- Dashboard
- Skills
- Skill Detail
- Submit Skill
- Review Queue
- Audit

第二阶段再做：

- Deployments
- Runtime
- Policy
- Settings

## 14. 组件清单建议

可以先抽这些通用组件：

- `StatusTag`
- `RiskTag`
- `SkillTable`
- `AuditTable`
- `FindingsTable`
- `JsonViewer`
- `DetailDrawer`
- `MetricCard`
- `ConfirmActionModal`

这样后面页面扩展不会很散。
