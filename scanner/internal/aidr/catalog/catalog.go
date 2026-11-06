// Package catalog embeds the generated copy of backend/aidr_products.json.
// Product IDs are stable wire identities; entry points are separate products.
package catalog

import (
	"embed"
	"encoding/json"
	"path/filepath"
	"runtime"
)

//go:embed products.json
var files embed.FS

type Product struct {
	EnrollmentLogSource string              `json:"enrollment_log_source"`
	LogOS               []string            `json:"log_os"`
	HookOS              []string            `json:"hook_os"`
	SampleVersions      []string            `json:"sample_versions"`
	ID                  string              `json:"id"`
	Name                string              `json:"name"`
	Entry               string              `json:"entry"`
	OS                  []string            `json:"os"`
	Logs                string              `json:"logs"`
	Roots               []string            `json:"roots"`
	RootsByOS           map[string][]string `json:"roots_by_os"`
	Hooks               string              `json:"hooks"`
	Block               bool                `json:"block"`
	Approval            bool                `json:"approval"`
	Managed             bool                `json:"managed"`
	HookEvents          map[string]string   `json:"hook_events"`
	Evidence            string              `json:"evidence"`
	Docs                []string            `json:"docs"`
}

var productCatalog = func() []Product {
	var p []Product
	data, _ := files.ReadFile("products.json")
	if err := json.Unmarshal(data, &p); err != nil {
		panic(err)
	}
	return p
}()

// All returns the immutable embedded directory. Callers must not mutate entries.
func All() []Product { return productCatalog }
func Get(id string) (Product, bool) {
	for _, p := range All() {
		if p.ID == id {
			return p, true
		}
	}
	return Product{}, false
}
func Log(id string) bool     { p, ok := Get(id); return ok && p.Logs != "" }
func Hook(id string) bool    { p, ok := Get(id); return ok && p.Hooks != "" }
func Enabled(id string) bool { return Log(id) || Hook(id) }
func HookIDs() []string {
	var ids []string
	for _, p := range All() {
		if p.Hooks != "" {
			ids = append(ids, p.ID)
		}
	}
	return ids
}
func Kind(agent, event string) string { p, _ := Get(agent); return p.HookEvents[event] }
func SupportedOS(p Product) bool      { return supportsOS(p.OS) }
func SupportedLogOS(p Product) bool   { return supportsOS(p.LogOS) }
func SupportedHookOS(p Product) bool  { return supportsOS(p.HookOS) }
func supportsOS(systems []string) bool {
	for _, os := range systems {
		if os == runtime.GOOS {
			return true
		}
	}
	return false
}
func LogRoots(id, home string) []string {
	p, ok := Get(id)
	if !ok || !SupportedLogOS(p) {
		return nil
	}
	var roots []string
	for _, r := range RelativeLogRoots(p) {
		roots = append(roots, filepath.Join(home, r))
	}
	return roots
}

func RelativeLogRoots(p Product) []string {
	if roots, ok := p.RootsByOS[runtime.GOOS]; ok {
		return roots
	}
	return p.Roots
}
