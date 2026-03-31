# OpenClaw Skill Manager Hook Demo

这是一个 OpenClaw hook pack 骨架，用来把 Skill Manager 接到 OpenClaw 的 skill 生命周期里。

当前实现目标：

1. 在 `agent:bootstrap` 时对本地 skill 做验签和 `can-load` 校验
2. 提供一个单独的 Plugin Hook skeleton，用于 `before_tool_call` 时对 tool 做 `check-tool` 校验

当前目录：

- [HOOK.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/HOOK.md)
- [handler.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/handler.ts)
- [skill-manager-client.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/lib/skill-manager-client.ts)
- [signer.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/lib/signer.ts)
- [discovery.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/lib/discovery.ts)
- [context.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/lib/context.ts)
- [plugin-hooks.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/plugin-hooks.ts)
- [plugin-hook-pack/README.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/plugin-hook-pack/README.md)
- [hooks/payload-recorder/HOOK.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/hooks/payload-recorder/HOOK.md)
- [hooks/payload-recorder/handler.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/hooks/payload-recorder/handler.ts)

## Notes

- 这是 hook pack 骨架，不是已经接入某个具体 OpenClaw 内部类型定义后的最终成品
- 代码尽量贴近文档里的 hook 事件模型
- `resolveSkillNameFromContext()` 和 `discoverVisibleSkills()` 里有一部分是保守实现，后面需要按你实际 OpenClaw gateway event shape 再细化

## Environment

```bash
export SKILL_MANAGER_BASE_URL="http://127.0.0.1:8080"
export SKILL_MANAGER_SIGNING_KEY="same-key-as-skill-manager"
```

## Hook Types

这里分成两类：

1. Internal hook
   - 当前 [HOOK.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/HOOK.md)
   - 事件：`agent:bootstrap`
   - 作用：加载前验签和 gating

2. Plugin hook skeleton
   - 当前 [plugin-hooks.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/plugin-hooks.ts)
   - 事件：`before_tool_call`
   - 作用：运行时 tool gating

## Payload Recorder

我额外加了一个可直接安装的调试 hook：

- [hooks/payload-recorder/HOOK.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/hooks/payload-recorder/HOOK.md)

它会把真实 `agent:bootstrap` payload 记录到：

```text
~/.openclaw/logs/hook-payloads.jsonl
```

这样你就能拿真实 OpenClaw event 回来继续把 Skill Manager hook 收得更准。

## Suggested Install Layout

建议先分两步安装：

### 1. Internal hook

把当前目录里的 internal hook 安装成 managed hook：

```bash
mkdir -p ~/.openclaw/hooks/skill-manager-guard
rsync -a /Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/ ~/.openclaw/hooks/skill-manager-guard/
openclaw hooks enable skill-manager-guard
```

如果你只想先抓 payload，可以只安装：

```bash
mkdir -p ~/.openclaw/hooks/payload-recorder
rsync -a /Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/hooks/payload-recorder/ ~/.openclaw/hooks/payload-recorder/
openclaw hooks enable payload-recorder
```

### 2. Plugin hook

`before_tool_call` 不是 internal hook 事件，所以需要走 plugin hook。

现在这个 demo 里给了一个最小骨架：

- [plugin-hook-pack/README.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/plugin-hook-pack/README.md)

后面你需要把：

- [plugin-hooks.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/plugin-hooks.ts)

接进你实际的 OpenClaw plugin 工程里。

## Recommended Real-World Sequence

建议你现在按这个顺序做：

1. 安装 `payload-recorder`
2. 触发一次 OpenClaw agent 启动
3. 读取 `~/.openclaw/logs/hook-payloads.jsonl`
4. 把真实 `agent:bootstrap` payload 给我
5. 我根据真实结构收紧：
   - [discovery.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/lib/discovery.ts)
   - [handler.ts](/Users/huangluguang/Desktop/Project/skill-manager/demo/openclaw-skill-manager-hook/handler.ts)
6. 再接 plugin 的 `before_tool_call`

## Next Step

后面你可以把这个目录当作 managed hook 或 plugin hook 来接 OpenClaw，再根据真实 event shape 微调：

- `event.context`
- `event.messages`
- `event.context.bootstrapFiles`
- `before_tool_call` 的 plugin hook payload
