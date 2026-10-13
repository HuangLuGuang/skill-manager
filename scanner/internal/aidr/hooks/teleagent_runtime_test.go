package hooks

import (
	"context"
	"io"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestProxyDrainPreservesStreamAndResumesAccepts(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	release := make(chan struct{})
	started := make(chan struct{})
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/stream" {
			w.Write([]byte("first\n"))
			w.(http.Flusher).Flush()
			close(started)
			<-release
			w.Write([]byte("last\n"))
			return
		}
		w.Write([]byte("ready"))
	})
	server := &http.Server{Handler: handler}
	go server.Serve(l)
	client := &http.Client{Timeout: 3 * time.Second}
	defer client.CloseIdleConnections()
	resp, err := client.Get("http://" + l.Addr().String() + "/stream")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	<-started
	next, drained, err := drainProxy(server, l)
	if err != nil || drained {
		t.Fatalf("drain %v %v", drained, err)
	}
	replacement := &http.Server{Handler: handler}
	go replacement.Serve(next)
	defer replacement.Close()
	r, err := client.Get("http://" + next.Addr().String() + "/ready")
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	close(release)
	body, err := io.ReadAll(resp.Body)
	if err != nil || string(body) != "first\nlast\n" {
		t.Fatalf("stream interrupted: %q %v", body, err)
	}
	if err = server.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	// A second handoff retains the same port, including queued new connections.
	held, drained, err := drainProxy(replacement, next)
	if err != nil || !drained {
		t.Fatalf("idle drain %v %v", drained, err)
	}
	done := make(chan error, 1)
	go func() {
		r, e := client.Get("http://" + held.Addr().String() + "/ready")
		if e == nil {
			defer r.Body.Close()
			b, _ := io.ReadAll(r.Body)
			if strings.TrimSpace(string(b)) != "ready" {
				e = io.ErrUnexpectedEOF
			}
		}
		done <- e
	}()
	time.Sleep(30 * time.Millisecond)
	final := &http.Server{Handler: handler}
	go final.Serve(held)
	defer final.Close()
	if err = <-done; err != nil {
		t.Fatal(err)
	}
}
