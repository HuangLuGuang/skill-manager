# OpenClaw Plugin Hook Pack Skeleton

这个目录是给 `before_tool_call` 用的 plugin hook skeleton。

用途：

- 在 tool 真正执行前调用 Agent Manager 的 `check-tool`
- 如果不允许，返回：
  - `block: true`
  - `blockReason: "..."`

当前文件：

- [package.json](/Users/huangluguang/Desktop/Project/agent-manager/demo/openclaw-agent-manager-hook/plugin-hook-pack/package.json)
- [plugin-hooks.ts](/Users/huangluguang/Desktop/Project/agent-manager/demo/openclaw-agent-manager-hook/plugin-hook-pack/plugin-hooks.ts)

## Notes

- 这是插件 hook 侧的骨架，不是完整 npm 插件工程
- 真正接入时，需要放进你的 OpenClaw plugin 工程，或按你现有 plugin 打包方式组织
