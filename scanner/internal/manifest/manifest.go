package manifest

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type FileEntry struct {
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type Manifest struct {
	Name        string      `json:"name"`
	Description string      `json:"description,omitempty"`
	Root        string      `json:"root"`
	Fingerprint string      `json:"fingerprint"`
	Files       []FileEntry `json:"files"`
	TotalBytes  int64       `json:"total_bytes"`
}

type Options struct {
	IgnoreDirs    map[string]bool
	MaxFileBytes  int64
	MaxTotalBytes int64
	MaxFiles      int
}

func Build(root string, opts Options) (Manifest, error) {
	var result Manifest
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return result, err
	}
	result.Root = absRoot
	name, description := parseSkillMetadata(filepath.Join(absRoot, "SKILL.md"))
	result.Name = name
	result.Description = description

	err = filepath.WalkDir(absRoot, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == absRoot {
			return nil
		}
		if entry.IsDir() {
			if opts.IgnoreDirs[entry.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return nil
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		if opts.MaxFileBytes > 0 && info.Size() > opts.MaxFileBytes {
			return fmt.Errorf("file too large: %s (%d bytes)", path, info.Size())
		}
		if opts.MaxFiles > 0 && len(result.Files) >= opts.MaxFiles {
			return fmt.Errorf("too many files under skill: %s", absRoot)
		}
		rel, err := safeRel(absRoot, path)
		if err != nil {
			return err
		}
		hash, err := fileSHA256(path)
		if err != nil {
			return err
		}
		result.TotalBytes += info.Size()
		if opts.MaxTotalBytes > 0 && result.TotalBytes > opts.MaxTotalBytes {
			return fmt.Errorf("skill package too large: %s (%d bytes)", absRoot, result.TotalBytes)
		}
		result.Files = append(result.Files, FileEntry{
			Path:   rel,
			Size:   info.Size(),
			SHA256: hash,
		})
		return nil
	})
	if err != nil {
		return result, err
	}
	sort.Slice(result.Files, func(i, j int) bool {
		return result.Files[i].Path < result.Files[j].Path
	})
	result.Fingerprint = fingerprint(result.Files)
	if result.Name == "" {
		result.Name = filepath.Base(absRoot)
	}
	return result, nil
}

func safeRel(root string, path string) (string, error) {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return "", err
	}
	if rel == "." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || rel == ".." || filepath.IsAbs(rel) {
		return "", fmt.Errorf("path escapes skill root: %s", path)
	}
	return filepath.ToSlash(rel), nil
}

func fileSHA256(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func ContentSignature(files []FileEntry) string {
	hash := sha256.New()
	for _, file := range files {
		io.WriteString(hash, file.Path+":"+file.SHA256+"\n")
	}
	return hex.EncodeToString(hash.Sum(nil))
}

func fingerprint(files []FileEntry) string {
	hash := sha256.New()
	for _, file := range files {
		io.WriteString(hash, file.Path)
		hash.Write([]byte{0})
		io.WriteString(hash, strconv.FormatInt(file.Size, 10))
		hash.Write([]byte{0})
		io.WriteString(hash, file.SHA256)
		hash.Write([]byte{0})
	}
	return "sha256:" + hex.EncodeToString(hash.Sum(nil))
}

func parseSkillMetadata(path string) (string, string) {
	file, err := os.Open(path)
	if err != nil {
		return "", ""
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	if !scanner.Scan() || strings.TrimSpace(scanner.Text()) != "---" {
		return "", ""
	}
	var name string
	var description string
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "---" {
			break
		}
		if strings.HasPrefix(line, "name:") && name == "" {
			name = cleanValue(strings.TrimSpace(strings.TrimPrefix(line, "name:")))
		}
		if strings.HasPrefix(line, "description:") && description == "" {
			description = cleanValue(strings.TrimSpace(strings.TrimPrefix(line, "description:")))
		}
	}
	return name, description
}

func ReadSkillMetadata(root string) (string, string) {
	return parseSkillMetadata(filepath.Join(root, "SKILL.md"))
}

func cleanValue(value string) string {
	value = strings.TrimSpace(value)
	value = strings.Trim(value, "\"'")
	return value
}
