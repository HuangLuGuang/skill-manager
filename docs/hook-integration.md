# Hook 接入：客户端 AIDR 插件

默认通过 Agent Manager Client 的 AIDR 插件 Hook 接入宿主事件与工具策略。客户端使用随包适配器和已有设备认证，按平台策略安装插件或写入受支持产品的 Hook 配置，并由主后台服务管理接收器及事件上传。

普通自动接入无需手工复制脚本、填写桥接环境变量或另建 Agent 运行凭证。宿主原生信任、插件启用和必要授权仍需按提示完成；覆盖范围以当前客户端报告的产品、版本、入口和真实事件为准。

## 1. 连接客户端并确认设备权限

在运行目标 Agent 的电脑安装并连接客户端。管理员在客户端管理确认设备在线、允许 AIDR 上报，且设备凭证具备 `aidr:heartbeat` 和 `aidr:report-events`。在设备详情核对本机 Agent 的发现结果与客户端版本。

设备凭证用于 AIDR 策略、状态和事件传输。只有另外接入开发者 Runtime API、模型或 MCP 网关时，才按对应能力配置运行凭证与权限。

## 2. 配置 AIDR 通道和插件策略

在客户端策略中启用插件 Hook 通道、选择实际使用且已适配的产品，确认设备继承默认策略还是使用设备覆盖。Agent 日志和系统事件是独立通道，按需要配置。

- **普通自动安装**：客户端检查宿主和兼容性，在需要时安装随包插件或写入 Hook 配置；自动更新按更新策略执行。
- **显式安装**：从设备详情的“插件接入”下发安装任务，查看客户端任务回执。
- **企业受管接入**：按受管模式完成原生授权和策略应用，确认目标产品及版本支持该模式。

保存平台策略后，在设备详情核对实际应用版本、任务结果和报告时间。策略已保存、设备在线或插件已安装，分别只证明对应步骤完成。

## 3. 在宿主完成信任并创建新会话

在客户端“Agent 运行治理”和平台“插件接入”核对安装、启用、信任及接收器状态。按目标产品提示完成原生审阅或授权，例如 Codex 在原生 `/hooks` 审阅信任；随后重启宿主或新建会话，使配置生效。

Hook 接收器和日志采集运行在 `agent-manager-client run` 主后台服务内。关闭窗口、退出或重启桌面界面不会停止它们；主后台服务重启则会短暂重建接收器。运行目标仍由有效策略控制。

## 4. 用真实事件验收

| 验收项 | 操作与确认 |
|---|---|
| 接入与投递 | 在新宿主会话触发受支持的工具操作，核对客户端接收状态、平台同一设备和产品的 Hook 事件，以及事件批次 ACK。状态心跳成功不能替代事件送达证明。 |
| 仅审计 | 确认事件到达、会话和工具证据可查看。仅审计模式不执行策略阻断。 |
| 工具拦截 | 对提供相应执行前控制点的产品，在拦截模式发布测试规则，分别核对允许、拒绝，以及需要时的人工审批结果与实际工具行为。 |
| 状态缺失 | 检查产品兼容性、原生信任、新会话、有效策略版本及报告时间；从“插件接入”发起重新检查。 |
| 上传中断 | 核对设备上报许可、凭证、队列、重试原因和最近事件 ACK；恢复后确认待发事件已实际到达。 |

Hook、Agent 日志和系统采集分别验收。插件安装或一次事件到达不证明全部工具路径可拦截。

## 5. 需要 Skill 加载前验签时

AIDR Hook 根据工具策略做运行决策；Skill 使用审计由后台内容观察与平台状态核对形成异步结论。要求在加载前验证 Skill 内容与授权时，进入[开发者：加载前验签](developer-skill-verification.md)，在真实 Loader 或受支持的宿主事件接入同步校验。手工脚本、环境变量、运行凭证和宿主配置示例集中在该指南。

## English: default Client AIDR Hook integration

Use Agent Manager Client to integrate host events and tool policies. Bundled adapters install native plugins or configure supported Hooks, using existing device authentication. Ordinary automatic setup does not require copied scripts, bridge environment variables or a separate Agent runtime credential. Native trust, enablement and authorization remain host-specific steps.

1. **Connect the device.** Install the Client on the Agent host. Confirm the device is online, AIDR reporting is allowed, and its credential has `aidr:heartbeat` and `aidr:report-events`.
2. **Configure policy.** Enable the plugin Hook channel and select supported products. Confirm inherited policy or device overrides. Ordinary automatic mode installs compatible integration components as needed; explicit installation uses a device task. Managed mode requires its native authorization and supported product/version. Logs and system collection are separate channels.
3. **Trust and activate.** Check installation, enablement, trust, task receipts and the applied policy version. Complete the host’s native review, such as Codex `/hooks`, then restart the host or start a new session.
4. **Verify actual behavior.** Trigger a supported tool event and correlate the device/product event, local receiver state and event-batch ACK. Audit-only mode records events. For interception, verify allow, deny and any approval flow at supported pre-execution points. Installation or a status heartbeat alone does not establish event delivery or full tool coverage.
5. **Check failures by channel.** Inspect compatibility, trust, report age, current policy, upload permission, queues and retries. Confirm queued events reach the platform after recovery.

The Hook receiver and log collector run inside the main `agent-manager-client run` background service. Closing or restarting the desktop UI leaves them running; restarting the background service briefly recreates the receiver. Effective policy controls their runtime targets.

For synchronous Skill content and authorization checks, use [Developer: pre-load verification](developer-skill-verification.md). Integrate at the real Loader or a supported host event with an Agent runtime credential. AIDR tool policies and asynchronous usage audit do not provide that load-time guarantee. Model and MCP gateway integration also has its own credentials and acceptance steps.

## 相关指南 / Related guides

- [客户端操作与产品覆盖 / Client operations and coverage](agent-manager-client.md)
- [开发者：加载前验签 / Developer: pre-load verification](developer-skill-verification.md)
- [内容签名与接口 / Content signatures and APIs](agent-signature-verification.md)
- [外部 Agent 接入 / External Agent integration](external-agent-integration.md)
