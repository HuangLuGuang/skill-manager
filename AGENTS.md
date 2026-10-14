# AGENTS.md

本文件给本地 coding agent 使用。修改本仓库时优先遵守这里的项目约定；如果用户有更具体要求，以用户要求为准。

## 项目定位

Agent Manager 是一个 AI Agent Skill 生命周期治理系统，用于对 skill 进行准入扫描、人工审核、签名验签、部署、运行时加载校验和审计。

核心目标：

- 提交 skill 后先进入后台扫描流程，不要直接信任外部 skill。
- 低风险 skill 可以自动批准并签名，高风险进入审核或拒绝。
- Agent 加载 skill 时应先调用 Agent Manager 做 registry/status/signature 校验。
- Sandbox、行为分析和 LLM 分析是辅助信号，最终风险等级由策略汇总决定。

## 目录结构

- `agent_manager/`：核心 Python 包，包含 CLI、API router、策略、扫描、签名、sandbox 等核心逻辑。
- `backend/`：后台管理 API 启动壳和账号/菜单/登录等管理台基础能力，使用 `uv` 管理依赖。
- `web/`：Vue 3 + Vite + Ant Design Vue 前端管理台。
- `services/isolated-sandbox-service/`：生产向远程 sandbox 服务。
- `services/local-sandbox-runtime/`：本地 Docker sandbox runtime 镜像。
- `demo/`：Agent 集成示例，包括 Agno、LangGraph、OpenClaw、Claude Code hook 等。
- `docs/`：项目原理、部署、sandbox、外部 Agent 集成等文档。
- `tests/`：pytest 测试和恶意/测试 skill 样例。

## 常用命令

后端 API：

```bash
uv run agent-manager-api --host 0.0.0.0 --port 8080
```

如果从 `backend/` 管理环境启动：

```bash
uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd web
npm install
npm run dev
```

前端构建需要 Node `20.19+` 或 `22.12+`。本机如果默认 Node 过低，使用：

```bash
source ~/.nvm/nvm.sh
nvm use 22.21.1
cd web
npm run build
```

测试：

```bash
uv run pytest
uv run pytest tests/test_sandbox.py -q
uv run pytest tests/test_vetting.py -q
```

Python 语法检查：

```bash
python3 -m py_compile agent_manager/core/llm.py agent_manager/core/vetting.py agent_manager/core/sandbox.py agent_manager/api/router.py
```

Docker 编排：

```bash
./.build.sh --all
docker compose up
docker compose ps
docker compose logs -f
```

构建本地 sandbox runtime 镜像：

```bash
make sandbox-runtime-build
```

## 开发约束

- Python 依赖优先使用 `uv` 管理，不要直接引入未记录的运行时依赖。
- 后台管理 API 依赖在 `backend/pyproject.toml`，核心包依赖在根目录 `pyproject.toml`。
- 前端依赖在 `web/package.json`，不要提交 `node_modules/`。
- 手动代码修改使用小范围补丁，避免重写无关文件。
- 仓库可能存在用户未提交改动；不要执行 `git reset --hard`、`git checkout -- <file>` 等破坏性命令，除非用户明确要求。
- 大改动前先看现有实现和文档，尤其是 `docs/project-guide.md`、`docs/external-agent-integration.md`、`docs/sandbox-service-architecture.md`。

## 后端注意事项

- API 路由主要在 `agent_manager/api/router.py`。
- 核心扫描流程在 `agent_manager/core/vetting.py`。
- LLM 调用封装在 `agent_manager/core/llm.py`，需要兼容 OpenAI-compatible API（DeepSeek 属于其中一种供应商）。
- 模型网关和隐私路由在 `backend/routers/llm_gateway.py`，用于管理模型供应商、模型、用户组、LLM API Key、隐私策略，并提供 OpenAI-compatible Chat Completions 代理。
- Sandbox 运行封装在 `agent_manager/core/sandbox.py`。
- 策略相关逻辑在 `agent_manager/core/policy.py`。
- 模型和 registry 数据结构在 `agent_manager/core/models.py`、`agent_manager/core/manager.py`。
- 新增 API 时要考虑登录权限、审计日志、错误信息中文可读性和前端兼容。
- 提交 skill 相关接口应保持幂等和防重复提交意识，前端禁用按钮不能替代后端校验。
- LLM API Key 明文只能在创建后展示一次，服务端只保存 hash；模型供应商 API Key 必须加密或脱敏存储，接口只能返回掩码。
- Chat Completions 代理只能透传明确允许的 OpenAI 参数；未知字段应拒绝，避免资源滥用。
- 模型网关运行时必须校验 API Key 状态、过期时间、模型范围、请求体大小和并发限制。
- Pipeline Trace 会保存原始 PII，只允许管理员或隐私审计角色查看；不要把原始 prompt/response 写入普通日志。

## 前端注意事项

- 策略页风险判定模式的总体说明放在标签旁的悬浮帮助中，按上下文判断项、判为恶意项、AI 复核分组；双语文案使用 `policySettings.modeHelp`，中文严重度沿用“中等”“高”。
- 前端使用 Vue 3 Composition API、Vite、Ant Design Vue。
- 管理平台和桌面客户端的所有新增或修改页面必须同时提供简体中文和英文。中文系统名固定为“智能体生命周期管理系统”，英文系统名固定为“Agent Manager”。
- 新增界面文案必须使用语义化 i18n Key 和语言资源，不得依赖 MutationObserver、DOM 扫描或中文原文匹配；`legacy.*` 哈希键只用于已迁移旧页面，不得手写到新页面。
- 状态、风险类型、审计事件、客户端任务和服务端错误应传递稳定编码，由界面按语言渲染；禁止在前端通过中文或英文提示文本判断业务逻辑。
- 文件内容、用户输入、Skill 原文、代码、命令输出及证据片段保持原文，不做自动翻译。
- 桌面客户端的动态文案使用 `t('ui.*')` 或 `tf`，系统通知也必须复用同一语言资源；Scanner 和 Verifier 通过独立环境变量选择语言。
- 新页面提交前必须执行中英文界面检查和 `npm run test:i18n`，确认英文长文案不会造成按钮、表格、弹窗或移动端布局溢出；后端新增错误必须提供稳定 `error_code`。
- API 封装在 `web/src/api/index.js`。
- 页面主要在 `web/src/views/`。
- Skill 列表关键词自动过滤沿用审核队列的 300 毫秒防抖交互，复用服务端分页搜索与第一页重置逻辑；立即查询及离开页面时清理待执行的关键词定时器。
- 提交 skill 页面支持四种导入方式：ZIP、本地目录、网络下载/GitHub、ClawHub。
- 对会创建后台记录的按钮必须同时做：
  - loading 状态。
  - disabled 防重复点击。
  - 函数入口的 `submitting` 防重入。
- 如果系统设置未启用或未配置直连 LLM API Key，提交页的 LLM 选项不能勾选，并要有 tooltip 说明；服务端内部任务也可以通过模型网关环境变量走隐私代理。
- 文件列表、扫描文件、报告 JSON 等内容应支持查看原始内容，避免只显示摘要。
- 文件夹上传原始大小按所属目录全部层级文件的字节数汇总；显示与计算分离，大小显示复用 `web/src/utils/fileSize.js`，字节单位走 i18n。
- 禁止 UI 单元测试，列出本次改动受影响的 UI 并给出测试 Todo list，我自行验证。

## Sandbox 约定

- Sandbox 服务地址保存与连接测试共用校验：最多 2048 字符的 HTTP/HTTPS 基础 URL，错误使用 `sandbox.url_*` 稳定编码；前端同步校验并通过 i18n 展示，超长输入保留完整内容并提示错误；仅远程模式校验该地址，保存入口仅校验本次变更的 Sandbox 配置；接口复用 `ApiError` 错误协议。后端地址常量和校验统一放在 `agent_manager/core/sandbox.py`。独立 API 入口须注册 `ApiError` 处理器，保持与后台一致的稳定错误编码和双语响应。

- 高级配置写入需按字段校验类型、范围及当前运行方式，使用稳定字段错误编码；草稿在失焦、失败与切换语言时保留，禁止通过回填默认值或夹取边界掩盖非法输入。输入字段悬浮说明和错误提供中英文；检测结果复用使用已有行下说明，文字与开关交互分离。远程凭据清除项的复选框、文字与说明图标同行展示。整数框保留原加减步长；多项失败按序号逐条显示；连接测试与保存的失败状态分别维护。前端校验复用 `web/src/utils/advancedConfig.js`，后端在 API 写入边界校验，保持旧 YAML 读取兼容；远程模式只发送网络访问开关，不使用本地 Docker 资源字段。

- Sandbox 分析器名称使用本次检测记录的 runtime，包括无脚本跳过；已有报告的展示以该次记录为准。

- Skill 详情的远程 Sandbox 服务地址按报告原因编码展示：`no_executable_script` 对应“未调用 / Not called”。

- Sandbox 的风险等级只代表运行时 probe 观察到的行为，不等同于静态扫描或 LLM 的最终风险。
- 默认 probe 可能覆盖不足；启用 LLM 时可以生成测试参数，但不要让 LLM 生成要执行的代码。
- 本地 Docker runtime 镜像建议使用 `agent-manager-sandbox-runtime:latest`，避免运行时缺少常见依赖。
- 远程 sandbox 服务的生产向实现参考 `services/isolated-sandbox-service/README.md`。
- 不要把 sandbox 当成完整攻击链复现系统；精确 syscall tracing、完整文件访问审计、进程树分析需要更底层的 runner 支持。

## Agent 集成约定

- Agent 不应该只按 skill name 加载本地目录；如果本地目录可写，应传 `skill_path` 让 Agent Manager 计算内容签名并验证。
- Name-only 校验只适合 CI/CD 管控的只读 skill 目录。
- 示例优先参考：
  - `demo/agno-skill-guard/`
  - `demo/langgraph-skill-guard/`
  - `demo/openclaw-agent-manager-hook/`
  - `demo/claude-code-hook/`

## 客户侧 Go 扫描器实施计划

- 客户本地 skills 扫描器使用 Go 实现，目标是单二进制部署，避免客户侧安装 Python、Node 或 Docker。
- Go 二进制不能硬编码 token；token 只能从 CLI 参数、环境变量或配置文件读取。
- Scanner Token 必须在管理台页面管理，创建后只展示一次明文，服务端只保存 hash，并支持禁用、吊销、过期、权限范围、允许 IP/CIDR、最大上传大小、最大并发任务数和审计。
- Scanner Token 最小权限为 `scanner:submit`、`scanner:read-own-results`、`scanner:read-own-sessions`；不要授予审批、部署、策略修改、用户管理或 token 管理权限。
- 后端新增 scanner 专用 API，不复用管理员接口。建议接口包括 `POST /api/v1/scanner/imports`、`GET /api/v1/scanner/imports/{skill_id}`，后续再增加 session 批量接口。
- Go scanner MVP 先实现 `skill-scanner scan <path>`：递归发现包含 `SKILL.md` 的目录，忽略 `.git`、`.venv`、`node_modules`、`__pycache__`、`dist`、`build`，解析基础元数据，生成 manifest 和 sha256 fingerprint，本地轻量预检，安全打 ZIP，上传到 Agent Manager，轮询结果，输出 JSON 报告。
- 本地轻量预检不执行客户代码，只检查大文件、危险扩展名、明显危险关键词等静态信号。
- 打包时禁止路径逃逸，不跟随指向 skill 目录外部的软链接，限制单文件大小、总上传大小和文件数量。
- 服务端收到 scanner 上传后要重新计算 manifest/fingerprint 并和客户端提交值对比。
- 前端新增“扫描器接入”页面，用于 Scanner Token 管理、安装命令、配置模板、最近扫描会话和风险统计。
- 建议目录结构为 `scanner/go.mod`、`scanner/cmd/skill-scanner/main.go`、`scanner/internal/config`、`scanner/internal/discovery`、`scanner/internal/manifest`、`scanner/internal/precheck`、`scanner/internal/packager`、`scanner/internal/client`、`scanner/internal/report`。
- 实施顺序：Phase 1 Go CLI MVP；Phase 2 后端 Scanner API 和 token 校验；Phase 3 前端 Scanner Token 管理；Phase 4 增量扫描、Markdown/HTML 报告、scanner 二进制下载、host/customer 分组和 CI 定时扫描。

## 文档维护

- 项目原理和使用说明优先更新 `docs/project-guide.md`。
- Agent 对接更新 `docs/external-agent-integration.md` 和 `docs/agent-signature-verification.md`。
- Sandbox 设计更新 `docs/sandbox-service-architecture.md`。
- Docker 部署更新 `docs/docker-deployment.md`。
- 如果新增 demo，补充对应 `README.md`。
- 模型网关、隐私路由、LLM API Key、Pipeline Trace 相关变更优先更新 `docs/model-gateway.md`，必要时同步 `docs/project-guide.md` 和 `docs/external-agent-integration.md`。
- 临时实施文档和计划文档用完就删除；长期开发约定记在 `AGENTS.md`，不要为了计划类内容新增 `docs/` 文档或放进 `docs/project-guide.md`。

## Git 约定

- 提交前检查 `git status --short`，确认没有误带无关文件。
- 如果 push 被拒绝，优先 `git fetch` 后 rebase 当前分支到远端分支，再解决冲突。
- 解决冲突时保留双方有效配置；示例文件中的密钥应使用占位值，不要提交真实 key。

## 35 部署与发布约定

- `10.10.71.35` 上的 GitLab Runner 名为 `35-ubuntu`，标签为 `agent-manager-release`；部署目录是 `/home/ubuntu/skill-manager`，发布产物目录是 `/home/ubuntu/releases`。
- 功能分支 push 不部署。代码合并并 push 到 `dev` 后，`deploy-35` 自动构建 x86 镜像、更新 Compose、执行健康检查并发送企业微信通知。
- 正式发布从已验证的 `dev` 提交创建版本 tag：`1.0.6`（兼容 `v1.0.6`）先更新 35，再由 `offline-package` 仅构建 x86 包；`1.0.6_arm`（兼容 `v1.0.6_arm`）由 `offline-package-arm` 仅构建 ARM 包。上传 S3 后校验下载链接并发送企业微信通知。
- 离线包使用部署文件清单组包：Compose、配置模板、Nginx 配置、目标架构镜像、Docker 安装程序、客户端发布文件、启动/升级脚本、部署文档及 provenance。源码仅用于构建镜像，仓库源码树不进入交付包。
- 打包时将包内 Compose 的应用镜像固定为发布版本。`start.sh` 加载离线镜像并启动、检查；`upgrade.sh <安装包>` 在原安装目录备份部署文件后更新并检查，保留现场 `.env` 和数据卷。部署文件备份不替代业务数据备份。
- 桌面客户端使用独立的 `client-vYY.MM.DD.N` GitHub tag 构建，`N` 为当天递增的发布序号；只有高于或等于当前版本的构建才能更新 `/home/ubuntu/releases/client-latest`，不要与平台版本 tag 混用。
- Docker Hub 基础镜像通过 35 的 Docker daemon 代理拉取；Backend 构建中的 apt、GitHub、PyPI 分别使用 `BUILD_APT_PROXY`、`BUILD_GIT_PROXY`、`BUILD_PYPI_INDEX`。PyPI 默认使用清华源，不要给 GitLab Runner 设置全局代理。
- ARM 应用镜像使用带 `_arm` 的独立版本 tag；共享的 `nginx:1.27-alpine` tag 在成功或失败退出时恢复原 x86 镜像。35 部署后检查运行镜像为 `amd64`、`docker compose ps` 全部健康，并验证 `http://127.0.0.1/`。
- 具体操作和现场离线部署分别维护在 `docs/docker-deployment.md`、`docs/offline-deployment.md`；不要在文档或 CI 中记录密码、Runner token、Webhook 完整地址或 S3 密钥。


以“当前有效要求”为成品的唯一依据。
用户的补充、撤回和修正用于更新当前有效要求；成品只表达更新后的当前状态。
- 最终代码、文档、测试、注释和提交信息只表达当前有效要求。
- 用户的修正替换旧要求，不自动形成新的否定要求。
- 被撤回、否决或由 Agent 擅自提出的概念，不得以否定说明、保护分支、fallback、配置、类型、测试或解释性注释残留在成品中。
- 只有当前业务契约、真实外部输入、信任边界、可达数据流、已知事故、回归测试或兼容性要求能够证明必要时，才加入否定约束或防御代码。
- 修改要求后，按当前有效要求正向重写受影响内容。
- 完成前检查最终 diff；任何只能由已被否决方案解释的改动都应删除。
- Sandbox 调试信息的术语及不明确取值说明复用 `SandboxDebugHelp.vue` 与 `skillDetail.sandboxHelp` 双语资源；取值及 `-` 的含义集中在字段标签或表头说明中，网络次数直接带单位显示，运行时取值按界面语言展示。Probe 参数提示根据原始报告区分空数组与字段缺失；退出码说明按本地 Docker 和远程服务分类。

- Skill 详情审计记录：事件、字段名、状态、风险及布尔值使用稳定语义翻译键；不得重复翻译已渲染文案，也不得将路径、备注等原始审计数据传给 legacy 哈希翻译函数。

- Skill 详情动态报告说明仅在英文翻译资源存在时取译文；缺少翻译保留原文及现有明确文案转换，不直接显示哈希翻译键。

- Skill 详情 LLM 失败展示复用本次报告的 analyzer_timings.llm.status 和 vetting.policy_notes；失败原因保留原文，旧报告仅在缺少状态且无成功结果时从已记录的 LLM 异常备注识别失败。

- LLM 失败原因区分平台网关前缀与上游响应：平台前缀使用语义 i18n 资源，上游响应和状态码保留原文；已保存的文本错误在展示层兼容。

- Skill 审批备注和拒绝原因上限为 1000 个 Unicode 字符（包含空格及换行），审核队列和详情入口共用前端校验，保留超长草稿并显示双语字段错误和悬浮说明；后端审批/拒绝接口写入前校验并返回稳定错误码，不修改既有记录。

- 审核文本长度统计与校验共用 Unicode 计数，输入框下方实时展示当前数量和上限；超长时显示红色错误及具体超出数量，两个审批入口保持一致。

- MCP 连接发现与保存前测试共用 `_upstream_connection_error`，HTTP 错误字段通过稳定编码和 `web/src/i18n/errors.js` 展示双语固定说明；状态码、URL 和上游原始原因保持原文。

- MCP 服务字段校验复用 `backend/mcp_validation.py` 和 `web/src/utils/mcpServerForm.js`；字段错误使用 `mcp.server.invalid_fields` 与安全的 `errors` 参数，前端语义资源为 `mcpServerForm`。现有长度与数值上限保持；鉴权值4096字符、描述2000字符。编辑先按原始草稿识别并校验变更字段，通过后再转换请求数值；鉴权留空保留原值；MCP混合校验错误仅返回位置和类型，不返回原始输入；非法草稿保留，数值沿用原有数字输入框及上下箭头，步长为1；状态无新增悬浮说明。

- MCP 服务表单的Endpoint说明和协议校验读取 `/api/v1/mcp/servers/options` 的 `allow_http`；首次用户输入后即时校验字段，刚打开的表单不显示空字段错误。协议配置未读取完成时展示读取中说明。

- MCP 审批日期范围筛选需完整显示开始和结束日期时间（含秒）；宽屏预留足够宽度，筛选栏不足时整项换行，窄屏允许输入分行。
- MCP 审批关键词、Tool 和调用凭证输入使用300毫秒防抖自动筛选；网关选择和日期范围确认或清空立即筛选，回到第一页。列表查询由首次加载、筛选、分页、手动刷新及审批操作触发；手动刷新及回车清理待执行筛选；防抖期间翻页或调整每页数量时先应用筛选并回第一页，保留所选每页数量；旧请求不得覆盖最新列表、统计或加载状态，离开页面清理定时器。

- MCP审批页所有时间展示及日期框钟面输入统一为北京时间（UTC+8），筛选申请时间created_at并包含起止边界；后端将带时区查询转换为数据库UTC时间，既有无时区查询按UTC兼容。刷新按钮加载状态只由手动刷新驱动。

- MCP网关环境和执行模式帮助复用标签旁QuestionCircleOutlined与mcpSecurity语义双语资源，按选项分行解释实际限制；保持文案与服务端调用边界一致。

- MCP调试平台网关凭证使用mcpDebug语义双语说明及字段错误；首次输入和连接前检查必填、无空白可打印ASCII字符，保留非法草稿并阻止请求，错误不包含凭证值。服务端负责凭证有效性及授权校验。

- ScannerAccess参数说明按配置项合并CLI/环境变量，展示必填条件、默认值与关系；双语资源使用scannerGuide。独立本地示例显式--server=""，分析示例包含地址/凭证配置；示例凭证明确要求替换为实际凭证，Sandbox说明包含服务端策略仍可能要求执行的关系；说明需与scanner/internal/config及runner实际行为一致。

- 深度扫描已过滤噪声明细复用后端过滤原因规则，使用 `suppressed_findings` 与稳定 `suppression_reason` 编码；界面统一展示严重度、规则、标题、文件名、独立行号和过滤原因，双语资源使用 `skillDetail.suppressed`。历史报告仅在读取响应中补齐明细，保留原存储和风险判定。

- 噪声明细的过滤原因仅翻译原因资源自身声明的编码；编码未知、为空或缺失时，统一按当前语言显示“未知 / Unknown”；兜底仅作用于过滤原因。
