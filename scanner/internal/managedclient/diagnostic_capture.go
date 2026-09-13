package managedclient

import (
	"bufio"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// CaptureDaemonOutput routes library output through the same bounded log writer.
// Call once in the standalone daemon process, before starting its goroutines.
func CaptureDaemonOutput(home string) (func(), error) {
	root := filepath.Join(home, ".agent-manager")
	reader, writer, err := os.Pipe()
	if err != nil {
		return nil, err
	}
	restore, err := redirectDiagnosticOutput(writer)
	if err != nil {
		reader.Close()
		writer.Close()
		return nil, err
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer reader.Close()
		input := bufio.NewReaderSize(reader, 4096)
		var previous string
		var repeats int
		var mu sync.Mutex
		flush := func() {
			if repeats > 0 {
				_ = writeDiagnostic(root, DiagnosticRecord{Level: "warning", Module: "daemon_output", Event: "repeated_output", Fields: map[string]any{"message": previous, "count": repeats}})
				repeats = 0
			}
		}
		ticker := time.NewTicker(time.Minute)
		defer ticker.Stop()
		go func() {
			for {
				select {
				case <-done:
					return
				case <-ticker.C:
					mu.Lock()
					flush()
					mu.Unlock()
				}
			}
		}()
		for {
			line, e := input.ReadSlice('\n')
			message := redactDiagnostic(strings.TrimSpace(string(line)))
			mu.Lock()
			if message != "" {
				if message == previous {
					repeats++
				} else {
					flush()
					_ = writeDiagnostic(root, DiagnosticRecord{Level: "warning", Module: "daemon_output", Event: "output", Fields: map[string]any{"message": message}})
					previous = message
				}
			}
			if e != nil && e != bufio.ErrBufferFull {
				flush()
				mu.Unlock()
				return
			}
			mu.Unlock()
		}
	}()
	// The old launchd file descriptors have now been redirected. Preserve a
	// bounded tail in structured diagnostics before removing those known files.
	for _, name := range []string{"client.log", "client-error.log"} {
		path := filepath.Join(root, "logs", name)
		info, e := os.Lstat(path)
		if e != nil || !info.Mode().IsRegular() {
			continue
		}
		file, e := os.Open(path)
		if e != nil {
			continue
		}
		start := info.Size() - 4096
		if start < 0 {
			start = 0
		}
		_, e = file.Seek(start, io.SeekStart)
		var tail []byte
		if e == nil {
			tail, e = io.ReadAll(io.LimitReader(file, 4096))
		}
		file.Close()
		if e != nil {
			continue
		}
		if len(tail) > 0 {
			e = writeDiagnostic(root, DiagnosticRecord{Level: "info", Module: "daemon_output", Event: "legacy_log_tail", Fields: map[string]any{"file": name, "original_bytes": info.Size(), "modified_at": info.ModTime().Format("2006-01-02T15:04:05.000Z07:00"), "tail": string(tail)}})
		}
		if e == nil {
			_ = os.Remove(path)
		}
	}
	return func() { restore(); writer.Close(); <-done }, nil
}
