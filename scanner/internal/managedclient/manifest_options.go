package managedclient

import "skill-manager/scanner/internal/manifest"

func DefaultManifestOptions() manifest.Options {
	return manifest.Options{
		IgnoreDirs:    map[string]bool{".git": true, ".venv": true, "node_modules": true, "__pycache__": true, "dist": true, "build": true, ".DS_Store": true},
		MaxFileBytes:  20 * 1024 * 1024,
		MaxTotalBytes: 100 * 1024 * 1024,
		MaxFiles:      20000,
	}
}
