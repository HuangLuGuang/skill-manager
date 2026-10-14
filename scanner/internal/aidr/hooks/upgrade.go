package hooks

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"time"
)

const upgradeRequestWait = 8 * time.Second
const upgradeWindowLifetime = 30 * time.Second

type upgradeWindow struct {
	Started time.Time `json:"started"`
	Expires time.Time `json:"expires"`
}

// BeginReceiverUpgrade is called under the service reconciliation lock, before
// stopping the old worker. The private, expiring marker permits waiting only;
// it never supplies a decision or changes the signed policy.
func BeginReceiverUpgrade(socket string) (func(), error) {
	path := socket + ".upgrade.json"
	if ValidateBridgePrivateFile(path) != nil {
		return nil, code("aidr_hook_upgrade_window_failed")
	}
	now := time.Now().UTC()
	body, _ := json.Marshal(upgradeWindow{now, now.Add(upgradeWindowLifetime)})
	f, err := os.CreateTemp(filepath.Dir(path), ".hook-upgrade-")
	if err != nil {
		return nil, code("aidr_hook_upgrade_window_failed")
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, err = f.Write(body); err == nil {
		err = f.Sync()
	}
	if err == nil {
		err = f.Close()
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err != nil {
		return nil, code("aidr_hook_upgrade_window_failed")
	}
	return func() { _ = os.Remove(path) }, nil
}

func receiverUpgradeDeadline(socket string) time.Time {
	path := socket + ".upgrade.json"
	if ValidateBridgePrivateFile(path) != nil {
		return time.Time{}
	}
	f, err := os.Open(path)
	if err != nil {
		return time.Time{}
	}
	defer f.Close()
	var window upgradeWindow
	body, err := io.ReadAll(io.LimitReader(f, 513))
	now := time.Now()
	if err != nil || len(body) > 512 || json.Unmarshal(body, &window) != nil || window.Started.After(now) || !window.Expires.After(now) || window.Expires.Sub(window.Started) != upgradeWindowLifetime {
		return time.Time{}
	}
	return window.Expires
}

// ExchangeForHost retries only a failed dial: no request was sent. Once connected,
// lost responses, invalid peers/protocols and explicit decisions remain final.
// The same event identity is retained and caller cancellation always wins.
func ExchangeForHost(ctx context.Context, socket string, req IPCRequest, timeout time.Duration) (IPCResponse, error) {
	return exchangeForHost(ctx, socket, req, timeout, Exchange)
}

func exchangeForHost(ctx context.Context, socket string, req IPCRequest, timeout time.Duration, exchange func(context.Context, string, IPCRequest) (IPCResponse, error)) (IPCResponse, error) {
	started := time.Now()
	deadline := started.Add(timeout)
	for {
		if end := receiverUpgradeDeadline(socket); end.After(time.Now()) {
			limit := started.Add(upgradeRequestWait)
			if end.Before(limit) {
				limit = end
			}
			if limit.After(deadline) {
				deadline = limit
			}
		}
		attempt, cancel := context.WithDeadline(ctx, deadline)
		response, err := exchange(attempt, socket, req)
		cancel()
		if err == nil || err.Error() != "aidr_hook_receiver_unavailable" || ctx.Err() != nil || !deadline.After(time.Now()) || !receiverUpgradeDeadline(socket).After(time.Now()) {
			return response, err
		}
		timer := time.NewTimer(50 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return response, err
		case <-timer.C:
		}
	}
}
