package hooks

import "context"

func codexHookAdapter() hookAdapter {
	return hookAdapter{Plugin: codexNativePlugin(), Decode: standardCommandHook, WriteDecision: writeCommandDecision}
}

func codexNativePlugin() *nativePluginAdapter {
	return &nativePluginAdapter{
		Inspect: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return inspectNativePlugin(ctx, "codex", binary, home, value)
		},
		Install: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return installNativePlugin(ctx, "codex", binary, home, value)
		},
		Update: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return updateNativePlugin(ctx, "codex", binary, home, value)
		},
		Uninstall: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return uninstallNativePlugin(ctx, "codex", binary, home, value)
		},
	}
}
