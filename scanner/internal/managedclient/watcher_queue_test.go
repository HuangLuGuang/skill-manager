package managedclient

import (
	"fmt"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestSkillWatcherIgnoresAncestorWritesButRepairsStructure(t *testing.T) {
	parent := filepath.Join(t.TempDir(), ".agent-manager")
	root := filepath.Join(parent, "skills")
	w := &SkillWatcher{roots: map[string]bool{root: true}}
	if w.relevant(parent, false) {
		t.Fatal("runtime parent writes must not trigger skill discovery")
	}
	if !w.relevant(parent, true) {
		t.Fatal("ancestor replacement must repair watches")
	}
	for _, path := range []string{root, filepath.Join(root, "demo", "SKILL.md")} {
		if !w.relevant(path, false) {
			t.Fatalf("skill write was filtered: %s", path)
		}
	}
	if w.relevant(filepath.Join(parent, "state.db"), true) {
		t.Fatal("unrelated runtime file became a skill change")
	}
}

func TestSkillChangesRetainPathsDuringSlowScan(t *testing.T) {
	queue := make(chan []string, 1)
	for i := 0; i < 100; i++ {
		queueSkillChanges(queue, []string{"a/SKILL.md", "b/SKILL.md"})
	}
	if got := <-queue; !reflect.DeepEqual(got, []string{"a/SKILL.md", "b/SKILL.md"}) {
		t.Fatalf("backpressure lost paths: %v", got)
	}
	queueSkillChanges(queue, []string{"a"})
	queueSkillChanges(queue, nil)
	queueSkillChanges(queue, []string{"b"})
	if got := <-queue; len(got) != 0 {
		t.Fatalf("coverage loss must retain compensation: %v", got)
	}
	paths := make([]string, 4096)
	for i := range paths {
		paths[i] = fmt.Sprint(i)
	}
	queueSkillChanges(queue, paths)
	queueSkillChanges(queue, []string{"overflow"})
	if got := <-queue; len(got) != 0 {
		t.Fatal("overflow must request compensation")
	}
	queueSkillChanges(queue, []string{"after-scan"})
	if got := <-queue; !reflect.DeepEqual(got, []string{"after-scan"}) {
		t.Fatalf("paths did not resume after compensation: %v", got)
	}
}

func TestCompensationCoalescesWithoutPostponingScan(t *testing.T) {
	now := time.Now()
	due := now.Add(5 * time.Minute)
	for i := 0; i < 50; i++ {
		due = compensationDue(now.Add(time.Duration(i)*100*time.Millisecond), now, due, 5*time.Minute)
	}
	if !due.Equal(now.Add(5 * time.Second)) {
		t.Fatalf("burst postponed or immediately repeated scan: %v", due.Sub(now))
	}
	if got := compensationDue(now, now, now.Add(time.Second), time.Second); !got.Equal(now.Add(time.Second)) {
		t.Fatal("compensation delayed scheduled patrol")
	}
	if got := compensationDue(now.Add(time.Minute), now, now.Add(5*time.Minute), 5*time.Minute); !got.Equal(now.Add(time.Minute)) {
		t.Fatal("isolated change after cooldown should scan immediately")
	}
}
