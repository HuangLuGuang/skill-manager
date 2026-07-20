package managedclient

import (
	"archive/zip"
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestVerifyAndExtractPackageRejectsTampering(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	content := []byte("safe")
	sum := sha256.Sum256(content)
	manifest := map[string]any{
		"version":           1,
		"skill_id":          "skill-1",
		"name":              "safe-skill",
		"content_signature": "abc",
		"files":             []map[string]any{{"path": "SKILL.md", "size": len(content), "sha256": hex.EncodeToString(sum[:])}},
	}
	manifestBody, _ := json.Marshal(manifest)
	build := func(fileBody []byte) []byte {
		var body bytes.Buffer
		archive := zip.NewWriter(&body)
		writeZip(t, archive, "manifest.json", manifestBody)
		writeZip(t, archive, "manifest.sig", []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, manifestBody))))
		writeZip(t, archive, "skill/SKILL.md", fileBody)
		if err := archive.Close(); err != nil {
			t.Fatal(err)
		}
		return body.Bytes()
	}
	key := base64.StdEncoding.EncodeToString(publicKey)
	target := filepath.Join(t.TempDir(), "skill")
	if _, err := VerifyAndExtractPackage(build(content), key, target); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(target, "SKILL.md")); err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyAndExtractPackage(build([]byte("tampered")), key, target+"-bad"); err == nil {
		t.Fatal("tampered package was accepted")
	}
}

func TestSafePackagePathRejectsTraversal(t *testing.T) {
	for _, value := range []string{"../secret", "/absolute", ""} {
		if safePackagePath(value) {
			t.Fatalf("unsafe path accepted: %q", value)
		}
	}
	if !safePackagePath("references/usage.md") {
		t.Fatal("safe relative path was rejected")
	}
}

func writeZip(t *testing.T, archive *zip.Writer, name string, body []byte) {
	t.Helper()
	writer, err := archive.Create(name)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write(body); err != nil {
		t.Fatal(err)
	}
}
