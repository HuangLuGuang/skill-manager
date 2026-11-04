# Sandbox Service Architecture

这个文档描述 Agent Manager 的 Sandbox 演进方向：

- 当前方案：本机 Docker probe
- 目标方案：独立隔离执行服务

这里参考了 [langgenius/dify-sandbox](https://github.com/langgenius/dify-sandbox?tab=readme-ov-file) 的思路，但实现命名保持中性，不把外部项目名称直接写进代码。

## 目标

Agent Manager 负责治理：

- skill 提交
- scanner / behavioral / LLM
- 风险分级
- 审批和部署
- 运行时校验

Sandbox 负责执行：

- 在受限环境里运行 skill 的 probe
- 记录 stdout / stderr / exit code
- 观察网络、文件系统、动态执行等信号
- 把结果回填到 `scan_report.sandbox_analysis`
- 从 Skill 中选择一个真实脚本入口，执行一个保守的默认 probe

## 架构对比

```mermaid
flowchart TB
    A["上传 Skill"] --> B["Agent Manager<br/>scanner / behavioral / LLM / policy"]
    B --> C{"选择 Sandbox 后端"}

    C --> D1["DockerSandboxRunner"]
    C --> D2["RemoteSandboxRunner"]

    D1 --> E1["本机 docker run<br/>限资源 / 只读挂载 / 禁网"]
    D2 --> E2["独立隔离执行服务<br/>chroot / seccomp / setuid / 空环境"]

    E1 --> F["SandboxResult"]
    E2 --> F

    F --> G["scan_report.sandbox_analysis"]
    G --> H["前端详情 / 审批 / 审计"]
```

## 当前实现

代码位置：

- [agent_manager/core/sandbox.py](../agent_manager/core/sandbox.py)
- [agent_manager/core/vetting.py](../agent_manager/core/vetting.py)

当前已经支持：

- `DockerSandboxRunner`
- `RemoteSandboxRunner`
- `get_sandbox_runner()` 工厂切换
- 一个生产版独立服务基线实现：
  [services/isolated-sandbox-service/README.md](../services/isolated-sandbox-service/README.md)

说明：

- `DockerSandboxRunner` 适合本地开发、单机试跑
- `RemoteSandboxRunner` 是独立执行服务适配层骨架，适合后续接 Linux 上的隔离执行服务

## 选择逻辑

```mermaid
sequenceDiagram
    participant Submit as "submit()"
    participant Vetting as "VettingPipeline"
    participant Factory as "get_sandbox_runner()"
    participant Runner as "Sandbox Backend"

    Submit->>Vetting: vet(..., use_sandbox)
    Vetting->>Vetting: 并行执行 scanner / behavioral / deep scan
    Vetting->>Vetting: 根据风险和策略判断是否强制 sandbox
    Vetting->>Factory: 读取 SandboxConfig
    Factory-->>Vetting: DockerSandboxRunner or RemoteSandboxRunner
    Vetting->>Vetting: discover entrypoint + default probe
    Vetting->>Runner: run_probe(skill_path, entrypoint, args)
    Runner-->>Vetting: SandboxResult
    opt 勾选 LLM
      Vetting->>Vetting: 汇总确定性证据后调用一次 LLM
    end
    Vetting->>Vetting: 合并到 scan_report.sandbox_analysis
```

## Probe 生成策略

默认情况下，sandbox 会先做保守 probe：

- 从 `scripts/` 和 Skill 根目录自动发现一个 `.py`、`.sh` 或 `.js` 入口
- 如果入口脚本看起来是 CLI，例如使用 `argparse`、`click`、`typer`，默认 probe 会用 `--help`
- 否则用空参数执行一次

当前 Vetting 流程只执行这一个默认 probe。没有支持的入口时会跳过，不执行 `SKILL.md` 中的 shell 命令块，也不调用 LLM 生成额外 probe。LLM 只在所选确定性分析器完成后做一次最终语义研判。
- 不允许生成破坏性参数
- 不保证覆盖所有恶意分支

最终报告中会出现：

- `sandbox_analysis.probe_cases`
- `sandbox_analysis.probe_results`
- `sandbox_analysis.llm_probe_plan`

其中 `probe_results` 会保留每个 case 的 stdout、stderr、exit code、风险信号和耗时。

Skill 详情的 Sandbox 调试信息在“说明”之前展示整行“错误输出”，读取汇总报告的 `sandbox_analysis.stderr`；每条 Probe 展开详情在“执行结果”之前展示自身 `stderr`。均以纯文本保留原文及换行，长行换行、内容最高显示 280px 并滚动。标签通过 `skillDetail.sandboxErrorOutput` 提供中英文；stderr 为空、null 或缺失时内容留空。复用已有报告字段，无需数据库迁移或新增部署配置。

## RemoteSandboxRunner 设计

`RemoteSandboxRunner` 将高风险 skill 的试跑移到独立服务。

推荐对接的独立服务能力：

- 受控语言运行时
- 空环境变量
- chroot 或等价文件系统隔离
- seccomp 或等价 syscall 限制
- setuid / setgid 降权
- 请求级网络开关

Agent Manager 需要的只是一个稳定返回结果的 HTTP API，不关心对方具体实现细节。

### 请求 schema

`RemoteSandboxRunner` 当前向远程服务发送：

```json
{
  "language": "python3",
  "code": "print('hello')",
  "preload": "",
  "enable_network": false,
  "metadata": {
    "entrypoint": "scripts/run.py",
    "args": ["--help"],
    "probe_name": "default"
  }
}
```

### 响应 schema

请求的 `files` 数组保存文件路径、内容与 `encoding`。UTF-8 文件使用 `encoding: "utf-8"`，其余文件以 `encoding: "base64"` 传送并在服务端恢复原始字节。发送二进制前，客户端确认 `/health` 的 `file_encodings` 包含 `base64`，服务端需先升级到支持该协议的版本。

`timeout_seconds` 指定本次执行时限，服务端使用它与自身执行时限的较小值。HTTP 等待时间比执行时限多 5 秒，用于接收隔离进程终止和结果清理后的响应。服务返回 `timed_out`，客户端同时兼容已有 message/error 超时说明。执行超时、传输失败及脚本退出错误分别记录在本次报告中。

当前兼容两种返回：

1. 包裹型响应，适合独立执行服务

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stdout": "ok",
    "stderr": "",
    "exit_code": 0,
    "duration_ms": 12
  }
}
```

2. 扁平型响应，适合轻量代理层

```json
{
  "stdout": "ok",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 12,
  "message": "success"
}
```

如果远程服务返回非零 `code`，Agent Manager 会把这次 probe 记为未执行成功，并把 `message` 写进 `sandbox_analysis.reason`。

## 配置

当前代码支持以下环境变量：

- `AGENT_MANAGER_SANDBOX_RUNTIME=docker|remote`
- `AGENT_MANAGER_SANDBOX_ENABLED=true|false`
- `AGENT_MANAGER_SANDBOX_URL=http://sandbox:8194`
- `AGENT_MANAGER_SANDBOX_API_KEY=...`
- `AGENT_MANAGER_SANDBOX_TIMEOUT_SECONDS=15`
- `AGENT_MANAGER_SANDBOX_NETWORK_MODE=none`
- `AGENT_MANAGER_SANDBOX_IMAGE=python:3.12-slim`
- `AGENT_MANAGER_SANDBOX_MEMORY_LIMIT=256m`
- `AGENT_MANAGER_SANDBOX_CPU_LIMIT=1.0`
- `AGENT_MANAGER_SANDBOX_PIDS_LIMIT=64`

也支持通过 API 和系统设置页保存到本地配置文件：

- `GET /api/v1/sandbox-config`
- `PUT /api/v1/sandbox-config`

默认配置文件路径：

- `~/.agent-manager/sandbox.yaml`

## 为什么保留 Docker 后端

短期不建议直接切掉 Docker probe，原因有两个：

1. 本地开发更简单
2. 远程隔离执行服务通常更依赖 Linux 环境和额外运维

推荐模式：

- 开发环境：`docker`
- 高风险或生产：`remote`

## 后续建议

1. 对高风险 skill 在 sandbox 不可用时收紧策略，改为直接进入 `VETTED` 或 `REJECTED`
2. 为远程 sandbox 增加更强的文件访问和进程审计
3. 提交结果和 vetting 结果中保留这些可观察字段：
   - `sandbox_triggered`
   - `sandbox_required_by_policy`
   - `sandbox_runtime`
   - `sandbox_analysis.probe_cases`
   - `sandbox_analysis.probe_results`

## Sandbox 调试信息悬浮说明

### 调试说明的中英文展示

调试汇总和 Probe 执行结果的 `reason` 保留原文；平台生成的新结果同时提供 `reason_code` 和 `reason_params`，详情按 `skillDetail.sandboxReasons` 双语资源显示。已知原因包括 nsjail / subprocess 执行、默认或指定参数、超时、Docker 不可用、运行方式或脚本类型不支持、远程地址未配置、请求失败、拒绝执行、响应格式异常和跳过分析。远程服务的 `success` 表示请求已处理，脚本执行结果通过退出码查看。

原因识别集中在 `agent_manager/core/sandbox.py`。已有报告在扫描报告 API 响应中补齐汇总及 Probe 原因编码，不回写历史报告；已存在的编码和参数保留。前端仅翻译资源声明的编码，未知说明原样显示。动态异常、URL、路径、状态码及多行上游错误作为参数保留原文，使用文本转义和换行显示；内置远程服务明确的后端不可用模板可完整翻译。

HTTPX 状态异常的固定模板（响应类型、请求地址前缀、重定向地址前缀和“更多信息请参阅”）通过 `reason_params.http_*` 与 `skillDetail.sandboxHttpErrors` 双语展示；HTTP 状态码及 reason phrase、请求 URL、重定向目标和文档链接保留原文。仅完整匹配 HTTPX 模板时提取参数，自定义错误仍显示原文。已有 `remote_request_failed` 报告在读取时补齐参数，保留原始 `reason`、`detail` 和编码。顶部摘要等于该次原因时复用相同翻译；独立摘要继续使用原有展示逻辑。Probe 执行结果不重复展示与原因相同的摘要，建议使用现有译文。

默认 Probe 描述、平台产生的全部固定信号（网络访问、文件访问、输入缺失及超时）、固定摘要和建议使用 `skillDetail.sandboxText`。扫描报告保存及历史读取共用固定模板识别，为字段添加对应的 `*_code` 和必要的 `*_params`，信号使用 `message_code`。风险摘要的数量和类别参数来自原始摘要，类别和默认/命令行帮助策略按界面语言显示；未知类别、用户提供的 Probe 描述和自定义摘要保留原文。历史报告不回写，已有展示编码保留；这些元数据仅用于展示，不参与执行状态和风险计算。切换语言后顶部、风险和诊断信号列表、Probe 描述、执行结果与建议同步更新。未命中语义编码的字段直接显示原始内容（包括空白），不经过 legacy 翻译；信号证据以纯文本保留完整内容和换行。Probe 说明组合仅跳过缺失或空字符串，纯空白说明仍保留；摘要、信号、建议和描述使用保留空白的文本容器显示。已知类别使用相同的语义资源，未知类别保持原值。

使用时切换系统语言即可查看对应说明，不需要重扫历史 Skill。原因编码不参与执行状态或风险判定。该变更不增加数据库查询、表结构、索引或外部翻译调用，Docker 沿用现有数据卷和升级方式。维护新增固定说明时同步更新原因识别、双语资源与后端测试，页面验证覆盖中英文及未知原文。

验收样本通过实际 Runner、扫描流程或历史报告生成，样本名称标注测试用途，测试清单记录输入、执行分支和报告来源。构造外部服务响应时沿用远程服务协议，执行状态、超时、退出码及 Probe 说明由生产代码生成；历史兼容样本保留报告业务字段，仅使用旧报告已有的元数据形态。

远程服务执行结果的超时识别同时覆盖 `message` / `error` 中的 `timeout` 和 `timed out`（忽略大小写），兼容内置服务的 `execution timed out`。该结果保持实际返回的退出码，并生成超时信号参与现有风险汇总；新报告保存正确标识，历史报告继续按当时保存值展示。

### 字段悬浮说明

Skill 详情的调试信息、Probe 列表及展开详情复用 `SandboxDebugHelp.vue`，双语文案位于 `skillDetail.sandboxHelp`。术语与全部取值含义集中在字段名或表头的说明图标；缺失信息的 `-` 也在对应字段说明中解释。运行时显示“远程服务 / 本地 Docker”或英文名称。网络尝试直接显示次数（如 `0次 / 0 attempts`）。

将鼠标移至说明图标或使用键盘聚焦，可查看说明。`cli-help` 表示平台传入 `--help`，让入口脚本显示使用方法和可用参数。退出码说明分为通用、本地 Docker 模式和远程服务模式：0 为正常结束，Docker 125/126/127 分别表示容器启动失败、命令无法执行和命令未找到，其余非零值说明为异常结束。具体原因查看错误输出或 Sandbox 服务日志。Probe 参数说明按报告区分空数组（未附加参数）与字段缺失或 null（未提供参数信息）。

