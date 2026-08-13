# Agent Manager Client 使用说明

Agent Manager Client 用于统一发现、接管和巡检本机 Agent 的 Skill 目录。它直接管控文件入口，不依赖 Agent 是否遵循提示词、Skill 指令或 Hook。

客户端支持两种治理方式：

- 客户端安全治理（默认）：Skill 已在平台批准且本地内容签名一致即可使用，不要求创建或绑定平台智能体。
- Agent 强授权：除批准状态和签名外，还要求本机 Agent 绑定平台智能体，并校验该智能体的 Skill 允许范围。

客户端当前内置支持以下 Agent：

- Claude Code
- Codex
- Gemini CLI
- OpenCode
- OpenClaw
- Hermes
- TRAE CN
- TRAE
- Cursor
- CodeBuddy
- WorkBuddy

客户端还识别可由 OpenCode、Cursor 等读取的共用 `.agents/skills` 目录，并在界面中单独标明共享边界。以上 Agent 和目录支持 Skill 发现、接管、安装和巡检。其他工具可在桌面端点击“添加自定义 Agent”，填写名称并选择或输入 Skill 根目录；自定义 Agent 会复用同一套治理流程。

## 模块化治理的边界

客户端的治理单元是“本机 Agent 类型 + 实际 Skill 根目录 + 具体 Skill + 可选的平台
Agent 绑定”，而不是把整台主机视为一个不可拆分的可信单元：

- 一个本机 Agent 可以配置一个或多个实际 Skill 根目录；客户端会解析符号链接，避免同一
  物理目录仅因路径别名被重复识别。
- Agent 强授权模式下，每个支持 Skill 管理的本机 Agent 分别绑定平台 Agent，并按该
  Agent 的 Skill 允许范围过滤安装和巡检结论。
- 修改、修复、移除和隔离以具体 Skill 安装记录为目标。执行后仍应核对目标 Agent、路径、
  版本、任务状态和事件，不能只依赖按钮提示。
- 共用 `.agents/skills` 目录单独显示可能的读取者，但目录本身不能证明实际调用者身份，
  因此不承担 Agent 强授权绑定。
- 正式启用自动恢复或隔离阻断前，先使用只审计模式验证根目录、共享边界和事件归属。

帮助中心“场景实践 → 客户端模块化治理”提供一台 Codex 与 Claude Code 共存工作站的
完整演练和下载清单。

## 客户端设置

右上角“设置”集中管理当前设备的偏好：

- 显示语言：简体中文或英文。
- 默认打开页面：客户端读取状态后优先进入的页面。
- 系统通知：控制是否把安全事件和新版本发送到操作系统通知中心；本地通知记录不受影响。
- 最低提醒级别：低于所选级别的事件只保留在客户端通知中心。
- 登录后启动后台治理：安装或移除当前用户级后台服务。
- 自动检查更新：控制接入平台后的静默更新检查。
- 更新通道：正式通道或测试通道；测试通道尚未发布版本时按“已是最新版”处理。
- 诊断：打开日志目录、打开数据目录，或导出不包含凭证明文和 Skill 内容的诊断报告。

客户端不提供通知提示音设置。

客户端内部语言与 macOS Finder 中的应用名称相互独立。Finder 会按照 macOS
系统首选语言读取安装包内的 `InfoPlist.strings`：中文显示“智能体生命周期管理系统客户端”，
英文显示“Agent Manager Client”。切换客户端内部语言不会立即重命名 Finder 中的应用。
各语言共用同一安装包，不需要重复打包。

## 1. 构建

桌面版（推荐）：

```bash
cd client/desktop
npm install
npm run build
```

macOS 安装包输出到 `client/desktop/src-tauri/target/release/bundle/macos/`。CI 会按 macOS、Windows、Linux 分别生成桌面安装包。

只构建后台单二进制：

```bash
cd scanner
./scripts/package.sh v0.1.0
```

输出文件位于 `scanner/releases/`：

```text
agent-manager-client-darwin-arm64
agent-manager-client-darwin-amd64
agent-manager-client-linux-amd64
agent-manager-client-linux-arm64
```

## 2. 创建客户端凭证

管理台进入：

```text
智能体管理 -> 统一凭证中心 -> 创建凭证
```

凭证类型选择“客户端接入凭证”。明文只展示一次。

## 3. 注册客户端

```bash
export AGENT_MANAGER_CLIENT_SERVER="http://127.0.0.1"
export AGENT_MANAGER_CLIENT_TOKEN="amat_xxx"

./agent-manager-client-darwin-arm64 register
```

客户端自动发现本机 Agent 和用户级 Skill，并上报平台。管理台进入：

```text
智能体管理 -> 客户端管理
```

默认使用“客户端安全治理”，无需绑定平台智能体。只有切换为“Agent 强授权”后，才需要在客户端详情中选择平台智能体；同类型只有一个候选时平台会自动匹配。

不在内置列表中的 Agent，无需开发新适配器。进入“Agent 发现 -> 添加自定义 Agent”，填写便于识别的名称，并选择包含多个 Skill 子目录的绝对路径。移除自定义 Agent 只取消登记，不会删除该目录中的文件。客户端安全治理无需在平台重复创建 Agent；Agent 强授权模式下，先在平台创建“自定义 Agent”，再在客户端选择对应的平台智能体。

## 4. 首次接管

先预览，不修改文件：

```bash
./agent-manager-client-darwin-arm64 takeover \
  --skill /Users/example/.codex/skills/code-review
```

确认预览后执行：

```bash
./agent-manager-client-darwin-arm64 takeover \
  --skill /Users/example/.codex/skills/code-review \
  --confirm
```

Agent 强授权模式再增加 `--agent codex=codex-agent`。桌面版会提供平台智能体下拉和 Skill 勾选，无需手写参数。

接管规则：

- 客户端安全治理：Skill 为 `APPROVED` 且签名一致时进入 `~/.river-security/agent-manager/skills/`。
- Agent 强授权：还必须通过智能体允许范围校验。
- 其他 Skill：备份后移入 `~/.river-security/agent-manager/pending/`。
- 用户在选择性接管中明确未勾选的路径保留原状，并记为当前治理范围外；接管完成后新出现的未知 Skill 仍会按策略检测。
- 原始内容备份到 `~/.river-security/agent-manager/backups/`。
- 接管失败时恢复原目录。
- 已接管的 Skill 在刷新预览时显示“已接管”，不会再次复制、备份或替换。

`~/.agent-manager/` 只保存配置、数据库、日志、锁和运行触发文件。升级时，客户端会把旧版 `skills`、`pending`、`quarantine`、`backups` 内容迁入 `~/.river-security/agent-manager/`，并保留旧路径兼容入口，现有 Agent 软链接无需重新接管。

## 5. 启动后台巡检

执行一次心跳、任务和完整性检查：

```bash
./agent-manager-client-darwin-arm64 run-once
```

持续运行：

```bash
./agent-manager-client-darwin-arm64 run --interval 30s
```

本地状态保存在：

```text
~/.agent-manager/client.db
```

客户端详情可设置：

- 只审计：发现修改后只记录事件。
- 自动恢复：重新下载平台批准版本。
- 隔离阻断：把异常内容移入 `~/.river-security/agent-manager/quarantine/` 并移除 Agent 入口。

平台不可达时，客户端不会执行安装、远程修复或授权变更，但会使用最近一次成功同步的策略继续检查已受管 Skill。只审计模式记录本地事件，隔离阻断模式会隔离确认被修改的内容；事件持久保存在本地并在平台恢复后自动补报。首次成功同步前没有策略缓存时，客户端不会自行处置。

桌面端可以“暂停持续治理”。暂停后保留当前 Skill、软链接和安装关系，不再巡检、告警、隔离或自动修复；后台服务仍继续同步平台安装、移除和修复任务。命令行对应：

```bash
./agent-manager-client-darwin-arm64 pause-governance
./agent-manager-client-darwin-arm64 resume-governance
```

## 6. 平台安装和卸载

在“客户端管理”中：

1. 打开客户端详情。
2. 点击目标 Agent 的“安装 Skill”。
3. 选择 `APPROVED` Skill。

Agent 强授权模式下，需要先绑定平台智能体，列表只显示该智能体允许使用的 Skill。

客户端轮询任务后，会验证 Ed25519 发布签名和逐文件 SHA-256。签名或文件哈希不一致时拒绝安装。

## 7. 备份恢复

桌面客户端在“运行状态”中可以查看和恢复首次接管产生的备份。命令行也可以操作：

```bash
./agent-manager-client-darwin-arm64 backups
./agent-manager-client-darwin-arm64 restore --backup 20260716T120000Z --confirm
```

恢复前会再次备份当前同名 Skill。备份目录只接受 `~/.river-security/agent-manager/backups/` 下的真实目录；升级后的客户端仍可读取旧版 `~/.agent-manager/backups/`。备份不跟随外部软链接，内置和自定义 Agent 均按当前登记的 Skill 根目录恢复。

被阻断的内容进入独立隔离区，不会在未经验证时直接放回 Agent 目录。桌面版应从平台选择批准版本重新安装；命令行可以只读查看隔离记录：

```bash
./agent-manager-client-darwin-arm64 quarantine
```

## 8. 后台服务

桌面版“启用后台服务”会安装当前用户级后台服务：macOS 使用 LaunchAgent，Linux 使用 systemd user service，Windows 使用登录计划任务。界面显示的是服务真实运行状态，不只检查配置文件是否存在。停止后台服务会同时停止平台任务同步；仅需停止巡检时应使用“暂停持续治理”。

```bash
./agent-manager-client-darwin-arm64 install-service
./agent-manager-client-darwin-arm64 service-status
./agent-manager-client-darwin-arm64 uninstall-service
```

后台定时任务使用轻量巡检，并按策略周期执行完整文件校验；桌面端“立即执行巡检”和命令行 `run-once` 会强制执行一次完整文件校验。

桌面客户端启动时只校准后台服务状态：服务未运行或后台二进制 SHA256 已变化时才会重启。因服务恢复或二进制升级而发生的重启会请求一次完整巡检；后台服务正常且二进制未变化时不会重启，也不会中断正在执行的巡检。`reconcile-service --force-restart` 仅用于明确的人工修复，不属于日常桌面启动流程。

## 9. 客户端自动更新

正式桌面安装包提供“检查更新”。客户端使用本地客户端凭证访问 Agent Manager，并由 Tauri Updater 校验 Ed25519 更新签名；无签名、签名错误或平台不匹配的更新包不会安装。确认更新后，界面会显示下载进度，安装前暂停后台服务，安装完成后自动重启桌面客户端；新版本启动时会校准并恢复后台服务。若下载或安装失败，客户端会恢复原后台服务并显示失败原因。正式通道读取 `latest.json`，测试通道读取 `preview.json`；未发布测试清单时服务端返回 `204 No Content`，客户端不会将其显示为连接错误。

管理台“安装客户端”会先签发仅对所选安装包有效的短时下载票据，再交给浏览器原生下载；实际进度可在浏览器下载列表中查看。票据保存在 HttpOnly Cookie 中，不会把登录凭证或下载票据暴露在 URL；浏览器可以使用原生 Range 分段下载和续传。Tauri 自动更新使用独立的签名更新端点。

生成更新签名密钥：

```bash
cd client/desktop
npx tauri signer generate -w ~/.tauri/agent-manager-client.key
```

在 GitHub 仓库“Settings → Secrets and variables → Actions”中配置以下 Repository secrets：

```text
AGENT_MANAGER_UPDATER_PUBLIC_KEY
AGENT_MANAGER_UPDATER_PRIVATE_KEY
AGENT_MANAGER_UPDATER_PRIVATE_KEY_PASSWORD
```

macOS 构建支持两种模式。仓库未配置变量时默认为 `adhoc`，用于内部测试；Tauri 会对完整 App Bundle 执行 ad-hoc 签名，流水线上仍会执行严格签名校验。浏览器下载的测试包首次运行时需要在 Finder 中右键应用并选择“打开”，或由测试人员自行移除该文件的 quarantine 属性，不能作为正式客户发行版。

正式发行时，在 GitHub 仓库的 Repository variables 中设置：

```text
AGENT_MANAGER_MACOS_SIGNING_MODE=developer-id
```

同时使用 Apple Developer Program 账号申请 `Developer ID Application` 证书，并配置以下 Repository secrets：

```text
APPLE_CERTIFICATE
APPLE_CERTIFICATE_PASSWORD
APPLE_ID
APPLE_PASSWORD
APPLE_TEAM_ID
```

`APPLE_CERTIFICATE` 是包含私钥的 `.p12` 证书经 `openssl base64 -A` 编码后的完整内容；`APPLE_CERTIFICATE_PASSWORD` 是导出 `.p12` 时设置的密码；`APPLE_PASSWORD` 必须使用 Apple ID 的 App 专用密码。Updater 的 Ed25519 密钥与 Apple 代码签名是两套独立机制，正式发行时缺少任意一套都不能形成可交付的 macOS 自动更新版本。

如果 Actions 报错 `SecKeychainItemImport` 或 `failed to import keychain certificate`，优先检查 `APPLE_CERTIFICATE` 是否误填成 `.cer`、文件路径或文件名，以及 `APPLE_CERTIFICATE_PASSWORD` 是否与 `.p12` 的导出密码一致。正式流水线会在构建前验证 Base64、`.p12` 密码、Developer ID Application 证书类型和私钥是否存在。

版本使用 `YY.MM.DD.N`，最后一段是当天发布序号，从 `1` 开始递增。例如 2026 年 3 月 15 日第一次和第二次发布：

```bash
git tag client-v26.03.15.1
git push github client-v26.03.15.1

git tag client-v26.03.15.2
git push github client-v26.03.15.2
```

客户端界面、安装包文件名和发布目录保留四段显示版本。构建脚本会将其转换成 Tauri 使用的三段内部版本，例如 `26.03.15.2` 转换为 `26.3.1502`，用于可靠比较同日多次发布。序号允许 `1`–`99`；不要使用 SemVer 构建元数据 `+N`，因为它不参与版本新旧比较。

推送 `client-v*` 标签后，[GitHub Actions 工作流](../.github/workflows/agent-manager-client.yml) 会使用 GitHub 托管的 macOS ARM、macOS Intel、Windows x64 和 Linux x64 Runner 构建安装包。macOS 测试模式会校验完整 ad-hoc 签名和 DMG 完整性；`developer-id` 模式还会强制检查 Developer ID、Hardened Runtime、DMG 公证票据和 Gatekeeper 评估。任何一项失败都会终止整个发布，不会同步到管理台。最终的 `agent-manager-client-update-feed` Artifact 包含安装包、自动更新包和 `latest.json`；也可以在 Actions 页面手动运行工作流，先验证四个平台的普通构建。

生产发布由标签为 `agent-manager-release` 的 GitHub self-hosted runner 自动同步到内部发布环境：版本文件保存到 `/home/ubuntu/releases/client-YY.MM.DD.N`。流水线比较候选 `latest.json` 与当前内部版本，只有候选版本不低于当前版本时才更新 `/home/ubuntu/skill-manager/scanner/releases` 和 `client-latest`；较旧构建只归档，不会覆盖最新版。企业微信通知地址通过 Repository Secret `WECHAT_WEBHOOK_URL` 配置，不写入仓库。

下载并解压最终 Artifact 后，将其中的文件放入服务端：

```text
scanner/releases/
  latest.json
  agent-manager-client-26.03.15.2-darwin-aarch64.dmg
  agent-manager-client-26.03.15.2-darwin-x86_64.dmg
  agent-manager-client-26.03.15.2-windows-x86_64.exe
  agent-manager-client-26.03.15.2-linux-x86_64.AppImage
  agent-manager-client-26.03.15.2-darwin-aarch64.app.tar.gz
  agent-manager-client-26.03.15.2-darwin-x86_64.app.tar.gz
```

管理台“客户端管理 → 安装客户端”按四段版本比较，只展示最新版本的 `.dmg`、`.exe` 和 `.AppImage`，历史版本即使仍保存在发布目录中也不会出现在下载列表。Windows 和 Linux 复用安装包执行更新，macOS 的更新压缩包不会出现在手动下载列表。正式构建左下角显示完整版本，例如 `版本 26.03.15.2`；本地 `npm run dev` 或普通 `npm run build` 显示 `版本 dev`。

正式客户端在成功接入平台后会静默检查一次更新，运行期间每 6 小时再次检查，重新回到前台时也会在超过检查间隔后补查。发现新版本后会发送一次系统通知，并将“检查更新”按钮改为“可更新 版本号”；客户端不会在启动时强制弹出更新窗口，也不会对同一版本重复发送系统通知。用户点击“可更新”后可查看说明并确认安装。

更新检查和文件下载均要求有效的客户端接入凭证。内网 HTTP 可以使用，但更新包仍必须通过内置公钥验签；生产环境优先使用 HTTPS。

## 10. 操作系统代码签名

Updater 签名只证明更新包来自 Agent Manager 发布流程，不能替代操作系统代码签名。正式交付前还需要：

- macOS：Apple Developer ID Application 证书签名，并完成 notarization；正式标签流水线已强制执行签名与公证门禁。
- Windows：使用企业代码签名证书或 Azure Artifact Signing 对安装程序签名。
- Linux：按客户软件源要求对 AppImage 或仓库包执行 GPG 签名。

证书、私钥和密码只能保存在 CI Secret 或专用签名服务中，不写入仓库。没有平台证书时仍可生成内部测试安装包，但不应作为正式客户发行版。
