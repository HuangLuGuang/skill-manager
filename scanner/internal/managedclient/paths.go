package managedclient

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
)

const (
	runtimeDirectoryName = ".agent-manager"
	dataDirectoryName    = ".river-security"
	dataProductName      = "agent-manager"
)

func RuntimeRoot(home string) string {
	return filepath.Join(home, runtimeDirectoryName)
}

func DataRoot(home string) string {
	return filepath.Join(home, dataDirectoryName, dataProductName)
}

func ManagedSkillsRoot(home string) string {
	return filepath.Join(DataRoot(home), "skills")
}

func PendingRoot(home string) string {
	return filepath.Join(DataRoot(home), "pending")
}

func QuarantineRoot(home string) string {
	return filepath.Join(DataRoot(home), "quarantine")
}

func BackupsRoot(home string) string {
	return filepath.Join(DataRoot(home), "backups")
}

func legacyContentRoot(home, name string) string {
	return filepath.Join(RuntimeRoot(home), name)
}

func managedSkillsRoots(home string) []string {
	return []string{ManagedSkillsRoot(home), legacyContentRoot(home, "skills")}
}

// EnsureDataLayout moves legacy content into the durable data directory and
// leaves compatibility links so existing Agent Skill links keep resolving.
func EnsureDataLayout(home string) error {
	if err := os.MkdirAll(RuntimeRoot(home), 0o700); err != nil {
		return err
	}
	if err := os.MkdirAll(DataRoot(home), 0o700); err != nil {
		return err
	}
	for _, name := range []string{"skills", "pending", "quarantine", "backups"} {
		if err := ensureContentDirectory(home, name); err != nil {
			return err
		}
	}
	return nil
}

func ensureContentDirectory(home, name string) error {
	legacy := legacyContentRoot(home, name)
	current := filepath.Join(DataRoot(home), name)
	legacyInfo, legacyErr := os.Lstat(legacy)
	currentInfo, currentErr := os.Lstat(current)

	if currentErr != nil && !errors.Is(currentErr, os.ErrNotExist) {
		return currentErr
	}
	if legacyErr != nil && !errors.Is(legacyErr, os.ErrNotExist) {
		return legacyErr
	}

	if currentErr != nil {
		if legacyErr == nil && legacyInfo.IsDir() && legacyInfo.Mode()&os.ModeSymlink == 0 && runtime.GOOS != "windows" {
			if err := os.Rename(legacy, current); err != nil {
				return err
			}
			legacyErr = os.ErrNotExist
		} else if err := os.MkdirAll(current, 0o700); err != nil {
			return err
		}
	} else if !currentInfo.IsDir() {
		return errors.New("Agent Manager 数据路径不是目录: " + current)
	}

	if runtime.GOOS == "windows" || legacyErr == nil {
		return nil
	}
	return os.Symlink(current, legacy)
}

func pathWithinLexical(path, root string) bool {
	relative, err := filepath.Rel(filepath.Clean(root), filepath.Clean(path))
	return err == nil && relative != ".." && !filepath.IsAbs(relative) && !hasParentPrefix(relative)
}

func hasParentPrefix(relative string) bool {
	return len(relative) > 3 && relative[:3] == ".."+string(filepath.Separator)
}
