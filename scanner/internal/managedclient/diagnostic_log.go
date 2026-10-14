package managedclient

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const diagnosticMaxBytes int64 = 200 * 1024 * 1024
const diagnosticFileBytes int64 = 10 * 1024 * 1024

type LogSettings struct {
	RetentionDays int   `json:"retention_days"`
	UsedBytes     int64 `json:"used_bytes"`
	MaxBytes      int64 `json:"max_bytes"`
}

type DiagnosticRecord struct {
	Time    string         `json:"time"`
	Level   string         `json:"level"`
	Module  string         `json:"module"`
	Event   string         `json:"event"`
	Version string         `json:"version"`
	PID     int            `json:"pid"`
	Fields  map[string]any `json:"fields,omitempty"`
}

var secretAssignment = regexp.MustCompile(`(?i)(["']?(?:authorization|token|api[_-]?key|password|secret|client[_-]?secret|private[_-]?key|cookie|access[_-]?token)["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&]+)`)
var bearerSecret = regexp.MustCompile(`(?i)(bearer|basic)\s+[^\s"',;]+`)
var privateKeyBlock = regexp.MustCompile(`(?s)-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----`)
var urlCredentials = regexp.MustCompile(`(https?://)[^/@\s]+:[^/@\s]+@`)

func redactDiagnostic(text string) string {
	text = privateKeyBlock.ReplaceAllString(text, "[REDACTED PRIVATE KEY]")
	text = bearerSecret.ReplaceAllString(text, "${1} [REDACTED]")
	text = secretAssignment.ReplaceAllString(text, "${1}[REDACTED]")
	return urlCredentials.ReplaceAllString(text, "${1}[REDACTED]@")
}

func safeDiagnosticValue(key string, value any) any {
	normalized := strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(key, "_", ""), "-", ""))
	if strings.Contains(normalized, "token") || strings.Contains(normalized, "password") || strings.Contains(normalized, "secret") || strings.Contains(normalized, "authorization") || strings.Contains(normalized, "apikey") || strings.Contains(normalized, "privatekey") || strings.Contains(normalized, "cookie") {
		return "[REDACTED]"
	}
	switch v := value.(type) {
	case map[string]any:
		result := map[string]any{}
		for k, item := range v {
			result[k] = safeDiagnosticValue(k, item)
		}
		return result
	case []any:
		result := make([]any, len(v))
		for i, item := range v {
			result[i] = safeDiagnosticValue("", item)
		}
		return result
	case string:
		s := redactDiagnostic(v)
		if len(s) > 4096 {
			s = s[:4096] + "…"
		}
		return s
	default:
		return value
	}
}

func logRoot(root string) string { return filepath.Join(root, "logs", "diagnostics") }

func diagnosticSanitizer(root string) func(any) (any, error) {
	tokens := []string{os.Getenv("AGENT_MANAGER_CLIENT_TOKEN")}
	if file, e := os.Open(filepath.Join(root, "config.json")); e == nil {
		var config struct {
			Token       string            `json:"token"`
			Connections []SavedConnection `json:"connections"`
		}
		if json.NewDecoder(io.LimitReader(file, 1024*1024)).Decode(&config) == nil {
			tokens = append(tokens, config.Token)
			for _, connection := range config.Connections {
				tokens = append(tokens, connection.Token)
			}
		}
		file.Close()
	}
	sort.SliceStable(tokens, func(i, j int) bool { return len(tokens[i]) > len(tokens[j]) })
	var replace func(any) any
	replace = func(item any) any {
		switch v := item.(type) {
		case map[string]any:
			for key, child := range v {
				v[key] = replace(child)
			}
			return v
		case []any:
			for i, child := range v {
				v[i] = replace(child)
			}
			return v
		case string:
			for _, token := range tokens {
				if token != "" {
					v = strings.ReplaceAll(v, token, "[REDACTED]")
				}
			}
			return v
		default:
			return item
		}
	}
	return func(value any) (any, error) {
		data, err := json.Marshal(value)
		if err != nil {
			return nil, err
		}
		var generic any
		if err = json.Unmarshal(data, &generic); err != nil {
			return nil, err
		}
		return safeDiagnosticValue("", replace(generic)), nil
	}
}

func ReadLogSettings(root string) (LogSettings, error) {
	settings := LogSettings{RetentionDays: 7, MaxBytes: diagnosticMaxBytes}
	body, err := os.ReadFile(filepath.Join(root, "log-settings.json"))
	if err == nil {
		var saved LogSettings
		if err = json.Unmarshal(body, &saved); err != nil {
			return settings, err
		}
		if !validRetention(saved.RetentionDays) {
			return settings, fmt.Errorf("diagnostics_invalid_retention")
		}
		settings.RetentionDays = saved.RetentionDays
	} else if !os.IsNotExist(err) {
		return settings, err
	}
	entries, err := os.ReadDir(logRoot(root))
	if os.IsNotExist(err) {
		return settings, nil
	}
	if err != nil {
		return settings, err
	}
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".jsonl") {
			info, e := entry.Info()
			if e != nil {
				return settings, e
			}
			if info.Mode().IsRegular() {
				settings.UsedBytes += info.Size()
			}
		}
	}
	return settings, nil
}
func validRetention(days int) bool {
	return days == 1 || days == 3 || days == 7 || days == 14 || days == 30
}

func SaveLogSettings(root string, days int) (LogSettings, error) {
	if !validRetention(days) {
		return LogSettings{}, fmt.Errorf("diagnostics_invalid_retention")
	}
	unlock, err := lockDiagnostics(root)
	if err != nil {
		return LogSettings{}, err
	}
	defer unlock()
	body, _ := json.Marshal(LogSettings{RetentionDays: days})
	tmp, err := os.CreateTemp(root, ".log-settings-")
	if err != nil {
		return LogSettings{}, err
	}
	defer os.Remove(tmp.Name())
	if _, err = tmp.Write(body); err != nil {
		tmp.Close()
		return LogSettings{}, err
	}
	if err = tmp.Close(); err != nil {
		return LogSettings{}, err
	}
	if err = os.Rename(tmp.Name(), filepath.Join(root, "log-settings.json")); err != nil {
		return LogSettings{}, err
	}
	if err = pruneDiagnosticLogs(root, time.Now(), days, 0, diagnosticMaxBytes); err != nil {
		return LogSettings{}, err
	}
	return ReadLogSettings(root)
}

type diagnosticFile struct {
	path     string
	size     int64
	modified time.Time
}

func diagnosticFiles(root string) ([]diagnosticFile, error) {
	entries, err := os.ReadDir(logRoot(root))
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	files := []diagnosticFile{}
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".jsonl") {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			return nil, err
		}
		if !info.Mode().IsRegular() {
			continue
		}
		files = append(files, diagnosticFile{filepath.Join(logRoot(root), entry.Name()), info.Size(), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool {
		if files[i].modified.Equal(files[j].modified) {
			return files[i].path < files[j].path
		}
		return files[i].modified.Before(files[j].modified)
	})
	return files, nil
}
func pruneDiagnosticLogs(root string, now time.Time, days int, incoming, maxBytes int64) error {
	files, err := diagnosticFiles(root)
	if err != nil {
		return err
	}
	var total int64
	for _, file := range files {
		total += file.size
	}
	for _, file := range files {
		if now.Sub(file.modified) > time.Duration(days)*24*time.Hour || total+incoming > maxBytes {
			if err := os.Remove(file.path); err != nil {
				return err
			}
			total -= file.size
		}
	}
	return nil
}

func writeDiagnostic(root string, record DiagnosticRecord) error {
	unlock, err := lockDiagnostics(root)
	if err != nil {
		return err
	}
	defer unlock()
	settings, err := ReadLogSettings(root)
	if err != nil {
		return err
	}
	now := time.Now()
	record.Time = now.Format("2006-01-02T15:04:05.000Z07:00")
	record.Version = Version
	record.PID = os.Getpid()
	if record.Fields != nil {
		fields, e := diagnosticSanitizer(root)(record.Fields)
		if e != nil {
			return e
		}
		record.Fields = fields.(map[string]any)
	}
	body, err := json.Marshal(record)
	if err != nil {
		return err
	}
	body = append(body, '\n')
	if len(body) > 64*1024 {
		return fmt.Errorf("diagnostics_record_too_large")
	}
	if err = pruneDiagnosticLogs(root, now, settings.RetentionDays, int64(len(body)), diagnosticMaxBytes); err != nil {
		return err
	}
	files, err := diagnosticFiles(root)
	if err != nil {
		return err
	}
	path := ""
	if len(files) > 0 {
		last := files[len(files)-1]
		if last.size+int64(len(body)) <= diagnosticFileBytes && last.modified.Format("2006-01-02") == now.Format("2006-01-02") {
			path = last.path
		}
	}
	var file *os.File
	if path == "" {
		file, err = os.CreateTemp(logRoot(root), now.Format("20060102T150405")+"-*.jsonl")
	} else {
		file, err = os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0600)
	}
	if err != nil {
		return err
	}
	_, err = file.Write(body)
	closeErr := file.Close()
	if err != nil {
		return err
	}
	return closeErr
}

// LogDiagnostic never replaces a business error with a logging failure.
func (store *Store) LogDiagnostic(level, module, event string, fields map[string]any) {
	if err := writeDiagnostic(store.root, DiagnosticRecord{Level: level, Module: module, Event: event, Fields: fields}); err != nil {
		_ = store.SetState("diagnostics:write_error", redactDiagnostic(err.Error()))
	}
}

type syncDiagnosticFailure struct {
	message     string
	first, last time.Time
	count       int
}

var syncDiagnosticMu sync.Mutex
var syncDiagnosticFailures = map[string]syncDiagnosticFailure{}

func logSyncTransition(store *Store, kind string, err error, contextFields ...map[string]any) {
	recordSyncTransition(store.root, store.LogDiagnostic, kind, err, contextFields...)
}

// RecordBackgroundSyncDiagnostic also serves workers that own a separate queue
// and must not acquire the managed client database's writer lock.
func RecordBackgroundSyncDiagnostic(home, kind string, err error, fields map[string]any) {
	root := filepath.Join(home, ".agent-manager")
	recordSyncTransition(root, func(level, module, event string, fields map[string]any) {
		_ = writeDiagnostic(root, DiagnosticRecord{Level: level, Module: module, Event: event, Fields: fields})
	}, kind, err, fields)
}

func recordSyncTransition(root string, record func(string, string, string, map[string]any), kind string, err error, contextFields ...map[string]any) {
	syncDiagnosticMu.Lock()
	defer syncDiagnosticMu.Unlock()
	key := root + ":" + kind
	previous, exists := syncDiagnosticFailures[key]
	now := time.Now()
	if err == nil {
		if exists {
			record("info", kind, "sync_recovered", map[string]any{"first_failed_at": previous.first.Format(time.RFC3339Nano), "failure_count": previous.count, "duration_ms": now.Sub(previous.first).Milliseconds()})
			delete(syncDiagnosticFailures, key)
		}
		return
	}
	message := redactDiagnostic(err.Error())
	if !exists || previous.message != message {
		if exists {
			record("warning", kind, "sync_error_summary", map[string]any{"error": previous.message, "count": previous.count, "first_failed_at": previous.first.Format(time.RFC3339Nano)})
		}
		previous = syncDiagnosticFailure{message: message, first: now, last: now, count: 1}
		fields := map[string]any{"error": message}
		if len(contextFields) > 0 {
			for key, value := range contextFields[0] {
				fields[key] = value
			}
		}
		record("error", kind, "sync_failed", fields)
	} else {
		previous.count++
		if now.Sub(previous.last) >= time.Minute {
			record("warning", kind, "sync_error_summary", map[string]any{"error": message, "count": previous.count, "first_failed_at": previous.first.Format(time.RFC3339Nano), "duration_ms": now.Sub(previous.first).Milliseconds()})
			previous.last = now
		}
	}
	syncDiagnosticFailures[key] = previous
}

func RecordCommandDiagnostic(home, command string, started time.Time, err error) {
	if command == "record-desktop-diagnostic" {
		return
	}
	readonly := map[string]bool{"local-status": true, "cached-inventory": true, "inventory": true, "service-status": true, "log-settings": true, "pending": true, "refresh-pending": true, "scan-history": true, "refresh-scan-history": true, "quarantine": true, "available-skills": true, "agent-settings": true, "backups": true}
	if err == nil && readonly[command] {
		return
	}
	fields := map[string]any{"command": command, "duration_ms": time.Since(started).Milliseconds(), "status": "succeeded"}
	level := "info"
	if err != nil {
		level = "error"
		fields["status"] = "failed"
		fields["error"] = err.Error()
		if errors.Is(err, ErrSkillActionBusy) || strings.Contains(err.Error(), ErrSkillActionBusy.Error()) {
			addMutationLockDiagnostic(filepath.Join(home, ".agent-manager", "mutation.lock"), fields)
		}
	}
	_ = writeDiagnostic(filepath.Join(home, ".agent-manager"), DiagnosticRecord{Level: level, Module: "command", Event: "completed", Fields: fields})
}

func addMutationLockDiagnostic(path string, fields map[string]any) {
	info, err := os.Stat(path)
	if err != nil {
		return
	}
	fields["lock_modified_at"] = info.ModTime().Format(time.RFC3339Nano)
	fields["lock_age_ms"] = time.Since(info.ModTime()).Milliseconds()
	body, err := os.ReadFile(path)
	if err != nil || len(body) > 64 {
		return
	}
	if pid, err := strconv.Atoi(strings.TrimPrefix(strings.TrimSpace(string(body)), "v2 ")); err == nil && pid > 0 {
		fields["lock_owner_pid"] = pid
	}
}

// RecordDesktopDiagnostic accepts only diagnostic metadata; command arguments,
// configuration and application content are not part of this input contract.
func RecordDesktopDiagnostic(home string, data []byte) error {
	var input struct {
		Event       string   `json:"event"`
		Message     string   `json:"message"`
		Count       int      `json:"count"`
		FirstAt     string   `json:"first_at"`
		Version     string   `json:"version"`
		Revision    any      `json:"revision"`
		EventType   string   `json:"event_type"`
		ActivePanel string   `json:"active_panel"`
		DurationMS  int64    `json:"duration_ms"`
		Outcome     string   `json:"outcome"`
		ErrorCode   string   `json:"error_code"`
		Path        string   `json:"path"`
		Partitions  []string `json:"partitions"`
	}
	if err := json.Unmarshal(data, &input); err != nil {
		return fmt.Errorf("diagnostics_invalid_record")
	}
	allowedEvents := map[string]bool{
		"script_error": true, "unhandled_rejection": true, "started": true,
		"desktop_state_event_received": true, "desktop_snapshot_refreshed": true,
		"desktop_snapshot_refresh_failed": true, "platform_event_ignored": true,
		"path_open_finished": true,
	}
	if !allowedEvents[input.Event] {
		return fmt.Errorf("diagnostics_invalid_record")
	}
	level := "info"
	if input.Event == "script_error" || input.Event == "unhandled_rejection" || input.Event == "desktop_snapshot_refresh_failed" {
		level = "error"
	}
	if input.Event == "started" {
		level = "info"
	}
	if input.Event == "path_open_finished" && input.Outcome == "failed" {
		level = "error"
	}
	fields := map[string]any{"message": input.Message, "count": input.Count, "first_at": input.FirstAt, "desktop_version": input.Version}
	if input.Revision != nil {
		fields["revision"] = input.Revision
	}
	if input.EventType != "" {
		fields["event_type"] = input.EventType
	}
	if input.ActivePanel != "" {
		fields["active_panel"] = input.ActivePanel
	}
	if input.DurationMS > 0 || input.Event == "path_open_finished" {
		fields["duration_ms"] = input.DurationMS
	}
	if input.Outcome != "" {
		fields["outcome"] = input.Outcome
	}
	if input.ErrorCode != "" {
		fields["error_code"] = input.ErrorCode
	}
	if input.Event == "path_open_finished" && input.Path != "" {
		fields["path"] = input.Path
	}
	if input.Partitions != nil {
		fields["partitions"] = input.Partitions
	}
	return writeDiagnostic(filepath.Join(home, ".agent-manager"), DiagnosticRecord{Level: level, Module: "desktop", Event: input.Event, Fields: fields})
}
