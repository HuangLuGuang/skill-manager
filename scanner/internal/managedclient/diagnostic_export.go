package managedclient

import (
	"archive/zip"
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// ExportDiagnostics exports current local evidence without including Skill source,
// credentials, or raw database files. It is also available when offline.
func (store *Store) ExportDiagnostics(outputDir string, days int) (string, error) {
	settings, err := ReadLogSettings(store.root)
	if err != nil {
		return "", err
	}
	if days < 1 || days > settings.RetentionDays {
		return "", fmt.Errorf("diagnostics_invalid_range")
	}
	if err = os.MkdirAll(outputDir, 0700); err != nil {
		return "", err
	}
	file, err := os.CreateTemp(outputDir, "agent-manager-diagnostics-"+time.Now().Format("20060102-150405")+"-*.zip")
	if err != nil {
		return "", err
	}
	path := file.Name()
	complete := false
	defer func() {
		file.Close()
		if !complete {
			os.Remove(path)
		}
	}()
	writer := zip.NewWriter(file)
	defer writer.Close()
	failures := []string{}
	sanitize := diagnosticSanitizer(store.root)
	writeJSON := func(name string, value any) error {
		generic, err := sanitize(value)
		if err != nil {
			return err
		}
		data, err := json.MarshalIndent(generic, "", "  ")
		if err != nil {
			return err
		}
		if len(data) > 10*1024*1024 {
			return fmt.Errorf("diagnostics_section_too_large")
		}
		entry, err := writer.Create(name)
		if err != nil {
			return err
		}
		_, err = entry.Write(data)
		return err
	}
	summary := map[string]any{"generated_at": time.Now().Format(time.RFC3339Nano), "exporter_version": Version, "os": runtime.GOOS, "arch": runtime.GOARCH, "days": days, "log_settings": settings}
	if raw, ok, e := store.State("diagnostics:daemon"); e == nil && ok {
		var daemon map[string]any
		if e = json.Unmarshal([]byte(raw), &daemon); e == nil {
			summary["last_daemon_session"] = daemon
		} else {
			failures = append(failures, "daemon_session: "+e.Error())
		}
	}
	if raw, ok, e := store.State("diagnostics:write_error"); e == nil && ok && raw != "" {
		summary["last_log_write_error"] = raw
	}
	if status, e := store.LocalStatus(); e == nil {
		summary["runtime"] = status
	} else {
		failures = append(failures, "runtime: "+e.Error())
	}
	if raw, ok, e := store.State("policy"); e == nil && ok {
		var p Policy
		if json.Unmarshal([]byte(raw), &p) == nil {
			summary["policy"] = map[string]any{"mode": p.Mode, "classification": p.Classification, "full_scan_seconds": p.FullScanSeconds}
		}
	}
	if raw, ok, e := store.State("inventory"); e == nil && ok {
		var inv Inventory
		if json.Unmarshal([]byte(raw), &inv) == nil {
			agents := []any{}
			for _, a := range inv.Agents {
				agents = append(agents, map[string]any{"agent_type": a.AgentType, "skills_path": a.SkillsPath, "skills": a.Skills})
			}
			summary["inventory"] = map[string]any{"client_id": inv.ClientID, "agents": agents}
		}
	}
	// Raw task payloads can contain model credentials. Keep only diagnostic fields.
	if status, ok := summary["runtime"].(LocalStatus); ok {
		status.Tasks = nil
		status.Notifications = nil
		summary["runtime"] = status
	}
	tasks, e := store.TaskHistory(500)
	if e != nil {
		failures = append(failures, "tasks: "+e.Error())
	} else {
		rows := []any{}
		for _, task := range tasks {
			rows = append(rows, map[string]any{"task_id": task.ID, "task_type": task.TaskType, "status": task.Status, "error": task.Error, "updated_at": task.UpdatedAt})
		}
		summary["tasks"] = rows
	}
	if recovery, e := store.QuarantineItems(); e == nil {
		summary["recovery"] = recovery
	} else {
		failures = append(failures, "recovery: "+e.Error())
	}
	if pending, e := store.PendingItems(); e == nil {
		summary["pending"] = pending
	} else {
		failures = append(failures, "pending: "+e.Error())
	}
	if history, e := store.ScanHistory(); e == nil {
		summary["scan_history"] = history
	} else {
		failures = append(failures, "scan_history: "+e.Error())
	}
	if queued, e := store.QueuedEvents(); e == nil {
		rows := []any{}
		for _, event := range queued {
			rows = append(rows, map[string]any{"event_id": event.ID, "created_at": event.CreatedAt, "client_id": event.ClientID, "event": event.EventType, "agent_type": event.AgentType, "skill_name": event.SkillName, "details": event.Details})
		}
		summary["queued_events"] = rows
	} else {
		failures = append(failures, "queued_events: "+e.Error())
	}
	if err = writeJSON("summary.json", summary); err != nil {
		return "", err
	}
	unlock, err := lockDiagnostics(store.root)
	if err != nil {
		return "", err
	}
	files, err := diagnosticFiles(store.root)
	unlock()
	if err != nil {
		return "", err
	}
	cutoff := time.Now().Add(-time.Duration(days) * 24 * time.Hour)
	entry, err := writer.Create("runtime.jsonl")
	if err != nil {
		return "", err
	}
	var copied int64
	for _, source := range files {
		if source.modified.Before(cutoff) {
			continue
		}
		// Copy at most one rotated file while holding the writer lock. Parsing
		// and ZIP compression happen after releasing it so exports don't stall logs.
		data, e := readDiagnosticSnapshot(store.root, source.path)
		if e != nil {
			failures = append(failures, "log: "+e.Error())
			continue
		}
		scanner := bufio.NewScanner(bytes.NewReader(data))
		scanner.Buffer(make([]byte, 4096), 64*1024+1)
		for scanner.Scan() {
			line := scanner.Bytes()
			var record DiagnosticRecord
			if json.Unmarshal(line, &record) != nil {
				failures = append(failures, "invalid_log_record")
				continue
			}
			at, e := time.Parse(time.RFC3339Nano, record.Time)
			if e != nil || at.Before(cutoff) {
				continue
			}
			fields, e := sanitize(record.Fields)
			if e != nil {
				return "", e
			}
			record.Fields, _ = fields.(map[string]any)
			clean, e := json.Marshal(record)
			if e != nil {
				return "", e
			}
			safe := string(clean)
			if copied+int64(len(safe)+1) > diagnosticMaxBytes {
				failures = append(failures, "log_export_size_limit")
				break
			}
			if _, e = fmt.Fprintln(entry, safe); e != nil {
				return "", e
			}
			copied += int64(len(safe) + 1)
		}
		if e = scanner.Err(); e != nil {
			failures = append(failures, "log: "+e.Error())
		}
	}
	if err = writeJSON("manifest.json", map[string]any{"schema_version": 1, "collected_at": time.Now().Format(time.RFC3339Nano), "log_bytes": copied, "collection_errors": failures, "notes": []string{"Times include their UTC offset. Runtime state is a fresh local snapshot; it may differ from the platform while offline.", "Retention applies to diagnostic logs only. No credentials, raw databases or Skill source files are included.", "Task history is limited to the latest 500 records."}}); err != nil {
		return "", err
	}
	if err = writer.Close(); err != nil {
		return "", err
	}
	if err = file.Close(); err != nil {
		return "", err
	}
	complete = true
	return filepath.Clean(strings.TrimSpace(path)), nil
}

func readDiagnosticSnapshot(root, path string) ([]byte, error) {
	unlock, err := lockDiagnostics(root)
	if err != nil {
		return nil, err
	}
	defer unlock()
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > diagnosticFileBytes {
		return nil, fmt.Errorf("diagnostics_invalid_log_file")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(io.LimitReader(file, diagnosticFileBytes))
}
