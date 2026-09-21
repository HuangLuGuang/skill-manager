package managedclient

import (
	"context"
	"testing"
)

func TestModelProbeRejectsEchoedPromptAndErrorExitPayload(t *testing.T) {
	marker := "AM_VERIFY_12345678-1234-1234-1234-123456789abc"
	output := `{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"` + marker + `"}]}}` + "\n" + `{"type":"message_end","message":{"role":"assistant","stopReason":"error","content":[]}}`
	if modelProbeHasAnswer("pi", []byte(output), marker) {
		t.Fatal("echoed user marker is not an answer")
	}
	output = `{"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"` + marker + `"}]}}`
	if !modelProbeHasAnswer("pi", []byte(output), marker) {
		t.Fatal("assistant answer missing")
	}
	if !modelProbeHasAnswer("gemini", []byte("Warning: no color\n"+`{"response":"`+marker+`"}`), marker) {
		t.Fatal("warning must not hide valid JSON result")
	}
}

func TestHermesModelProbeAcceptsExactMarkerOnFirstOrLaterLine(t *testing.T) {
	marker := "AM_VERIFY_12345678-1234-1234-1234-123456789abc"
	for _, output := range []string{marker + "\n", "Hermes response:\n  " + marker + "  \n"} {
		if !modelProbeHasAnswer("hermes", []byte(output), marker) {
			t.Fatalf("exact Hermes marker was not recognized in %q", output)
		}
	}
	if modelProbeHasAnswer("hermes", []byte("Reply with exactly "+marker), marker) {
		t.Fatal("Hermes prompt echo must not be accepted as the answer")
	}
}

func TestMissingAgentVerificationPersistsFailureAndKeepsRecovery(t *testing.T) {
	home := t.TempDir()
	if err := ApplyModelConfig(home, "https://gateway.example", "codex", "codex", "model", "test-key"); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", "")
	if _, err := VerifyModelConfig(context.Background(), home, "codex", "codex", API{}, Inventory{}); err == nil {
		t.Fatal("missing executable must fail")
	}
	state := InspectModelConfig(home, "codex")
	if state.Status != "failed" || state.Error != "model_config.agent_missing" || !state.CanRestore {
		t.Fatalf("missing executable failure was not recorded: %+v", state)
	}
}
