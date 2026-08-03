package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var errSecureDocumentUnavailable = errors.New("document unavailable")

// secureReadBoundedDocument is the single reader for startup-only Server
// configuration documents. Every pathname component is opened relative to a
// held directory descriptor; the final file is never reopened by pathname.
func secureReadBoundedDocument(path string, limit int64) ([]byte, error) {
	return secureReadBoundedDocumentWithHooks(path, limit, nil)
}

// secureDocumentOpenHooks is dependency injection for deterministic namespace
// replacement tests. Production callers always pass nil.
type secureDocumentOpenHooks struct {
	traversal      *securePathTraversalHooks
	beforeFileOpen func(parentFD int) error
	afterFileOpen  func(fileFD int) error
}

func secureReadBoundedDocumentWithHooks(
	path string,
	limit int64,
	hooks *secureDocumentOpenHooks,
) ([]byte, error) {
	if limit < 0 || !validSecureDocumentPath(path) {
		return nil, errSecureDocumentUnavailable
	}
	parentPath := filepath.Dir(path)
	var traversalHooks *securePathTraversalHooks
	if hooks != nil {
		traversalHooks = hooks.traversal
	}
	parentFD, err := openDirectoryWithoutSymlinksWithHooks(
		parentPath,
		traversalHooks,
	)
	if err != nil {
		return nil, secureDocumentError(err)
	}
	defer unix.Close(parentFD)

	if hooks != nil && hooks.beforeFileOpen != nil {
		if err := hooks.beforeFileOpen(parentFD); err != nil {
			return nil, errSecureDocumentUnavailable
		}
	}
	name := filepath.Base(path)
	fileFD, err := unix.Openat(
		parentFD,
		name,
		unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW|unix.O_NONBLOCK,
		0,
	)
	if err != nil {
		return nil, secureDocumentError(err)
	}
	if hooks != nil && hooks.afterFileOpen != nil {
		if err := hooks.afterFileOpen(fileFD); err != nil {
			_ = unix.Close(fileFD)
			return nil, errSecureDocumentUnavailable
		}
	}
	file := os.NewFile(uintptr(fileFD), "secure-runtime-document")
	if file == nil {
		_ = unix.Close(fileFD)
		return nil, errSecureDocumentUnavailable
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() ||
		info.Size() < 0 || info.Size() > limit {
		return nil, errSecureDocumentUnavailable
	}
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errSecureDocumentUnavailable
	}
	return data, nil
}

func validSecureDocumentPath(path string) bool {
	if path == "" || strings.ContainsRune(path, '\x00') ||
		!filepath.IsAbs(path) || filepath.Clean(path) != path ||
		path == string(filepath.Separator) {
		return false
	}
	trimmed := strings.TrimPrefix(path, string(filepath.Separator))
	if trimmed == "" {
		return false
	}
	for _, component := range strings.Split(trimmed, string(filepath.Separator)) {
		if component == "" || component == "." || component == ".." {
			return false
		}
	}
	name := filepath.Base(path)
	return name != "" && name != "." && name != ".."
}

func secureDocumentError(err error) error {
	switch {
	case errors.Is(err, unix.ENOENT):
		return os.ErrNotExist
	case errors.Is(err, unix.EACCES), errors.Is(err, unix.EPERM):
		return os.ErrPermission
	default:
		return errSecureDocumentUnavailable
	}
}
