package main

import (
	"bytes"
	"context"
	"crypto/elliptic"
	"errors"
	"os"
	"path/filepath"
	"time"

	"skill-manager/scanner/internal/aidr/upload"
	"skill-manager/scanner/internal/managedclient"
)

func prepareHookControlKey(ctx context.Context, cfg managedclient.Config, paths desktopPaths, pinned string) (string, error) {
	c, err := upload.New(upload.Options{Server: cfg.Server, ClientID: paths.Device, Token: cfg.Token})
	if err != nil {
		return "", err
	}
	defer c.Close()
	bounded, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	key, err := c.HookControlKey(bounded)
	if err != nil {
		return "", err
	}
	previouslyPinned := pinned != ""
	if pinned == "" {
		pinned = filepath.Join(paths.Root, "hook-policy-key.bin")
	}
	if !filepath.IsAbs(pinned) {
		return "", errors.New("aidr_hook_control_key_invalid")
	}
	prior, err := os.ReadFile(pinned)
	if err == nil {
		if !bytes.Equal(prior, key) {
			return "", errors.New("aidr_hook_control_key_changed")
		}
		return pinned, nil
	}
	if previouslyPinned || !os.IsNotExist(err) {
		return "", errors.New("aidr_hook_control_key_invalid")
	}
	x, _ := elliptic.Unmarshal(elliptic.P256(), key)
	if x == nil {
		return "", errors.New("aidr_hook_control_key_invalid")
	}
	if err = os.MkdirAll(paths.Root, 0700); err != nil {
		return "", err
	}
	f, err := os.OpenFile(pinned, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", err
	}
	_, err = f.Write(key)
	closeErr := f.Close()
	if err != nil {
		return "", err
	}
	return pinned, closeErr
}
