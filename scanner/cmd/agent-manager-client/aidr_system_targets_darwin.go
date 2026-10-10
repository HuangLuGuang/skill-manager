//go:build darwin

package main

import (
	"context"
	"debug/macho"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/upload"
)

type systemCandidate struct {
	ID           string `json:"id"`
	Product      string `json:"product"`
	Path         string `json:"path"`
	Entry        string `json:"entry"`
	Availability string `json:"availability"`
	Source       string `json:"source"`
}
type systemTargetView struct {
	Version          string            `json:"version"`
	Revision         string            `json:"revision"`
	DiscoveryRequest string            `json:"discovery_request"`
	Items            []systemCandidate `json:"items"`
}
type systemTargetSelection struct {
	Binding  string   `json:"binding"`
	Version  string   `json:"expected_version"`
	Revision string   `json:"expected_revision"`
	IDs      []string `json:"ids"`
}

func systemProduct(path string) (string, string) {
	switch {
	case strings.Contains(path, "/WorkBuddy.app/Contents/MacOS/"):
		return "workbuddy", "desktop"
	case strings.HasSuffix(path, "/codex") && (strings.Contains(path, "/ChatGPT.app/") || strings.Contains(path, "/Codex.app/")):
		return "codex", "bundled_cli"
	case filepath.Base(path) == "codex":
		return "codex", "cli"
	case filepath.Base(path) == "claude" || strings.Contains(path, "/.local/share/claude/versions/"):
		return "claude", "cli"
	}
	return "", ""
}

func inspectSystemCandidate(ctx context.Context, path, source string) (systemCandidate, bool) {
	real, err := filepath.EvalSymlinks(path)
	if err != nil || !filepath.IsAbs(real) || len(real) >= 1024 || strings.ContainsAny(real, "\n\r\t") {
		return systemCandidate{}, false
	}
	info, err := os.Stat(real)
	if err != nil || !info.Mode().IsRegular() {
		return systemCandidate{}, false
	}
	product, entry := systemProduct(real)
	if product == "" {
		if source != "custom" {
			return systemCandidate{}, false
		}
		product, entry = "custom", "custom"
	}
	item := systemCandidate{Product: product, Entry: entry, Path: real, Source: source, Availability: "available"}
	native := false
	if file, e := macho.Open(real); e == nil {
		native = true
		file.Close()
	} else if fat, e := macho.OpenFat(real); e == nil {
		native = true
		fat.Close()
	}
	identity := fmt.Sprintf("%s:%d:%d", real, info.Size(), info.ModTime().UnixNano())
	if !native || info.Mode().Perm()&0111 == 0 {
		item.Availability = "not_native"
	} else {
		check, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		if e := exec.CommandContext(check, "/usr/bin/codesign", "--verify", "--strict", real).Run(); e != nil {
			item.Availability = "unsigned"
		} else if output, e := exec.CommandContext(check, "/usr/bin/codesign", "-d", "--verbose=4", real).CombinedOutput(); e == nil {
			for _, line := range strings.Split(string(output), "\n") {
				if strings.HasPrefix(line, "CDHash=") {
					identity += ":" + line
				}
			}
		} else {
			item.Availability = "unreadable"
		}
	}
	item.ID = systemHash([]byte(product + ":" + identity))
	return item, true
}

func discoverSystemCandidates(ctx context.Context, home string, custom []string) []systemCandidate {
	items := make([]systemCandidate, 0)
	seen := map[string]bool{}
	add := func(path, source string) {
		if len(items) >= 64 || ctx.Err() != nil {
			return
		}
		real, e := filepath.EvalSymlinks(path)
		if e != nil || seen[real] {
			return
		}
		if item, ok := inspectSystemCandidate(ctx, real, source); ok {
			seen[real] = true
			items = append(items, item)
		}
	}
	for _, root := range []string{"/Applications", filepath.Join(home, "Applications")} {
		for _, relative := range []string{
			"ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
			"ChatGPT.app/Contents/Resources/codex-cli/bin/codex", "Codex.app/Contents/Resources/codex",
			"WorkBuddy.app/Contents/MacOS/Electron", "WorkBuddy.app/Contents/MacOS/WorkBuddy",
		} {
			add(filepath.Join(root, relative), "common_path")
		}
	}
	for _, agent := range []string{"claude", "codex"} {
		for _, root := range []string{filepath.Join(home, ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"} {
			add(filepath.Join(root, agent), "common_path")
		}
		if path, err := exec.LookPath(agent); err == nil {
			add(path, "common_path")
		}
	}
	for _, pattern := range []string{
		"/opt/homebrew/lib/node_modules/@openai/codex*/vendor/*/codex/codex",
		"/usr/local/lib/node_modules/@openai/codex*/vendor/*/codex/codex",
		filepath.Join(home, ".nvm/versions/node/*/lib/node_modules/@openai/codex*/vendor/*/codex/codex"),
		filepath.Join(home, ".nvm/versions/node/*/lib/node_modules/@openai/codex/node_modules/@openai/codex-*/vendor/*/codex/codex"),
	} {
		matches, _ := filepath.Glob(pattern)
		for _, path := range matches {
			add(path, "common_path")
		}
	}
	// ps returns executable names, not argv; no customer program is executed.
	if out, err := exec.CommandContext(ctx, "/bin/ps", "-axo", "comm=").Output(); err == nil {
		for _, path := range strings.Split(string(out), "\n") {
			path = strings.TrimSpace(path)
			if product, _ := systemProduct(path); product != "" && filepath.IsAbs(path) {
				add(path, "running")
			}
		}
	}
	for _, path := range custom {
		add(path, "custom")
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].Product != items[j].Product {
			return items[i].Product < items[j].Product
		}
		return items[i].Path < items[j].Path
	})
	return items
}

func systemTargets(home, action, selection, custom string, out io.Writer) error {
	cfg, paths, err := desktopBinding(home)
	if err != nil {
		return err
	}
	c, err := upload.New(upload.Options{Server: cfg.Server, ClientID: paths.Device, Token: cfg.Token})
	if err != nil {
		return err
	}
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	data, result := c.RuntimeGet(ctx, "collection/device")
	if result.Code != "" {
		return errors.New(result.Code)
	}
	var view systemTargetView
	if json.Unmarshal(data, &view) != nil {
		return systemError("response_invalid")
	}
	if action == "targets" {
		return writeSystemTargetView(data, cfg.Server, paths.Device, out)
	}
	if action == "select" {
		var value systemTargetSelection
		if len(selection) > 8192 || json.Unmarshal([]byte(selection), &value) != nil || len(value.IDs) == 0 || len(value.IDs) > 32 {
			return systemError("request_invalid")
		}
		if value.Binding != systemHash([]byte(cfg.Server+"\x00"+paths.Device)) {
			return errors.New("aidr.system_selection_conflict")
		}
		byID := map[string]systemCandidate{}
		for _, item := range view.Items {
			byID[item.ID] = item
		}
		for _, id := range value.IDs {
			item, ok := byID[id]
			if !ok {
				return errors.New("aidr.system_candidate_changed")
			}
			actual, exists := inspectSystemCandidate(ctx, item.Path, item.Source)
			if !exists || actual.ID != id || actual.Availability != "available" {
				return errors.New("aidr.system_candidate_changed")
			}
		}
		data, result = c.SystemCollection(ctx, "selection", map[string]any{"expected_version": value.Version, "expected_revision": value.Revision, "ids": value.IDs})
	} else {
		customPaths := []string{}
		for _, item := range view.Items {
			if item.Source == "custom" {
				customPaths = append(customPaths, item.Path)
			}
		}
		if action == "add-program" {
			if _, ok := inspectSystemCandidate(ctx, custom, "custom"); !ok {
				return systemError("path_invalid")
			}
			customPaths = append(customPaths, custom)
		}
		items := discoverSystemCandidates(ctx, home, customPaths)
		if ctx.Err() != nil {
			return errors.New("aidr_upload_transport")
		}
		data, result = c.SystemCollection(ctx, "discovery", map[string]any{"items": items})
	}
	if result.Code != "" {
		return errors.New(result.Code)
	}
	return writeSystemTargetView(data, cfg.Server, paths.Device, out)
}

func writeSystemTargetView(data []byte, server, device string, out io.Writer) error {
	var value map[string]any
	if json.Unmarshal(data, &value) != nil || value == nil {
		return systemError("response_invalid")
	}
	value["binding"] = systemHash([]byte(server + "\x00" + device))
	return json.NewEncoder(out).Encode(value)
}
