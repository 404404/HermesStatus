package main

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var errUnsafeRuntimePath = errors.New("runtime path is invalid")

type openedPersistencePaths struct {
	primaryName string
	backupName  string
	directoryFD int
}

func (paths *openedPersistencePaths) close() {
	if paths != nil && paths.directoryFD >= 0 {
		_ = unix.Close(paths.directoryFD)
		paths.directoryFD = -1
	}
}

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

// openPersistencePaths is the single preflight used at startup and before
// every persistence write. It validates primary and backup unconditionally,
// even when the primary is already readable.
func openPersistencePaths(
	primaryPath string,
	backupPath string,
	probeWrite bool,
) (*openedPersistencePaths, error) {
	if !filepath.IsAbs(primaryPath) ||
		filepath.Clean(primaryPath) != primaryPath ||
		!filepath.IsAbs(backupPath) ||
		filepath.Clean(backupPath) != backupPath ||
		backupPath != primaryPath+"~" {
		return nil, errUnsafeRuntimePath
	}
	directory := filepath.Dir(primaryPath)
	if directory != filepath.Dir(backupPath) ||
		filepath.Base(primaryPath) == "." ||
		filepath.Base(primaryPath) == string(filepath.Separator) ||
		filepath.Base(primaryPath) == filepath.Base(backupPath) {
		return nil, errUnsafeRuntimePath
	}
	directoryFD, err := openDirectoryWithoutSymlinks(directory)
	if err != nil {
		return nil, err
	}
	paths := &openedPersistencePaths{
		primaryName: filepath.Base(primaryPath),
		backupName:  filepath.Base(backupPath),
		directoryFD: directoryFD,
	}
	primaryStat, err := paths.validateEntry(paths.primaryName)
	if err != nil {
		paths.close()
		return nil, err
	}
	backupStat, err := paths.validateEntry(paths.backupName)
	if err != nil {
		paths.close()
		return nil, err
	}
	if primaryStat != nil && backupStat != nil &&
		primaryStat.Dev == backupStat.Dev &&
		primaryStat.Ino == backupStat.Ino {
		paths.close()
		return nil, errUnsafeRuntimePath
	}
	if probeWrite {
		if err := paths.probeWritableDirectory(); err != nil {
			paths.close()
			return nil, err
		}
	}
	return paths, nil
}

func openDirectoryWithoutSymlinks(path string) (int, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return -1, errUnsafeRuntimePath
	}
	currentFD, err := unix.Open(
		string(filepath.Separator),
		unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC|unix.O_NOFOLLOW,
		0,
	)
	if err != nil {
		return -1, err
	}
	for _, component := range strings.Split(
		strings.TrimPrefix(path, string(filepath.Separator)),
		string(filepath.Separator),
	) {
		if component == "" {
			continue
		}
		nextFD, openErr := unix.Openat(
			currentFD,
			component,
			unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC|unix.O_NOFOLLOW,
			0,
		)
		_ = unix.Close(currentFD)
		if openErr != nil {
			return -1, openErr
		}
		currentFD = nextFD
	}
	return currentFD, nil
}

func (paths *openedPersistencePaths) validateEntry(name string) (*unix.Stat_t, error) {
	if name == "" || name == "." || name == ".." || filepath.Base(name) != name {
		return nil, errUnsafeRuntimePath
	}
	var linkStat unix.Stat_t
	if err := unix.Fstatat(
		paths.directoryFD,
		name,
		&linkStat,
		unix.AT_SYMLINK_NOFOLLOW,
	); err != nil {
		if errors.Is(err, unix.ENOENT) {
			return nil, nil
		}
		return nil, err
	}
	if linkStat.Mode&unix.S_IFMT != unix.S_IFREG {
		return nil, errUnsafeRuntimePath
	}
	if linkStat.Nlink != 1 {
		return nil, errUnsafeRuntimePath
	}
	if err := unix.Faccessat(
		paths.directoryFD,
		name,
		unix.R_OK|unix.W_OK,
		unix.AT_EACCESS,
	); err != nil {
		return nil, err
	}
	fileFD, err := unix.Openat(
		paths.directoryFD,
		name,
		unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW,
		0,
	)
	if err != nil {
		return nil, err
	}
	defer unix.Close(fileFD)
	var openedStat unix.Stat_t
	if err := unix.Fstat(fileFD, &openedStat); err != nil {
		return nil, err
	}
	if openedStat.Mode&unix.S_IFMT != unix.S_IFREG ||
		openedStat.Nlink != 1 ||
		openedStat.Dev != linkStat.Dev ||
		openedStat.Ino != linkStat.Ino {
		return nil, errUnsafeRuntimePath
	}
	return &openedStat, nil
}

func (paths *openedPersistencePaths) probeWritableDirectory() error {
	name, err := randomPersistenceName(".hermesstatus-preflight-", ".tmp")
	if err != nil {
		return err
	}
	fileFD, err := unix.Openat(
		paths.directoryFD,
		name,
		unix.O_WRONLY|unix.O_CREAT|unix.O_EXCL|unix.O_CLOEXEC|unix.O_NOFOLLOW,
		0o600,
	)
	if err != nil {
		return err
	}
	closeErr := unix.Close(fileFD)
	unlinkErr := unix.Unlinkat(paths.directoryFD, name, 0)
	if closeErr != nil {
		return closeErr
	}
	return unlinkErr
}

func randomPersistenceName(prefix, suffix string) (string, error) {
	var entropy [16]byte
	if _, err := rand.Read(entropy[:]); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(entropy[:]) + suffix, nil
}
