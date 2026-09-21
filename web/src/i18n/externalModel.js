export const externalModelMessages = {
  'zh-CN': {
    source: '模型来源', internal: '内置模型网关', external: '外部 AI 网关', gatewaySelect: '外部 AI 网关',
    prepare: '准备并刷新模型', preparing: '正在注册外部 Agent 并获取模型', refresh: '刷新模型',
    prepareHint: '平台将按默认策略注册或查询外部 Agent，并使用其 API Key 从外部网关实时获取可用模型。', platformPrepareHint: '平台会先创建草稿智能体，再向所选外部网关注册独立身份并获取模型；此流程不依赖客户端。',
    unavailable: '平台策略未允许此外部网关，或尚未选择有效连接。', loadFailed: '获取外部模型失败', empty: '此外部 Agent 当前没有可用模型。', selectAfterRefresh: '请先准备并刷新外部模型。',
    ready: '外部模型已加载', modelCount: '共 {count} 个可用模型', gateway: '网关：{name}', agent: '外部 Agent：{id}', bindingStatus: '绑定状态：{status}', keyId: 'Key ID：{id}', clientReported: '模型切换后由客户端执行真实调用验证。', gatewayRequired: '请选择外部 AI 网关', modelRequired: '请选择外部网关模型', draftCleanupFailed: '草稿智能体清理失败，请在智能体列表中删除后重试。',
  },
  'en-US': {
    source: 'Model source', internal: 'Built-in model gateway', external: 'External AI gateway', gatewaySelect: 'External AI gateway',
    prepare: 'Prepare and refresh models', preparing: 'Registering the external Agent and loading models', refresh: 'Refresh models',
    prepareHint: 'The platform registers or queries the external Agent according to the default policy, then uses its API key to discover available models from the external gateway.', platformPrepareHint: 'The platform first creates a draft Agent, registers a dedicated identity with the selected external gateway, and loads models. No Client is involved.',
    unavailable: 'Platform policy does not allow this external gateway, or no valid connection is selected.', loadFailed: 'Could not load external models', empty: 'No models are currently available to this external Agent.', selectAfterRefresh: 'Prepare and refresh external models first.',
    ready: 'External models loaded', modelCount: '{count} available models', gateway: 'Gateway: {name}', agent: 'External Agent: {id}', bindingStatus: 'Binding status: {status}', keyId: 'Key ID: {id}', clientReported: 'The Client performs a real model call after applying this configuration.', gatewayRequired: 'Select an external AI gateway', modelRequired: 'Select an external gateway model', draftCleanupFailed: 'Could not clean up the draft Agent. Delete it from the Agent list before retrying.',
  },
}
