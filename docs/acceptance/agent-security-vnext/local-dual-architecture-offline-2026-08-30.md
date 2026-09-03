# A7-04 双架构完整离线包本地验收证据

> 结论：A7-04 已完成内部验证。当前未提交工作树分别生成 ARM64 和 x86_64 完整离线包，
> 两个包均完成解包、镜像归档重载、Worker 门禁和独立 Compose 启动。ARM64 为本机原生执行，
> x86_64 为 ARM64 Docker 主机上的模拟执行；本证据不是银行目标主机验收，也不关闭 BANK-12、
> BANK-13 或 P7-12。

## 供应链修复后复验

同日修复前端依赖安全告警后，以内部标识 `p7-a704-supply-chain-refresh` 重新构建当前工作树，
旧包仅保留历史流程证据，以下新包和哈希作为最新内部双架构证据：

| 架构 | 完整包大小 | 完整包 SHA-256 | 内层镜像归档 SHA-256 |
|---|---:|---|---|
| ARM64 | 1,030,854,279 bytes | `7fe9459425dd214146e43f07f2f528bef63c0633eccff00c68e05c7c600354f6` | `36eab6a41b57a7849006d997f017139d51e40404c1a49a49046fe9c9e99385e8` |
| x86_64 | 1,104,370,107 bytes | `821ebb15ba2cb537944db346c18a3a3f3bff37a3f09865539687b50b56e67953` | `ffc18e580c85378f170c1292aa17061e2e0a149b294184a40ab22b08a95bbee2` |

两个包的 provenance 均记录 Commit `3f9ea5398154fb9190820bff223ce1ff6f0357fc`、对应平台、
`source_mode=worktree` 和 `worktree_dirty=true`。这符合内部工作树复验口径，不满足正式发布必须来自
干净 `git_clone` 的 P7-12 最终门禁。

验证时先删除本次专用镜像标签，再从各自包内 `.tar.xz` 重载。ARM64 五类镜像均为 arm64，
Frontend ID 为 `sha256:e6ffe059…`；x86_64 五类镜像均为 amd64，Frontend ID 为
`sha256:d7d552e6…`。两种架构的 Worker 均通过 UID/GID 10001、许可证/NOTICE/SBOM、断网、只读根
文件系统、去 capability、`no-new-privileges` 和资源限制门禁。前端镜像构建日志均显示
`found 0 vulnerabilities`。复验后精确测试标签已删除，共享 Nginx 标签恢复为宿主 ARM64；运行中的
Hermes 和 Redis 容器未改变。

## 环境和范围

- 日期：2026-08-30
- 宿主机：macOS ARM64；Docker Server 29.4.0，Linux/ARM64
- 来源：当前 Git 工作树，通过 `package-release.sh --source-dir .` 打包
- 版本标识：`p7-a704-current`（内部验收标识，不是正式发布 tag）
- 完整镜像范围：Backend、Frontend、Sandbox、Sandbox Runtime、Agent Security Worker 和 Nginx
- 安全边界：`--source-dir` 只复制 Git 已跟踪文件和未被忽略的新文件；`.env` 和 `.git` 未进入归档

## 离线包和镜像归档

| 架构 | 完整包大小 | 完整包 SHA-256 | 内层镜像归档 SHA-256 |
|---|---:|---|---|
| ARM64 | 1,030,699,147 bytes | `38d080dace73774897f02c997d4367f549f28edcea9e67deacce40a8c7b8016b` | `c3c496a70869481db501b65710d0283c6923119a5e3216cf90788ea271e8cf79` |
| x86_64 | 1,103,984,431 bytes | `aa8f29ed7c0b7cf286d2aa4183e4165ee44633faf573d0dfb75a144cb41b7180` | `6191a67123c198dc11fc2f330f850046545e93f582fcc90e61c4edd65404a686` |

两个压缩包根目录均固定为 `agent-manager/`，并包含 `docker-compose.yaml`、`.env.example`、
双架构 Docker 安装器和对应架构的完整镜像归档。

## ARM64 原生验证

从 ARM 包解压后，删除仅本次创建的五个 `p7-a704-current` 镜像标签，再通过内层 `.tar.xz`
执行 `docker load`。加载后的镜像均为 ARM64：

| 镜像 | Image ID |
|---|---|
| Backend | `sha256:bd7940c7be2cf63957a5c1bf565b2e6b6ed7742219782d92ced49614772b5408` |
| Frontend | `sha256:175aa9a2b1b3367fe3b41a06ad54245838a94342e93e19710d1055868ed3507f` |
| Sandbox | `sha256:45065b9ee081b179b5d24f22987a14cbc8bdd2c33bc2424c42a9d71943939d0d` |
| Sandbox Runtime | `sha256:435e042c0dce8ea68a2e2fb76784d2a02af8493a6ab76ee78ee4006a29d62ae2` |
| Agent Security Worker | `sha256:aa2120c7ffb380315bdd75ed29b9220c57617ccc7c8b1eb828a3791ebbbce53a` |

- Worker 门禁：架构、UID/GID 10001、健康命令、许可证/NOTICE/SBOM、断网和受限运行通过。
- 独立项目：`agent-security-a704-arm-install`。
- Backend、Frontend、Sandbox 和 Nginx 均为 `healthy`，首页访问成功。
- 测试结束后项目容器、网络和四个独立数据卷已删除；原项目数据未使用或修改。

## x86_64 模拟执行验证

从 x86 包重复相同的删除精确测试标签和 `docker load` 流程。加载后的镜像均为 amd64：

| 镜像 | Image ID |
|---|---|
| Backend | `sha256:e4c443f238f15649421f723611540beaa32529f9ba84e500ef9fe549b5a4ff08` |
| Frontend | `sha256:553612134d2f6c18bf98ace3a54435f26c21a3fbd640e490dd29e4de4020abee` |
| Sandbox | `sha256:d5047bd7aee02f3712a8de96c409844aee42e93af9e247a40dd310e0fa74c3ff` |
| Sandbox Runtime | `sha256:07a74aaeee15feddeb2e76fd9731a94846bce2f4d06419ffd56249763e38b70e` |
| Agent Security Worker | `sha256:f7e25db97e88ef09e5dfc3a9d8e4e77fc62b346d7cab061fb940c301a0649e04` |

- Worker 门禁：架构、UID/GID 10001、健康命令、许可证/NOTICE/SBOM、断网和受限运行通过。
- 独立项目：`agent-security-a704-x86-install`；Docker 明确报告宿主 ARM64、请求镜像 amd64。
- Backend、Frontend、Sandbox 和 Nginx 在模拟执行下均为 `healthy`，首页访问成功。
- 测试结束后项目容器、网络和四个独立数据卷已删除。

## 已知限制和遗留风险

- x86_64 结果证明完整包能在模拟执行环境启动，不等于真实 x86_64 服务器的内核、存储、网络、
  性能或 Docker 兼容性验收。
- 两个包均是当前未提交工作树的内部验收产物，不是从已验证 tag 生成的正式发布物。
- 未在银行主机执行 Docker 安装器、升级迁移、备份恢复或真实业务回归，因此 BANK-12、BANK-13
  和 P7-12 继续保持“未验证”。
- 初次构建记录的 1 个 low、5 个 high 前端依赖漏洞已在供应链复验中关闭；Axios、Vite 和受控
  传递依赖升级后，宿主与双架构镜像构建的 `npm audit` 均为 0。生产包仍需在正式 tag 流水线重复门禁。
