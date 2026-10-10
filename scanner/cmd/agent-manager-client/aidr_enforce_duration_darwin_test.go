package main

import (
	"context"
	"testing"
	"time"
)

func TestContinuousCollectionRunsUntilOwnerCancels(t *testing.T) {
	ctx, cancel := enforcementRunContext(context.Background(), 0)
	if _, bounded := ctx.Deadline(); bounded {
		t.Fatal("continuous run has a deadline")
	}
	cancel()
	if ctx.Err() != context.Canceled {
		t.Fatal("owner cancellation must stop collection")
	}
	ctx, cancel = enforcementRunContext(context.Background(), time.Minute)
	defer cancel()
	if _, bounded := ctx.Deadline(); !bounded {
		t.Fatal("explicit bounded CLI run lost deadline")
	}
}
