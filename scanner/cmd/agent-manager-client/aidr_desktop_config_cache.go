package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"skill-manager/scanner/internal/aidr/privatefs"
	"sync"
)

var desktopConfigCache struct {
	sync.Mutex
	files map[string]desktopConfigFile
}

type desktopConfigFile struct {
	info os.FileInfo
	body []byte
}

func sameDesktopConfigFile(a, b os.FileInfo) bool {
	return a != nil && b != nil && os.SameFile(a, b) && a.Size() == b.Size() && a.Mode() == b.Mode() &&
		a.ModTime().Equal(b.ModTime()) && desktopConfigChangeTime(a) != 0 && desktopConfigChangeTime(a) == desktopConfigChangeTime(b)
}

func readDesktopConfigBytes(path string) ([]byte, error) {
	desktopConfigCache.Lock()
	defer desktopConfigCache.Unlock()
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || privatefs.SecureFile(path) != nil {
		delete(desktopConfigCache.files, path)
		return nil, errors.New("aidr_desktop_config_unreadable")
	}
	if saved, ok := desktopConfigCache.files[path]; ok && sameDesktopConfigFile(saved.info, info) {
		return saved.body, nil
	}
	delete(desktopConfigCache.files, path)
	f, err := openDesktopConfig(path)
	if err != nil {
		return nil, errors.New("aidr_desktop_config_unreadable")
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(info, opened) || !opened.Mode().IsRegular() || privatefs.Check(path) != nil {
		return nil, errors.New("aidr_desktop_config_unreadable")
	}
	body, err := io.ReadAll(io.LimitReader(f, 65537))
	if err != nil {
		return nil, errors.New("aidr_desktop_config_unreadable")
	}
	if len(body) > 65536 || !json.Valid(body) {
		return nil, errors.New("aidr_desktop_config_invalid")
	}
	after, err := os.Lstat(path)
	if err != nil || !os.SameFile(opened, after) || !after.Mode().IsRegular() || privatefs.Check(path) != nil {
		return nil, errors.New("aidr_desktop_config_unreadable")
	}
	if sameDesktopConfigFile(info, after) {
		if desktopConfigCache.files == nil || len(desktopConfigCache.files) >= 64 {
			desktopConfigCache.files = make(map[string]desktopConfigFile)
		}
		desktopConfigCache.files[path] = desktopConfigFile{after, body}
	}
	return body, nil
}
