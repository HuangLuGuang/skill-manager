package managedclient

import (
	"net/url"
	"path/filepath"
)

func sqliteURI(path, query string) string {
	path = filepath.ToSlash(path)
	// A drive letter belongs in the URI path, not its authority (file://C:/).
	if len(path) >= 2 && path[1] == ':' {
		path = "/" + path
	}
	return (&url.URL{Scheme: "file", Path: path, RawQuery: query}).String()
}
