package managedclient

import (
	"archive/zip"
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type releaseFile struct {
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type releaseManifest struct {
	Version            int           `json:"version"`
	SkillID            string        `json:"skill_id"`
	VersionID          string        `json:"version_id"`
	VersionNo          int           `json:"version_no"`
	SourceVersion      string        `json:"source_version,omitempty"`
	ContentFingerprint string        `json:"content_fingerprint,omitempty"`
	Name               string        `json:"name"`
	ContentSignature   string        `json:"content_signature"`
	Files              []releaseFile `json:"files"`
}

func VerifyAndExtractPackage(body []byte, publicKeyBase64, target string) (releaseManifest, error) {
	var manifest releaseManifest
	reader, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
	if err != nil {
		return manifest, err
	}
	files := map[string]*zip.File{}
	for _, file := range reader.File {
		files[file.Name] = file
	}
	manifestFile, ok := files["manifest.json"]
	if !ok {
		return manifest, fmt.Errorf("package missing manifest.json")
	}
	manifestBody, err := readZipFile(manifestFile)
	if err != nil {
		return manifest, err
	}
	signatureFile, ok := files["manifest.sig"]
	if !ok {
		return manifest, fmt.Errorf("package missing manifest.sig")
	}
	signatureBody, err := readZipFile(signatureFile)
	if err != nil {
		return manifest, err
	}
	publicKey, err := base64.StdEncoding.DecodeString(publicKeyBase64)
	if err != nil || len(publicKey) != ed25519.PublicKeySize {
		return manifest, fmt.Errorf("invalid release public key")
	}
	signature, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(signatureBody)))
	if err != nil || !ed25519.Verify(publicKey, manifestBody, signature) {
		return manifest, fmt.Errorf("release signature verification failed")
	}
	if err := json.Unmarshal(manifestBody, &manifest); err != nil {
		return manifest, err
	}
	if !validInstallComponent(manifest.SkillID) || !validInstallComponent(manifest.Name) ||
		(manifest.VersionID != "" && !validInstallComponent(manifest.VersionID)) {
		return manifest, fmt.Errorf("invalid release identifier")
	}
	tmp := target + ".tmp"
	_ = os.RemoveAll(tmp)
	if err := os.MkdirAll(tmp, 0o755); err != nil {
		return manifest, err
	}
	for _, item := range manifest.Files {
		if !safePackagePath(item.Path) {
			_ = os.RemoveAll(tmp)
			return manifest, fmt.Errorf("unsafe package path %q", item.Path)
		}
		file, ok := files["skill/"+item.Path]
		if !ok {
			_ = os.RemoveAll(tmp)
			return manifest, fmt.Errorf("package missing %s", item.Path)
		}
		data, err := readZipFile(file)
		if err != nil {
			_ = os.RemoveAll(tmp)
			return manifest, err
		}
		sum := sha256.Sum256(data)
		if int64(len(data)) != item.Size || hex.EncodeToString(sum[:]) != item.SHA256 {
			_ = os.RemoveAll(tmp)
			return manifest, fmt.Errorf("package file verification failed: %s", item.Path)
		}
		path := filepath.Join(tmp, filepath.FromSlash(item.Path))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			_ = os.RemoveAll(tmp)
			return manifest, err
		}
		if err := os.WriteFile(path, data, 0o644); err != nil {
			_ = os.RemoveAll(tmp)
			return manifest, err
		}
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return manifest, err
	}
	old := target + ".old"
	_ = os.RemoveAll(old)
	if _, err := os.Stat(target); err == nil {
		if err := os.Rename(target, old); err != nil {
			return manifest, err
		}
	}
	if err := os.Rename(tmp, target); err != nil {
		_ = os.Rename(old, target)
		return manifest, err
	}
	_ = os.RemoveAll(old)
	return manifest, nil
}

func readZipFile(file *zip.File) ([]byte, error) {
	reader, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return io.ReadAll(io.LimitReader(reader, 100*1024*1024))
}

func safePackagePath(value string) bool {
	clean := filepath.Clean(filepath.FromSlash(value))
	return value != "" && !filepath.IsAbs(clean) && clean != ".." && !strings.HasPrefix(clean, ".."+string(filepath.Separator))
}
