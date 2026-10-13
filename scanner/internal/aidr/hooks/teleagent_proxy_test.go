package hooks

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestTeleAgentDesktopPreservesSignedRequestAndPrivateHost(t *testing.T) {
	secret := strings.Repeat("a", 64)
	key := []byte("test-provider-key")
	sign := func(uri string) string {
		mac := hmac.New(sha256.New, key)
		mac.Write([]byte("POST\n" + uri))
		return hex.EncodeToString(mac.Sum(nil))
	}
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Header.Get("X-Test-Signature") != sign(r.RequestURI) {
			http.Error(w, "invalid signature", http.StatusUnauthorized)
			return
		}
		if strings.Contains(r.Host, secret[:32]) || r.Header.Get("X-Forwarded-Host") != "" {
			t.Error("private hostname reached upstream")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: signed-stream\n\n")
	}))
	defer upstream.Close()
	u, _ := url.Parse(upstream.URL + "/superCowork/sapi")
	h, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: "/unused", Secret: secret, Upstream: u, PreservePath: true})
	if err != nil {
		t.Fatal(err)
	}
	uri := "/superCowork/sapi/api/v1/chat%2Fcompletions?mode=a%2Fb"
	request := func(host, origin string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "http://"+host+uri, strings.NewReader(`{"stream":true}`))
		r.RemoteAddr = "127.0.0.1:1234"
		r.Header.Set("X-Test-Signature", sign(uri))
		r.Header.Set("Origin", origin)
		r.Header.Set("X-Forwarded-Host", host)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	w := request(teleAgentLocalHost(secret)+":12345", "")
	if w.Code != 200 || w.Body.String() != "data: signed-stream\n\n" || w.Header().Get("Content-Type") != "text/event-stream" {
		t.Fatalf("signed response: %d %s", w.Code, w.Body.String())
	}
	for _, input := range [][2]string{{"localhost:12345", ""}, {teleAgentLocalHost(secret) + ":12345", "https://example.com"}} {
		if w := request(input[0], input[1]); w.Code != http.StatusForbidden {
			t.Fatalf("unauthenticated request: %d", w.Code)
		}
	}
	if calls != 1 {
		t.Fatalf("unexpected upstream requests: %d", calls)
	}
}
