//go:build darwin

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os/exec"
	"time"
)

type capabilityOutput struct {
	data bytes.Buffer
	max  int
}

func (w *capabilityOutput) Write(p []byte) (int, error) {
	limit := w.max
	if limit == 0 {
		limit = 4096
	}
	if len(p) > limit-w.data.Len() {
		return 0, io.ErrShortWrite
	}
	return w.data.Write(p)
}

// Probe the already validated native path without opening ES or a state store.
// A legacy binary must not silently start the control-enabled default mode.
func nativeCollectionCapabilities(path string) error {
	return nativeCollectionCapabilitiesContext(context.Background(), path)
}

func nativeCollectionCapabilitiesContext(parent context.Context, path string) error {
	ctx, cancel := context.WithTimeout(parent, 2*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, "--capabilities")
	cmd.WaitDelay = 250 * time.Millisecond
	cmd.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	output := &capabilityOutput{}
	cmd.Stdout = output
	cmd.Stderr = io.Discard
	if err := cmd.Run(); err != nil {
		return errors.New("aidr_enforcement_collection_unsupported")
	}
	var capabilities struct {
		Protocol          int  `json:"protocol"`
		CollectionOnly    bool `json:"collection_only"`
		SignedAttribution bool `json:"signed_attribution"`
	}
	if err := json.Unmarshal(output.data.Bytes(), &capabilities); err != nil || capabilities.Protocol != 1 || !capabilities.CollectionOnly || !capabilities.SignedAttribution {
		return errors.New("aidr_enforcement_collection_unsupported")
	}
	return nil
}
