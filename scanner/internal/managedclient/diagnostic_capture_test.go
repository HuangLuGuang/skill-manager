package managedclient

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestDiagnosticCaptureBoundsOutputAndMigratesLegacyLogs(t *testing.T) {
	if home := os.Getenv("AGENT_MANAGER_CAPTURE_TEST_HOME"); home != "" {
		stop, err := CaptureDaemonOutput(home)
		if err != nil {
			t.Fatal(err)
		}
		for i := 0; i < 100; i++ {
			fmt.Fprintln(os.Stderr, "library failure token=PRIVATE")
		}
		fmt.Fprintln(os.Stdout, strings.Repeat("x", 20000))
		stop()
		return
	}
	home := t.TempDir()
	root := filepath.Join(home, ".agent-manager")
	if err := os.MkdirAll(filepath.Join(root, "logs"), 0700); err != nil {
		t.Fatal(err)
	}
	legacy := filepath.Join(root, "logs", "client-error.log")
	if err := os.WriteFile(legacy, []byte("historical password=SECRET"), 0600); err != nil {
		t.Fatal(err)
	}
	keep := filepath.Join(root, "logs", "unrelated.txt")
	os.WriteFile(keep, []byte("keep"), 0600)
	cmd := exec.Command(os.Args[0], "-test.run=^TestDiagnosticCaptureBoundsOutputAndMigratesLegacyLogs$")
	cmd.Env = append(os.Environ(), "AGENT_MANAGER_CAPTURE_TEST_HOME="+home)
	if data, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, data)
	}
	if _, err := os.Stat(legacy); !os.IsNotExist(err) {
		t.Fatalf("legacy retained: %v", err)
	}
	if _, err := os.Stat(keep); err != nil {
		t.Fatal(err)
	}
	files, err := diagnosticFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]bool{}
	for _, file := range files {
		data, err := os.ReadFile(file.path)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(data), "PRIVATE") || strings.Contains(string(data), "SECRET") {
			t.Fatal("secret leaked")
		}
		for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
			var record DiagnosticRecord
			if err := json.Unmarshal([]byte(line), &record); err != nil {
				t.Fatal(err)
			}
			found[record.Event] = true
			if record.Event == "repeated_output" && record.Fields["count"] == float64(99) {
				found["repeat_count"] = true
			}
		}
	}
	for _, event := range []string{"output", "legacy_log_tail", "repeat_count"} {
		if !found[event] {
			t.Fatal(event, found)
		}
	}
}

func TestDiagnosticDesktopInputIsWhitelistedAndRedacted(t *testing.T) {
	home := t.TempDir()
	if err := RecordDesktopDiagnostic(home, []byte(`{"event":"script_error","message":"token=PRIVATE","version":"dev","count":2,"payload":"SHOULD_NOT_EXPORT"}`)); err != nil {
		t.Fatal(err)
	}
	files, err := diagnosticFiles(filepath.Join(home, ".agent-manager"))
	if err != nil || len(files) != 1 {
		t.Fatal(err, files)
	}
	data, err := os.ReadFile(files[0].path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "PRIVATE") || strings.Contains(string(data), "SHOULD_NOT_EXPORT") {
		t.Fatal("unexpected input persisted")
	}
	if err := RecordDesktopDiagnostic(home, []byte(`{"event":"arbitrary"}`)); err == nil {
		t.Fatal("unsupported event accepted")
	}
}

func TestDiagnosticDesktopStateMetadataIsPersisted(t *testing.T) {
	home := t.TempDir()
	err := RecordDesktopDiagnostic(home, []byte(`{"event":"desktop_snapshot_refreshed","revision":"42","event_type":"pending_status_changed","active_panel":"discover","duration_ms":18,"outcome":"succeeded","partitions":["local_snapshot","pending"]}`))
	if err != nil {
		t.Fatal(err)
	}
	files, err := diagnosticFiles(filepath.Join(home, ".agent-manager"))
	if err != nil || len(files) != 1 {
		t.Fatal(err, files)
	}
	body, err := os.ReadFile(files[0].path)
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{"desktop_snapshot_refreshed", "pending_status_changed", "discover", "local_snapshot", "18"} {
		if !strings.Contains(string(body), value) {
			t.Fatalf("metadata %q missing: %s", value, body)
		}
	}
}

func TestDiagnosticPathOpenResultIsPersisted(t *testing.T) {
	home := t.TempDir()
	for _, record := range []string{
		`{"event":"path_open_finished","path":"C:\\Users\\用户\\Skill 目录","outcome":"accepted","duration_ms":12,"count":1}`,
		`{"event":"path_open_finished","path":"C:\\Users\\用户\\Skill 目录","outcome":"failed","error_code":"folder_open_shell_failed","message":"ShellExecuteW 5 token=PRIVATE","payload":"SHOULD_NOT_EXPORT","count":1}`,
	} {
		if err := RecordDesktopDiagnostic(home, []byte(record)); err != nil {
			t.Fatal(err)
		}
	}
	files, err := diagnosticFiles(filepath.Join(home, ".agent-manager"))
	if err != nil || len(files) != 1 {
		t.Fatal(err, files)
	}
	body, err := os.ReadFile(files[0].path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(body), "PRIVATE") || strings.Contains(string(body), "SHOULD_NOT_EXPORT") {
		t.Fatal("unexpected input persisted")
	}
	lines := bytes.Split(bytes.TrimSpace(body), []byte("\n"))
	if len(lines) != 2 {
		t.Fatalf("expected two operation results, got %d", len(lines))
	}
	for i, line := range lines {
		var record DiagnosticRecord
		if err := json.Unmarshal(line, &record); err != nil {
			t.Fatal(err)
		}
		if record.Event != "path_open_finished" || record.Fields["path"] != `C:\Users\用户\Skill 目录` {
			t.Fatalf("path open metadata missing: %s", line)
		}
		if i == 0 && (record.Level != "info" || record.Fields["outcome"] != "accepted") {
			t.Fatalf("accepted request recorded incorrectly: %s", line)
		}
		if i == 1 && (record.Level != "error" || record.Fields["error_code"] != "folder_open_shell_failed") {
			t.Fatalf("failure evidence missing: %s", line)
		}
	}
}
