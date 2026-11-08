package agentlog

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestWindowsZcodeReadsLiveWAL(t *testing.T) {
	testMutableSQLiteParts(t, "zcode", "db.sqlite")
}

func TestWindowsCodeBuddyStableReadWithoutCacheStamp(t *testing.T) {
	source := codeBuddyFixture(t)
	raw, info, err := codeBuddyReadFile(source.Path, 1<<20)
	if err != nil || len(raw) == 0 {
		t.Fatalf("stable index rejected: %v", err)
	}
	current, err := os.Stat(source.Path)
	if err != nil || !sameLogReadVersion(info, current) || sameLogFileVersion(info, current) {
		t.Fatal("read stability and cache eligibility must differ on Windows", err)
	}
	batch, err := ReadWithPolicy(context.Background(), source, Cursor{}, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy())
	if err != nil || len(batch.Events) == 0 || !batch.Cursor.ScanComplete {
		t.Fatalf("snapshot not collected: %v %+v", err, batch.Coverage)
	}
}
