# AIDR P1 上传

客户正常流程由平台客户端策略指定日志目标，现有Go用户后台自动管理读取与上传。下面的`aidr-sync`命令仅用于开发/受控诊断，不是桌面客户安装步骤；三通道实机状态及未验项见客户端长期说明和既有验收记录。

## 系统队列的有界补传

`DrainRuntime`在摄入停止后上传既有系统记录，保持写锁和目的绑定，每批沿用原冻结正文/摘要。只有设备、协议、durable、数量与digest全部匹配的ACK才能删除该批。调用者提供时间预算和1～1024次请求上限；暂时失败按1秒起、30秒封顶退避，明确认证拒绝不重试。预算结束保留积压，后续恢复可在同一状态目录继续；不创建监视器或读取控制命令。返回排空确认、可用的待发数量、尝试/成功批次与预算状态。超时无法获得新计数时保持null。共享上传健康保存`aidr_upload_ack_invalid`，返回值保留原系统ACK错误码。

**English:** Runtime drain operates on existing durable records with bounded attempts and a caller deadline. It never starts collection or fetches control commands. Frozen retries, exact ACK matching and device/platform isolation are preserved across restart. Shutdown drain is integrated; the privileged automatic OFF/recovery supervisor remains pending.

`agent-manager-client aidr-sync` 显式启动日志读取、持久化、批量上传和心跳；退出即停止，不安装系统服务。默认读取当前用户的 Claude projects 与 Codex sessions。此命令不会建立日志调用与 OS 进程之间的强归属，事件的 `process_relation` 保持 `unknown`。

## 接入

1. 管理台设备详情的“Agent 日志观察”点击“允许上报”。
2. 创建 client 类型凭证，绑定该设备，只授予 `aidr:heartbeat`、`aidr:report-events`。明文仅创建时展示一次，服务端保存 hash。
3. 在进程环境中设置 `AGENT_MANAGER_AIDR_TOKEN`，运行：

```sh
agent-manager-client aidr-sync \
  --state-dir /absolute/private/aidr-state \
  --server https://manager.example.com \
  --client-id DEVICE_ID
```

凭证不接受命令行明文参数。`--token-env` 可指定其他变量名。`--claude-root`、`--codex-root` 覆盖日志根；`--claude-file`、`--codex-file` 可将验收范围限制在相应根内的一个日志。`--since` 指定初次回溯起点，默认 24 小时；已有游标沿用持久化范围。`--duration 180s` 用于有界验证。退出时输出健康统计；持续消费不依赖 stdout 或页面定时器。

## 传输与隔离

- HTTPS 为默认要求，只有 loopback 接受 HTTP。拒绝重定向；单请求超时 10 秒，回执最大 64 KiB。
- 默认每 2 秒进行有界消费/上传。每个来源最多 4 MiB / 500 个事件 / 1 秒，每轮摄入总时间预算 2 秒，轮换来源防止饥饿。每轮最多上传 4 批，每批最多 500 条 / 1 MiB。
- 默认 30 秒发现来源和发送心跳；每种 Agent 最多 64 个来源、10,000 个目录项及 1 秒发现预算。缺口通过覆盖和原因码显式记录。
- 网络、429、5xx 与无效 ACK 保留同一冻结批次重试；指数退避 1–60 秒。401/403 等永久错误停止本次运行，保留本地待发队列。
- ACK 必须匹配 schema=2、设备、stream、batch、digest、记录数和 durable 标志后才能推进上传游标。服务端事务提交后才返回 durable ACK。
- `stream_id` 在状态目录中持久化，跨重启稳定。状态目录绑定平台和设备；凭证轮换不改变绑定，不能把同一份待发数据改投其他设备或平台。
- 管理查询同时要求现有设备可见性及角色权限；super_admin 沿用全局管理权限。设备正文不能覆盖认证归属。设备暂停上报拒绝新事件批次，仍允许有效设备凭证获取审计策略及报告心跳/接收器状态；吊销、过期或权限不足继续拒绝对应接口。

## 容量与健康

沿用 [localstore](../localstore/README.md) 配额。容量不足暂停摄入并保留游标，仍尝试上传已持久化队列及心跳；`aidr_store_capacity` 可见。上传错误使用 `aidr_upload_*` 编码。历史正文淘汰单独计数，不表示采集缺口；待上传正文不会被保留期限清理。

平台暂停上传只通过 HTTP 403 的稳定 `aidr.reporting_disabled` 识别为可恢复的 `aidr_upload_reporting_paused`，不能按提示文本或任意403放宽鉴权。日志和Hook上传都保持冻结正文及严格ACK，退避为1/2/4/8/16/32/60秒封顶，实际工作者周期可能延后尝试。本地摄入、策略刷新及心跳独立继续；认证拒绝停止工作者且保留队列。Hook接收器状态报告可选携带 `upload_code`、`next_upload_at` 和 `last_event_ack_at`；后者仅在本地严格匹配批次ACK的同一事务中持久保存，不等同于状态报告成功。旧报告缺少这些字段时保持未知。

**English:** A device reporting pause rejects new event batches, while valid device authentication still permits policy retrieval and heartbeat/runtime status. Only the exact machine code `aidr.reporting_disabled` on HTTP 403 selects retryable reporting pause; other credential rejections stop upload without discarding the queue. Intake remains independent and immutable batches retry with capped backoff. The optional last event ACK timestamp survives restart and is distinct from successful status reports. Missing telemetry from older clients remains unknown.

平台心跳统计为最后一次快照，离线期间不能当作实时计数。平台接收白名单元数据、摘要及按采集策略处理的有界行为字段，再次校验结构、长度、服务端下发记录及开启策略下的秘密模式；完整 Prompt、文件正文、工具结果及未知参数不透传。当前实机认证版本见验收记录，其他版本上报 `unverified`，不宣称完整支持。

## 升级已有状态

先升级平台，再停止旧版 `aidr-sync` 并升级客户端，使用相同 `--server`、`--client-id` 和 `--state-dir` 启动。启动迁移保留平台数据，旧本地绑定通过认证设备的历史映射自动核对。冻结正文仍为 schema=1，ACK 为 schema=2；正文、摘要、幂等键、stream 和读取游标保持不变。重复上传仍只保留一份逻辑事件。

出现 `aidr_upload_destination_changed` 时检查平台 URL 和设备 ID；出现 `aidr_upload_destination_migration_unavailable` 时核对平台是否已完成迁移及是否具有该设备的历史映射。保留原状态目录和队列，修正连接或恢复相应平台备份后再运行。不要通过新建目录或删除数据库跳过待发数据。旧客户端的 v1 ACK 校验与新版回执不兼容，应配套升级；它会保留未确认队列。


### P1 补强：平台统一 AIDR 审计脱敏

入口：**系统管理 → 系统总览 → AIDR 审计脱敏**（英文 System Overview → AIDR audit redaction）。管理员且具有 `settings:update` 权限可修改，默认开启；修改人、时间、前后开关与版本进入管理审计，不记录命令内容。设备详情同时展示平台目标策略、客户端报告的版本/开关及最后刷新时间；没有支持报告的旧客户端显示未知/旧版本继续脱敏，不宣称已应用关闭状态。

`aidr-sync` 启动后先读取缓存并尝试认证获取策略，以后每 30 秒重试，下一轮有界采集生效。网络往返及当前采集轮次会增加延迟，这不是硬实时 SLA。离线/获取失败使用已持久化缓存，首次失败默认开启（版本 0）；状态码为 `aidr_policy_applied`、`aidr_policy_cached`、`aidr_policy_response_invalid`。本地 `agent-log-collect` 使用同一状态目录的缓存，无平台连接时不主动刷新。

关闭仅关闭允许字段的敏感值替换，命令里的真实凭证可能进入本地数据库及后台；白名单、UTF-8 字节上限、截断、控制字符处理和正文排除不变。完整 Prompt、独立文件正文、完整结果、未知参数不采集。明确的内联正文/脚本参数及 heredoc 仍省略，标记 `body_omitted`，不冒充凭证脱敏。普通 `git commit -m "fix scanner ownership across client credential rotation" && git status --short --branch` 在两种策略下均完整保留。明确 `--password`、秘密环境变量赋值、Authorization/Bearer、Cookie 和受支持令牌格式在开启时遮蔽其值，保持引号与操作符。

升级不删除或重建本地数据。平台新增策略下发记录表；本地 metadata 增加策略缓存及应用序列边界。事件 `behavior.policy` 保存 `version/enabled/receipt`，`redacted` 表示发生替换，`body_omitted` 单独说明正文排除。服务端以绑定设备/stream 的真实下发记录授权，开启策略再次检查敏感模式，未下发版本或错误设备/序列拒绝（`aidr.redaction_policy_invalid`）。客户端持久化应用新策略后，在下次刷新确认上报旧数据序列上界；只有确认后才关闭旧策略范围，响应丢失仍可重试。冻结批次不修改、不重算摘要；旧队列按采集策略补传，即使当前目标已开启，合法 OFF 积压仍可接收。离线采集时间无法由服务端独立证明，策略依赖认证客户端正确报告应用边界，不提供终端可信执行证明。

切换只影响后续新逻辑事件，不恢复、重采或清洗历史。版本 1/2 事件、既有内容哈希、覆盖游标及 ACK 契约保留；重读通过既有身份复用原始投影并保留新位置的来源证据；已淘汰正文的墓碑保持淘汰，避免恢复历史或重复逻辑事件。旧客户端继续固定脱敏，需升级才支持开关。版本 3 不支持向旧平台降级上报，部署顺序为先平台后采集端。
