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

- 前端使用 Vue 3 Composition API、Vite、Ant Design Vue。
- 管理平台和桌面客户端的所有新增或修改页面必须同时提供简体中文和英文。中文系统名固定为“智能体生命周期管理系统”，英文系统名固定为“Agent Manager”。
- 新增界面文案必须使用语义化 i18n Key 和语言资源，不得依赖 MutationObserver、DOM 扫描或中文原文匹配；`legacy.*` 哈希键只用于已迁移旧页面，不得手写到新页面。
- 状态、风险类型、审计事件、客户端任务和服务端错误应传递稳定编码，由界面按语言渲染；禁止在前端通过中文或英文提示文本判断业务逻辑。
- 文件内容、用户输入、Skill 原文、代码、命令输出及证据片段保持原文，不做自动翻译。
- 桌面客户端的动态文案使用 `t('ui.*')` 或 `tf`，系统通知也必须复用同一语言资源；Scanner 和 Verifier 通过独立环境变量选择语言。
- 新页面提交前必须执行中英文界面检查和 `npm run test:i18n`，确认英文长文案不会造成按钮、表格、弹窗或移动端布局溢出；后端新增错误必须提供稳定 `error_code`。
- API 封装在 `web/src/api/index.js`。
- 页面主要在 `web/src/views/`。
- 提交 skill 页面支持四种导入方式：ZIP、本地目录、网络下载/GitHub、ClawHub。
- 对会创建后台记录的按钮必须同时做：
  - loading 状态。
  - disabled 防重复点击。
  - 函数入口的 `submitting` 防重入。
- 如果系统设置未启用或未配置直连 LLM API Key，提交页的 LLM 选项不能勾选，并要有 tooltip 说明；服务端内部任务也可以通过模型网关环境变量走隐私代理。
- 文件列表、扫描文件、报告 JSON 等内容应支持查看原始内容，避免只显示摘要。

## Sandbox 约定

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
- 正式发布必须从已验证的 `dev` 提交创建 `v数字.数字.数字` tag。tag 流水线先更新 35，再由 `offline-package` 自动构建 x86/ARM 离线包并上传 S3。
- 桌面客户端使用独立的 `client-vYY.MM.DD.N` GitHub tag 构建，`N` 为当天递增的发布序号；只有高于或等于当前版本的构建才能更新 `/home/ubuntu/releases/client-latest`，不要与平台版本 tag 混用。
- Docker Hub 基础镜像通过 35 的 Docker daemon 代理拉取；Backend 构建中的 apt、GitHub、PyPI 分别使用 `BUILD_APT_PROXY`、`BUILD_GIT_PROXY`、`BUILD_PYPI_INDEX`。PyPI 默认使用清华源，不要给 GitLab Runner 设置全局代理。
- ARM 构建会临时覆盖同名镜像 tag，离线任务必须在成功或失败退出时恢复 x86 tag。发布后检查所有运行镜像为 `amd64`、`docker compose ps` 全部健康，并验证 `http://127.0.0.1/`。
- 具体操作和现场离线部署分别维护在 `docs/docker-deployment.md`、`docs/offline-deployment.md`；不要在文档或 CI 中记录密码、Runner token、Webhook 完整地址或 S3 密钥。
