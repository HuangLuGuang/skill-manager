# 离线 License / Offline License

智能体生命周期管理系统（Agent Manager）使用厂商 Ed25519 签名的离线 License。
签发工具位于独立的 `license-issuer` 仓库；客户平台只持有验签公钥，无需联网验证。

管理台帮助中心在 **部署与运维 → License 申请、签发与续期** 提供中英文操作指南，
地址为 `/docs/license-authorization`，Docker 部署和系统管理帮助页也提供入口。
指南按客户部署人员、客户管理员和厂商签发人员分别说明操作位置、步骤及验收结果。

管理台顶部每 60 秒刷新授权状态，仅根据服务端成功返回的限制状态显示提示。
请求失败时保留上次已确认状态；首次读取失败时不显示顶部授权提示，后续轮询继续重试。
后续成功读取到有效授权时清除提示。后端独立执行授权限制。

The console refreshes its License banner every 60 seconds and shows a warning only when
a successful server response reports a restricted state. Failed requests preserve the last
confirmed state; an initial failure leaves the banner hidden while polling continues.
A subsequent valid response clears the warning. The backend enforces licensing independently.

## 新客户与续期交付

- 新客户先在实际交付服务器部署并登录，再导出该部署的申请。厂商分配客户编号并核对客户身份，
  确认安装镜像或受管公钥目录信任签发系统的公钥。客户平台不需要连接厂商签发系统。
- 厂商登录 `license-issuer`，在新建授权页导入申请 JSON，设置日期、完整模块和注册客户端额度，
  点击“核对并签发”后下载 `.license` 交付客户；签发记录不等同于客户已经导入。
- 签发页面的日期表示北京时间 00:00，结束时刻不包含在有效期内；例如覆盖 10 月 31 日全天时，
  结束日期应为 11 月 1 日。导入后核对“有效”状态、客户与部署身份、日期、模块、额度和修订号，
  再按已授权模块执行新增、扫描和网关或防护业务验收。
- 续期、增购或调整额度时，在签发系统找到原部署记录，选择“续期 / 调整”，签发更高修订号。
  新文件包含全部权益，应保留仍需使用的模块；未来续期的起始时间应与原到期时间衔接。
  客户可提前导入并核对待生效记录，到生效时间自动切换。
- License 签发私钥、AIDR 策略签名密钥和 Skill 签名密钥用途不同；初始化防护或 Skill 签名密钥
  不会自动获得商业授权。客户全新安装或使用空卷生成了新部署标识时，需要重新申请。

## 管理员操作

1. 在 **系统管理 → License 授权** 打开 `/license`。新部署生成并持久化唯一部署标识。
2. 输入厂商分配的客户编号和客户名称，导出 `customer-request.json`，交给厂商签发工作站。
3. 厂商设置起止日期、模块和客户端额度，交付 `.license` 文件。
4. 选择文件并点击“验证并导入”。服务端验证受信任公钥、签名、产品、结构、部署和客户绑定、有效期及修订号。
5. 页面显示当前授权、待生效续期、已注册数量、模块和导入记录。界面支持简体中文和英文，客户输入保持原文。

授权管理页需要 `license:view`，导出申请与导入需要 `license:update`，系统管理员默认具备。
所有已登录用户可获取授权状态，用于全局状态提示；业务数据和导出仍遵守原有角色权限。
申请文件中的身份是厂商需要核对的声明，并非身份认证证明。

## 有效期、修订与额度

- 时间统一按 UTC 存储、北京时间 UTC+8 显示，满足 `not_before <= now < expires_at`。
- 同一文件再次导入幂等；同一修订内容不同或低于已接收修订的新文件拒绝。失败导入不替换既有授权。
- 导入失败原因保留在文件操作区，按稳定错误码显示中英文说明；切换语言保留所选文件及错误，重新选择文件或再次导入时清除上一条错误。
- 未来生效的授权保留为待生效修订；运行时根据时间选择已生效的最高修订，支持多 Worker 和重启后的自动切换。
- 续期或调整文件表示完整权益集合。新的生效修订移除某模块时，该模块运行授权随之更新；“到期继续运行”适用于有效签名内的既有模块。
- 额度按 `managed_clients` 中已注册客户端计数，包括离线客户端。同一 ID 重连不重复计数。
- 注册在同一数据库写事务中检查数量并创建记录，并发请求不能争抢最后一个名额。额度降低到已有数量以下时保留已有客户端，停止新注册。
- 历史导入记录保存修订、签名文件、时间和操作员；导出申请和导入的管理操作沿用管理审计。

## 执行边界

| 操作 | 有效且包含对应模块 | 到期后 |
| --- | --- | --- |
| 查看记录、报告和原有导出 | 按原角色权限 | 保留 |
| 新增 Skill/Prompt、扫描、重扫 | 允许 | 拒绝 |
| 新增客户端、智能体、网关、供应商、模型、凭证 | 允许 | 拒绝 |
| 既有模型与 MCP 网关请求 | 允许 | 保留 |
| 既有 Skill 运行验签、Hook、AIDR 防护 | 允许 | 保留 |
| 客户端重连、心跳、库存及审计上报 | 保留 | 保留；发现信息不自动创建新的治理身份 |
| 既有防护策略下发、运行审批、隐私策略更新 | 允许 | 保留 |
| 排队扫描与定时扫描派发 | 允许 | 停止领取和派发，续期后重新检查 |
| 已运行安全扫描 | 允许 | Worker 心跳返回停止，MCP 扫描调用及评估模型调用入口拒绝继续执行 |
| 账号安全、License 导入、系统管理维护 | 按原角色权限 | 保留 |

稳定模块编码为 `skill_governance`、`security_scanning`、`aidr`、`mcp_gateway`、`model_gateway`。
Skill 准入同时检查治理和扫描模块；运行校验使用治理模块，不因到期停止。
核心扫描函数也检查授权，独立 API 入口复用限制。前端状态提示不能替代后端判定。

已运行本地 Skill 分析在分析器开始边界重新检查。已经发出的同步调用可能先结束；
Worker 扫描通过现有心跳及取消机制停止，而不是在到期瞬间强杀进程。
客户自行运行、不与平台交互的独立本地扫描二进制不受服务端拦截控制。

## 部署、可信公钥与备份

- 默认状态路径为 `${DATA_DIR}/license/state.db`；无 DATA_DIR 时使用项目 `data/license/state.db`。
  可用 `AGENT_MANAGER_LICENSE_STATE_PATH` 指定绝对路径。同一部署的 API/任务进程必须共用同一状态文件。
- Docker 后端使用已有持久化 data 卷保存授权身份与记录，镜像包含 `deploy/license/public-keys/` 中的可信公钥。
- 内置 `5fa1304ab4aa7ed0.pem` 对应本次建立的签发工作站；上线前核对厂商实际使用的密钥。
  可用 `AGENT_MANAGER_LICENSE_KEYS_DIR` 指向运维配置的只读公钥目录。
- 客户管理页不能上传或替换可信公钥，License 文件也不携带可自行信任的公钥。
- 不将私钥、License 状态库、客户签发文件放入源码、镜像或通用离线安装包。
- 备份/恢复时一并保存业务数据库和 License 状态目录。不要删除授权状态以重置额度或修订。
  全新安装生成不同部署标识，需要重新申请授权；复制完整安装目录不会创造独立授权身份。
- 没有 License 的新安装可登录、导出申请、导入、查看及导出已有数据；新增和扫描必须先获得授权。
  既有系统升级也需要先准备绑定本部署的授权，升级本身不自动产生商业授权。

### Docker 运行与迁移

默认 Compose 的 `backend_data` 卷挂载到 `/app/runtime/data`，因此授权身份、导入记录及时间高水位
实际位于 `/app/runtime/data/license/state.db`。后端镜像内的可信公钥目录为
`/app/deploy/license/public-keys`。容器重启或使用同一个卷重建容器后，会继续读取原授权。
签发工作站无需运行在客户 Docker 网络中，导入和运行校验不访问签发服务。

首次启动空卷会生成新的部署标识：本机源码运行环境签发的 License 不能直接导入这个新部署。
新部署应在容器启动后导出申请并重新签发；若是迁移同一个部署，应在停写后同时迁移业务数据库
和完整 `license` 状态目录，再启动并核对部署标识、客户、修订号、模块及额度。
仅复制 `.license` 文件不会迁移部署身份。

普通 `docker compose down` 保留命名卷；`docker compose down -v` 会删除这些卷。
改变 Compose 项目名也可能使用另一套空卷，部署或升级时须保持项目名与卷映射一致。
如果设置 `AGENT_MANAGER_LICENSE_STATE_PATH` 或 `AGENT_MANAGER_LICENSE_KEYS_DIR`，填入容器内路径，
并分别配置可写的持久化状态挂载和只读的公钥挂载。公钥轮换后须更新镜像或所挂载的公钥目录。

服务器记录已观察到的最大时间。回拨超过 5 分钟时限制新增和扫描，保留按已观察时间选出的既有运行权益；
时间校准后自动恢复。5 分钟以内按最大已观察时间判定，不能借小幅回拨延长到期时间。
完全离线且客户拥有宿主机控制权时，恢复旧磁盘快照、修改代码或克隆部署无法仅靠软件彻底阻止；
当前实现不声称具备可信硬件时钟或不可回滚存储。

## API

- `GET /api/v1/license/status`：当前、待生效和历史授权、部署标识及客户端使用量。
- `POST /api/v1/license/request`：JSON `customer_id`、`customer_name`；返回申请 JSON 下载。
- `POST /api/v1/license/import`：请求体直接传入原始 `.license` JSON，最大 64 KiB。
- 错误使用 `license.*` 稳定编码及中英文消息；签名失败、部署不匹配、回滚和额度耗尽可明确区分。

格式与厂商签发工具一致：`am-license-v1.<key_id>.<payload>` 是 Ed25519 签名输入，
payload 使用未填充 base64url 编码的规范 UTF-8 JSON。公钥 ID 为原始公钥 SHA-256 的前 16 位十六进制。

## 人工验收 Todo

受影响 UI：新增 License 页、全局授权状态提示、系统管理菜单、角色权限中的授权模块、扫描停止原因；语言切换保留 License 页草稿。
未新增 UI 单元测试。

- [ ] 中英文检查空状态、有效、过期、待生效、超额及服务错误，桌面和手机宽度均可操作。
- [ ] 导出申请，使用独立签发工具签发，再导入真实部署；公钥与部署标识一致。
- [ ] 签名篡改、错误部署、重复文件、低修订和同修订冲突，确认原授权不变。
- [ ] 未来续期导入后当前授权继续有效，生效边界自动切换；重启后保持。
- [ ] 额度最后一个名额并发注册；离线仍计数、重连不重复计数、降低额度后既有连接保留。
- [ ] 到期后手动、Scanner、定时和排队扫描均停止，Worker 收到停止指令。
- [ ] 到期前后实际模型请求、MCP 工具调用、Hook 审批、AIDR 策略续发和审计上报连续可用。
- [ ] 只读角色不能导入；无权限账号不能通过直接 API 修改授权；已有报告导出不受影响。
- [ ] 全套离线包升级/恢复，在目标宿主机验证持久卷、时间和可信公钥配置。

## English operator summary

The bilingual Help Center guide is under **Deploy and operate → License requests, issuance and renewal**
at `/docs/license-authorization`, with links from Docker deployment and System management.
For a new customer, export the request from the actual delivered deployment and have the vendor verify
customer identity and signing-key trust. The vendor imports the JSON into license-issuer, reviews the full
entitlement and delivers the signed file. Issuer dates mean 00:00 Beijing time, with the end instant excluded.
To renew, select Renew / adjust on the existing deployment record and issue a higher revision containing
all required modules and capacity. Align the new start with the previous expiry and verify pending renewals.
License, AIDR policy and Skill signing keys have separate purposes; configuring runtime signing does not grant a License.

Open **System Management → License**, export a customer request and send it to the separate vendor issuer.
Import the returned signed file. The deployment identity persists locally; the private signing key remains with the vendor.
Future renewals do not replace the active entitlement prematurely. Failed imports preserve the previous license.
Registered clients, including offline clients, consume seats; reconnecting the same ID does not consume another seat.
Expiry stops additions and scans while preserving viewing, exports, existing gateways, runtime verification and protection.
License checks run on the server and execution boundaries. Running scans stop cooperatively at worker heartbeat/analyzer boundaries.
Preserve the license state alongside business backups, and provision trusted public keys independently of imported files.
Docker stores license state in `/app/runtime/data/license/state.db` on the `backend_data` volume and bundles
trusted public keys in `/app/deploy/license/public-keys`. Reuse the volume when recreating containers.
A fresh volume creates a new deployment identity and needs a newly issued license. To migrate the same deployment,
stop writes and move both business databases and the complete license state directory. Container-side path overrides
must have corresponding persistent mounts; removing volumes or changing the Compose project can create a fresh identity.
Offline software cannot fully resist host-controlled snapshot rollback or cloned installations.
