package hooks

func qoderHookAdapter() hookAdapter {
	return hookAdapter{Decode: func(hook string, raw []byte) (input, error) {
		in, err := standardCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		if !validID(in.RequestSet, false) || !validID(in.ParentRequestSet, false) {
			return in, code("aidr_hook_identity_invalid")
		}
		if in.Prompt != "" {
			in.Turn = in.Prompt
		}
		if in.RequestSet != "" {
			in.Turn = in.RequestSet
		} else if hook == "Stop" && in.ParentRequestSet != "" {
			in.Turn = in.ParentRequestSet
		}
		return in, nil
	}, WriteDecision: writeCommandDecision, Settings: &settingsFormat{Path: ".qoder/settings.json", Nested: true, Timeout: 60}}
}
