package hooks

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// A read-only native inventory. No thread/model calls and no trust mutations.
// This local diagnostic is kept separate from older platform report contracts.
func NativeCodexTrust(ctx context.Context, binary, home string) string {
	raw, ok := nativeCodexCall(ctx, binary, home, "hooks/list", map[string]any{"cwds": []string{home}})
	if !ok {
		return "unknown"
	}
	return parseNativeCodexTrust(raw)
}

func NativeCodexManagedTrust(ctx context.Context, binary, home string) string {
	raw, ok := nativeCodexCall(ctx, binary, home, "hooks/list", map[string]any{"cwds": []string{home}})
	if !ok {
		return "unknown"
	}
	layout, err := SystemManagedLayout("codex")
	if err != nil {
		return "unknown"
	}
	return parseNativeManagedTrust(raw, layout)
}

func parseNativeManagedTrust(raw []byte, layout ManagedLayout) string {
	var result struct {
		Data []struct {
			Errors   []json.RawMessage `json:"errors"`
			Warnings []json.RawMessage `json:"warnings"`
			Hooks    []struct {
				Command    string `json:"command"`
				Enabled    bool   `json:"enabled"`
				Managed    bool   `json:"isManaged"`
				Trust      string `json:"trustStatus"`
				SourcePath string `json:"sourcePath"`
				Source     string `json:"source"`
				Event      string `json:"eventName"`
			} `json:"hooks"`
		} `json:"data"`
	}
	if json.Unmarshal(raw, &result) != nil {
		return "unknown"
	}
	expected := map[string]string{}
	for event := range catalog["codex"] {
		expected[managedCommand(layout, "codex", event)] = managedNativeEvent(event)
	}
	seen := map[string]bool{}
	for _, group := range result.Data {
		if len(group.Errors) > 0 || len(group.Warnings) > 0 {
			return "unknown"
		}
		for _, hook := range group.Hooks {
			event, ours := expected[hook.Command]
			if !ours {
				continue
			}
			path := hook.SourcePath
			want := layout.Root
			if resolved, err := filepath.EvalSymlinks(path); err == nil {
				path = resolved
			}
			if resolved, err := filepath.EvalSymlinks(want); err == nil {
				want = resolved
			}
			if seen[event] || hook.Event != event || !hook.Enabled || !hook.Managed || hook.Trust != "managed" || hook.Source != "system" || path != want {
				return "unknown"
			}
			seen[event] = true
		}
	}
	if len(seen) != len(expected) {
		return "unknown"
	}
	return "managed"
}

// Uses the native config writer only to preserve a pre-existing disabled flag
// during an upgrade. Hook trust and all other config values remain host-owned.
func preserveCodexDisabled(ctx context.Context, binary, home, plugin string) bool {
	_, ok := nativeCodexCall(ctx, binary, home, "config/value/write", map[string]any{"keyPath": "plugins.\"" + plugin + "\".enabled", "value": false, "mergeStrategy": "replace"})
	return ok
}

func nativeCodexCall(ctx context.Context, binary, home, method string, params any) (json.RawMessage, bool) {
	results, ok := nativeCodexCalls(ctx, binary, home, []nativeCodexRequest{{method, params}})
	if !ok {
		return nil, false
	}
	return results[0], true
}

type nativeCodexRequest struct {
	method string
	params any
}

func nativeCodexCalls(ctx context.Context, binary, home string, calls []nativeCodexRequest) ([]json.RawMessage, bool) {
	results, err := nativeCodexCallsChecked(ctx, binary, home, calls)
	return results, err == nil
}

var errNativeMethodUnsupported = errors.New("aidr_native_method_unsupported")

func nativeCodexCallsChecked(ctx context.Context, binary, home string, calls []nativeCodexRequest) ([]json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, "app-server", "--stdio")
	cmd.WaitDelay = time.Second
	for _, v := range os.Environ() {
		if !strings.HasPrefix(v, "CODEX_HOME=") {
			cmd.Env = append(cmd.Env, v)
		}
	}
	cmd.Env = append(cmd.Env, "CODEX_HOME="+home)
	inspection := len(calls) > 0
	for _, call := range calls {
		if call.method != "hooks/list" && call.method != "plugin/list" && call.method != "config/read" {
			inspection = false
		}
	}
	if inspection {
		cmd.Env = append(cmd.Env, "AGENT_MANAGER_ACTIVITY=client_probe")
	}
	cmd.Dir = home
	cmd.Stderr = io.Discard
	stdin, e := cmd.StdinPipe()
	if e != nil {
		return nil, e
	}
	stdout, e := cmd.StdoutPipe()
	if e != nil {
		return nil, e
	}
	stop, e := startNativeProcess(cmd)
	if e != nil {
		stdin.Close()
		stdout.Close()
		return nil, e
	}
	defer func() { stdin.Close(); stop(); cancel(); cmd.Wait() }()
	enc := json.NewEncoder(stdin)
	scan := bufio.NewScanner(stdout)
	scan.Buffer(make([]byte, 4096), 512<<10)
	request := func(id int, method string, params any) (json.RawMessage, error) {
		if enc.Encode(map[string]any{"id": id, "method": method, "params": params}) != nil {
			return nil, code("aidr_plugin_source_unreadable")
		}
		for n := 0; n < 128 && scan.Scan(); n++ {
			var r struct {
				ID     int             `json:"id"`
				Result json.RawMessage `json:"result"`
				Error  *struct {
					Code int `json:"code"`
				} `json:"error"`
			}
			if json.Unmarshal(scan.Bytes(), &r) == nil && r.ID == id {
				if r.Error != nil && r.Error.Code == -32601 {
					return nil, errNativeMethodUnsupported
				}
				if r.Error != nil || len(r.Result) == 0 {
					return nil, code("aidr_plugin_source_unreadable")
				}
				return r.Result, nil
			}
		}
		return nil, code("aidr_plugin_source_unreadable")
	}
	if _, err := request(1, "initialize", map[string]any{"clientInfo": map[string]string{"name": "aidr-desktop-inventory", "version": "1"}, "capabilities": map[string]bool{"experimentalApi": true}}); err != nil {
		return nil, err
	}
	enc.Encode(map[string]string{"method": "initialized"})
	results := make([]json.RawMessage, 0, len(calls))
	for i, call := range calls {
		result, err := request(i+2, call.method, call.params)
		if err != nil {
			return nil, err
		}
		results = append(results, result)
	}
	return results, nil
}

func parseNativeCodexTrust(raw []byte) string {
	var result struct {
		Data []struct {
			Errors   []json.RawMessage `json:"errors"`
			Warnings []json.RawMessage `json:"warnings"`
			Hooks    []struct {
				Plugin  string `json:"pluginId"`
				Enabled bool   `json:"enabled"`
				Trust   string `json:"trustStatus"`
			} `json:"hooks"`
		} `json:"data"`
	}
	if json.Unmarshal(raw, &result) != nil {
		return "unknown"
	}
	count := 0
	trusted := true
	for _, g := range result.Data {
		if len(g.Errors) > 0 || len(g.Warnings) > 0 {
			return "unknown"
		}
		for _, h := range g.Hooks {
			if h.Plugin != "aidr-codex@aidr-local" {
				continue
			}
			count++
			if h.Trust != "trusted" || !h.Enabled {
				trusted = false
			}
		}
	}
	if count != 12 {
		return "unknown"
	}
	if trusted {
		return "trusted"
	}
	return "needs_review"
}
