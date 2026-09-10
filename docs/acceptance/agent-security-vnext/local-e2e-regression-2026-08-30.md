# 智能体安全内部总体验收回归记录

## 结论

2026-08-30 在当前本地工作树执行 `run-agent-security-e2e-regression.sh`，E2E-01～E2E-10
对应的 12 个测试全部通过。该结果证明仓库内可自动复现的总体验收行为已闭环，不等同于银行环境部署、
真实 Agent、银行 MCP Gateway、正式双架构离线包或现场角色验收。

## 来源与执行结果

- Git Commit：`3f9ea5398154fb9190820bff223ce1ff6f0357fc`
- 工作树状态：有未提交变更，结果文件明确记录 `worktree_dirty=true`
- 当前源文件树 SHA-256：`bdf9b1430f94cb05442137aeb05ada9ae1c146f5c91f0dba860fbbd5690d02a7`
- 自动化场景：10 项
- 实际测试：12 项
- 结果：12 passed
- pytest 日志包含 413 条既有弃用警告，无测试失败

## 证据哈希

| 文件 | SHA-256 |
|---|---|
| `e2e-junit.xml` | `aec83063b64888b3068aced8be8fc55938bdb3e9c88454f26434dba509322671` |
| `e2e-pytest.log` | `17619c7f66b57624b0ce85739edd316f7a01697029c4aa866749f4c557cf049a` |
| `e2e-results.json` | `aa10b812eb2c9ead5fcbb614980801981e072f98aec50077170c498def23bf2b` |

逐场景到测试的稳定映射保存在 `e2e-regression-cases.json`，执行脚本只在全部选定测试通过后生成
全通过结果；输出目录必须是绝对空目录，生成的三份证据由 `manifest.sha256` 校验。

## 边界

本记录支持勾选实施计划中的内部 E2E-01～E2E-10，但不能支持勾选 P7-12。P7-12 仍要求
BANK-01～BANK-15 在银行目标环境逐项执行、封包、脱敏复核和独立签署。
