package agentlog

import (
	"strings"
	"testing"

	"skill-manager/scanner/internal/aidr/privatefs"
)

func TestWindowsLogUserScopeMatchesHookIdentity(t *testing.T) {
	want, err := privatefs.UserSID()
	if err != nil {
		t.Fatal(err)
	}
	if got := sourceUserScope(); !strings.HasPrefix(got, "S-1-") || got != want {
		t.Fatalf("log user scope %q differs from Hook identity %q", got, want)
	}
}
