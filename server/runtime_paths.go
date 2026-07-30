package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

var errUnsafeRuntimePath = errors.New("runtime path is invalid")

// resolveOptionsPaths fixes every mutable runtime path before the app starts.
// Relative paths are resolved against the configuration document directory,
// so a later working-directory change cannot redirect persistence.
func resolveOptionsPaths(opts Options) (Options, error) {
	configPath, err := filepath.Abs(opts.ConfigPath)
	if err != nil {
		return Options{}, errUnsafeRuntimePath
	}
	opts.ConfigPath = filepath.Clean(configPath)
	configDirectory := filepath.Dir(opts.ConfigPath)

	if opts.StatsPath == "" {
		opts.StatsPath = filepath.Join(opts.WebDir, "json", "stats.json")
	}
	opts.StatsPath, err = resolvePathFromDirectory(configDirectory, opts.StatsPath)
	if err != nil {
		return Options{}, errUnsafeRuntimePath
	}

	if opts.PersistencePath == "" {
		opts.PersistencePath = opts.StatsPath + ".state-v2"
	} else {
		if containsParentTraversal(opts.PersistencePath) {
			return Options{}, errUnsafeRuntimePath
		}
		opts.PersistencePath, err = resolvePathFromDirectory(
			configDirectory,
			opts.PersistencePath,
		)
		if err != nil {
			return Options{}, errUnsafeRuntimePath
		}
	}
	return opts, nil
}

func resolvePathFromDirectory(directory, path string) (string, error) {
	if path == "" {
		return "", errUnsafeRuntimePath
	}
	if !filepath.IsAbs(path) {
		path = filepath.Join(directory, path)
	}
	path = filepath.Clean(path)
	if !filepath.IsAbs(path) {
		return "", errUnsafeRuntimePath
	}
	return path, nil
}

func containsParentTraversal(path string) bool {
	for _, component := range strings.Split(filepath.ToSlash(path), "/") {
		if component == ".." {
			return true
		}
	}
	return false
}

// validateNoSymlinkComponents rejects an existing symlink at any component.
// Missing suffixes are allowed so a new private persistence directory can be
// created, then checked again immediately before the atomic write.
func validateNoSymlinkComponents(path string) error {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return errUnsafeRuntimePath
	}
	current := string(filepath.Separator)
	for _, component := range strings.Split(
		strings.TrimPrefix(path, string(filepath.Separator)),
		string(filepath.Separator),
	) {
		if component == "" {
			continue
		}
		current = filepath.Join(current, component)
		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		if err != nil {
			return errUnsafeRuntimePath
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errUnsafeRuntimePath
		}
	}
	return nil
}
