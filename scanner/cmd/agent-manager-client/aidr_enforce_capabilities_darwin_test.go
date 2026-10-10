//go:build darwin

package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestCollectionNativeCompatibilityProbe(t *testing.T) {
	cases := []struct {
		name, script string
		ok           bool
	}{
		{"supported", `test "$1" = '--capabilities' || exit 1
printf '%s' '{"protocol":1,"collection_only":true,"signed_attribution":true}'`, true},
		{"legacy", `exit 64`, false},
		{"controlOnly", `printf '%s' '{"protocol":1,"collection_only":false,"signed_attribution":true}'`, false},
		{"unsignedSelectors", `printf '%s' '{"protocol":1,"collection_only":true}'`, false},
		{"futureProtocol", `printf '%s' '{"protocol":2,"collection_only":true,"signed_attribution":true}'`, false},
		{"invalid", `printf '%s' '{"collection_only":true'`, false},
		{"oversize", `i=0; while [ "$i" -lt 5000 ]; do printf x; i=$((i+1)); done`, false},
		{"timeout", `exec /bin/sleep 10`, false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "native path with spaces")
			if err := os.WriteFile(path, []byte("#!/bin/sh\n"+test.script+"\n"), 0700); err != nil {
				t.Fatal(err)
			}
			err := nativeCollectionCapabilities(path)
			if (err == nil) != test.ok {
				t.Fatalf("expected supported=%v, error=%v", test.ok, err)
			}
			if err != nil && err.Error() != "aidr_enforcement_collection_unsupported" {
				t.Fatal(err)
			}
		})
	}
}

func TestCollectionProbeHonorsCancelledParent(t *testing.T) {
	root := t.TempDir()
	marker := filepath.Join(root, "should-not-execute")
	path := filepath.Join(root, "candidate")
	script := "#!/bin/sh\n/usr/bin/touch '" + marker + "'\n"
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if nativeCollectionCapabilitiesContext(ctx, path) == nil {
		t.Fatal("cancelled prerequisite inspection succeeded")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("candidate ran after parent cancellation")
	}
}
