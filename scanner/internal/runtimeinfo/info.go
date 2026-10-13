// Package runtimeinfo identifies the executable loaded by this process.
package runtimeinfo

import (
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"sync"
	"time"
)

var Version = "dev"
var once sync.Once
var current Info

type Info struct {
	PID       int       `json:"pid"`
	Version   string    `json:"version"`
	SHA256    string    `json:"sha256"`
	StartedAt time.Time `json:"started_at"`
}

// Call before a mutable executable path can be staged over. Never infer a
// running version from the desktop version or a later read of that path.
func Current() Info {
	once.Do(func() {
		current = Info{PID: os.Getpid(), Version: Version, StartedAt: time.Now().UTC()}
		if path, err := os.Executable(); err == nil {
			current.SHA256, _ = Digest(path)
		}
	})
	return current
}
func Digest(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", h.Sum(nil)), nil
}
