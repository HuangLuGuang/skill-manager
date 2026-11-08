package privatefs

import (
	"strings"
	"testing"
)

func TestWindowsDriveSQLiteURI(t *testing.T) {
	u := SQLiteURI("C:/Users/QA Team/队列/hooks.db", "mode=ro")
	if !strings.HasPrefix(u, "file:///C:/Users/QA%20Team/") || !strings.HasSuffix(u, "/hooks.db?mode=ro") {
		t.Fatal(u)
	}
}
