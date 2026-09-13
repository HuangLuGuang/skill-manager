package managedclient

import (
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
