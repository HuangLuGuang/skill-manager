package main

import (
	"encoding/json"
	"path/filepath"
	"testing"
)

func TestWindowsStatusReplacementWhileReaderOpen(t *testing.T) {
	path := filepath.Join(t.TempDir(), "log-status.json")
	if err := writeDesktopJSON(path, map[string]int{"revision": 1}); err != nil {
		t.Fatal(err)
	}
	reader, err := openDesktopConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	if err := writeDesktopJSON(path, map[string]int{"revision": 2}); err != nil {
		t.Fatal("status writer blocked by observer", err)
	}
	var old map[string]int
	if err := json.NewDecoder(reader).Decode(&old); err != nil || old["revision"] != 1 {
		t.Fatal(old, err)
	}
	current, err := openDesktopConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	defer current.Close()
	var next map[string]int
	if err := json.NewDecoder(current).Decode(&next); err != nil || next["revision"] != 2 {
		t.Fatal(next, err)
	}
}
