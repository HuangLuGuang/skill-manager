package managedclient

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"sync"
	"time"
)

// ServeDesktop keeps UI reads independent of Hook admission and worker execution.
func ServeDesktop(ctx context.Context, home string) error {
	listener, cleanup, err := listenDesktop(home)
	if err != nil {
		return err
	}
	defer cleanup()
	return serveDesktop(ctx, home, listener)
}

func serveDesktop(ctx context.Context, home string, listener net.Listener) error {
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			listener.Close()
		case <-done:
		}
	}()
	var workers sync.WaitGroup
	defer workers.Wait()
	slots := make(chan struct{}, 4)
	platformSlots := make(chan struct{}, 2)
	for {
		conn, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		select {
		case slots <- struct{}{}:
		default:
			conn.Close()
			continue
		}
		workers.Add(1)
		go func() {
			defer workers.Done()
			defer func() { <-slots }()
			defer conn.Close()
			stop := context.AfterFunc(ctx, func() { conn.Close() })
			defer stop()
			conn.SetDeadline(time.Now().Add(5 * time.Second))
			var request DesktopRequest
			decoder := json.NewDecoder(io.LimitReader(conn, 16384))
			decoder.DisallowUnknownFields()
			if decoder.Decode(&request) != nil || request.Version != 1 {
				json.NewEncoder(conn).Encode(map[string]string{"error": "client_ipc_invalid_request"})
				return
			}
			if request.Method != "snapshot" {
				select {
				case platformSlots <- struct{}{}:
					defer func() { <-platformSlots }()
				default:
					json.NewEncoder(conn).Encode(map[string]string{"error": "client_ipc_busy"})
					return
				}
				conn.SetDeadline(time.Now().Add(35 * time.Second))
				requestCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
				defer cancel()
				result, err := DesktopPlatform(requestCtx, home, request)
				if err != nil {
					json.NewEncoder(conn).Encode(map[string]string{"error": err.Error()})
				} else {
					json.NewEncoder(conn).Encode(map[string]any{"result": result})
				}
				return
			}
			snapshot, err := DesktopSnapshot(ctx, home, request.Recovery)
			if err != nil {
				json.NewEncoder(conn).Encode(map[string]string{"error": "client_snapshot_unavailable"})
				return
			}
			json.NewEncoder(conn).Encode(snapshot)
		}()
	}
}
