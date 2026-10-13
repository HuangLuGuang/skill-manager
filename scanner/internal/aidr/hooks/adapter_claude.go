package hooks

import "context"

func claudeHookAdapter() hookAdapter {
	return hookAdapter{Plugin: claudeNativePlugin(), Decode: func(hook string, raw []byte) (input, error) {
		in, err := standardCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		if in.Prompt != "" {
			in.Turn = in.Prompt
		}
		return in, nil
	}, WriteDecision: writeCommandDecision}
}

func claudeNativePlugin() *nativePluginAdapter {
	return &nativePluginAdapter{
		Inspect: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return inspectNativePlugin(ctx, "claude", binary, home, value)
		},
		Install: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return installNativePlugin(ctx, "claude", binary, home, value)
		},
		Update: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return updateNativePlugin(ctx, "claude", binary, home, value)
		},
		Uninstall: func(ctx context.Context, binary, home, value string) (PluginStatus, error) {
			return uninstallNativePlugin(ctx, "claude", binary, home, value)
		},
	}
}
