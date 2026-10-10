package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Recovery includes ignored directories and links, so its budget is separate
// from the smaller manifest used for Skill classification and packaging.
const recoveryCopyMaxBytes int64 = 1 << 30
const recoveryCopyMaxEntries = 100000

// Recovery integrity covers directory structure, modes and link text as well
// as regular-file contents. The scan manifest intentionally excludes links and
// ignored directories and cannot establish that a backup is complete.
func recoveryTreeDigest(root string) (string, error) {
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", err
	}
	h := sha256.New()
	enc := json.NewEncoder(h)
	remaining := recoveryCopyMaxBytes
	entries := 0
	err = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		entries++
		if entries > recoveryCopyMaxEntries {
			return fmt.Errorf("skill_copy_limit_exceeded")
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		value := ""
		switch {
		case info.Mode()&os.ModeSymlink != 0:
			value, err = os.Readlink(path)
		case info.IsDir():
		case info.Mode().IsRegular():
			if info.Size() > remaining {
				return fmt.Errorf("skill_copy_limit_exceeded")
			}
			file, e := os.Open(path)
			if e != nil {
				return e
			}
			content := sha256.New()
			var size int64
			size, err = io.Copy(content, io.LimitReader(file, remaining+1))
			file.Close()
			if size > remaining {
				return fmt.Errorf("skill_copy_limit_exceeded")
			}
			remaining -= size
			value = hex.EncodeToString(content.Sum(nil))
		default:
			return fmt.Errorf("skill_copy_type_unsupported")
		}
		if err != nil {
			return err
		}
		return enc.Encode([]any{rel, uint32(info.Mode()), value})
	})
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func copyRecoveryTree(source, target string) error {
	before, err := recoveryTreeDigest(source)
	if err != nil {
		return err
	}
	if err := copyDir(source, target); err != nil {
		return err
	}
	for _, path := range []string{source, target} {
		after, err := recoveryTreeDigest(path)
		if err != nil {
			return err
		}
		if after != before {
			return fmt.Errorf("skill_content_changed")
		}
	}
	return nil
}

// Only call for a newly owned copy. Copied read-only directory modes must not
// prevent removal of an abandoned staging tree; symlink targets stay untouched.
func removeOwnedCopy(root string) error {
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			info, err := entry.Info()
			if err != nil {
				return err
			}
			return os.Chmod(path, info.Mode().Perm()|0700)
		}
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	return os.RemoveAll(root)
}
