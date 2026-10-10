//go:build darwin

package main

import (
	"context"
	"encoding/xml"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const systemComponentRoot = "/Library/Application Support/AgentManagerRuntime/system/bin"

func boolResult(value bool) *bool { return &value }

// Only the OS codesign program runs during signature inspection. Arbitrary
// component execution is prohibited until ownership and product signer match.
func systemSignature(ctx context.Context, path string, identifier string) (string, []byte, bool) {
	requirement := "anchor apple generic"
	if identifier != "" {
		requirement += ` and identifier "` + identifier + `"`
	}
	verify := exec.CommandContext(ctx, "/usr/bin/codesign", "--verify", "--strict", "-R", requirement, path)
	verify.WaitDelay = 250 * time.Millisecond
	verify.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	if verify.Run() != nil {
		return "", nil, false
	}
	display := exec.CommandContext(ctx, "/usr/bin/codesign", "--display", "--verbose=4", "--entitlements", ":-", path)
	display.WaitDelay = 250 * time.Millisecond
	display.Env = verify.Env
	meta, entitlements := &capabilityOutput{}, &capabilityOutput{max: 65536}
	display.Stderr, display.Stdout = meta, entitlements
	if display.Run() != nil {
		return "", nil, false
	}
	team := signingTeam(meta.data.String())
	return team, entitlements.data.Bytes(), team != ""
}

func signingTeam(metadata string) string {
	for _, line := range strings.Split(metadata, "\n") {
		if strings.HasPrefix(line, "TeamIdentifier=") {
			value := strings.TrimPrefix(line, "TeamIdentifier=")
			if regexp.MustCompile(`^[A-Z0-9]{10}$`).MatchString(value) {
				return value
			}
		}
	}
	return ""
}

type entitlementNode struct {
	XMLName  xml.Name
	Text     string            `xml:",chardata"`
	Children []entitlementNode `xml:",any"`
}

func entitlementPermission(data []byte) *bool {
	if len(data) == 0 {
		return boolResult(false)
	}
	if len(data) > 65536 {
		return nil
	}
	var root entitlementNode
	if xml.Unmarshal(data, &root) != nil || root.XMLName.Local != "plist" || len(root.Children) != 1 || root.Children[0].XMLName.Local != "dict" {
		return nil
	}
	children := root.Children[0].Children
	if len(children)%2 != 0 {
		return nil
	}
	var permission *bool
	for i := 0; i < len(children); i += 2 {
		if children[i].XMLName.Local != "key" {
			return nil
		}
		if children[i].Text == "com.apple.developer.endpoint-security.client" {
			value := children[i+1]
			if permission != nil || (value.XMLName.Local != "true" && value.XMLName.Local != "false") || len(value.Children) != 0 || strings.TrimSpace(value.Text) != "" {
				return nil
			}
			permission = boolResult(value.XMLName.Local == "true")
		}
	}
	if permission == nil {
		return boolResult(false)
	}
	return permission
}

func hasESEntitlement(data []byte) bool {
	value := entitlementPermission(data)
	return value != nil && *value
}

func systemPreflight(parent context.Context) systemPrerequisites {
	ctx, cancel := context.WithTimeout(parent, 5*time.Second)
	defer cancel()
	report := systemPrerequisites{Version: 1, Code: "aidr_system_authorization_entry_required", CheckedAt: time.Now().UTC().Format(time.RFC3339Nano), Components: []systemComponentCheck{}, ESAuthorization: "unknown", ESSubscription: "unknown"}
	for _, name := range []string{"agent-manager-client", "aidr-enforcer"} {
		path := filepath.Join(systemComponentRoot, name)
		item := systemComponentCheck{Name: name, Path: path, Code: "aidr_system_component_missing"}
		info, err := os.Lstat(path)
		if os.IsNotExist(err) {
			item.Exists = boolResult(false)
		} else if err != nil {
			item.Code = "aidr_system_inspection_unavailable"
		} else {
			item.Exists = boolResult(true)
			safe := info.Mode().IsRegular() && info.Mode().Perm()&0111 != 0 && info.Mode()&(os.ModeSetuid|os.ModeSetgid) == 0 && rootFile(path, false) == nil
			item.TrustedPath = boolResult(safe)
			item.Code = "aidr_system_component_untrusted"
			if safe {
				valid := systemVerifyComponent(path, name == "aidr-enforcer", systemDevelopment == "true") == nil
				item.Signature = boolResult(valid)
				item.Code = "aidr_system_signature_unverified"
				if valid {
					item.Code = "aidr_system_component_verified"
					if name == "aidr-enforcer" {
						item.Entitlement = boolResult(true)
						item.CollectionOnly = boolResult(nativeCollectionCapabilitiesContext(ctx, path) == nil)
						if !*item.CollectionOnly {
							item.Code = "aidr_enforcement_collection_unsupported"
						}
					}
				}
			}
		}
		report.Components = append(report.Components, item)
	}
	return report
}
