package main

import (
	"bytes"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"testing"

	"golang.org/x/sys/unix"
)

func TestSecureDocumentReaderAcceptsBoundedRegularFiles(t *testing.T) {
	root := t.TempDir()
	nested := filepath.Join(root, "managed", "documents")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(nested, "registry.json")
	want := []byte(`{"version":1}`)
	if err := os.WriteFile(path, want, 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := secureReadBoundedDocument(path, int64(len(want)))
	if err != nil || !bytes.Equal(got, want) {
		t.Fatalf("bounded regular document failed: %q err=%v", got, err)
	}

	empty := filepath.Join(nested, "empty.json")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	got, err = secureReadBoundedDocument(empty, 0)
	if err != nil || len(got) != 0 {
		t.Fatalf("empty bounded document failed: %q err=%v", got, err)
	}

	if err := os.WriteFile(path, append(want, 'x'), 0o600); err != nil {
		t.Fatal(err)
	}
	if got, err := secureReadBoundedDocument(path, int64(len(want))); err == nil ||
		got != nil {
		t.Fatalf("oversized document was accepted: %q", got)
	}
}

func TestSecureDocumentReaderRejectsUnsafePathsAndObjects(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target.json")
	if err := os.WriteFile(target, []byte(`{"safe":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	finalLink := filepath.Join(root, "final-link.json")
	if err := os.Symlink(target, finalLink); err != nil {
		t.Fatal(err)
	}
	dangling := filepath.Join(root, "dangling.json")
	if err := os.Symlink(filepath.Join(root, "missing.json"), dangling); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, "directory.json")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	fifo := filepath.Join(root, "fifo.json")
	if err := unix.Mkfifo(fifo, 0o600); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(root, "socket.json")
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()

	realParent := filepath.Join(root, "real-parent")
	if err := os.Mkdir(realParent, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(
		filepath.Join(realParent, "nested.json"),
		[]byte(`{"safe":true}`),
		0o600,
	); err != nil {
		t.Fatal(err)
	}
	linkedParent := filepath.Join(root, "linked-parent")
	if err := os.Symlink(realParent, linkedParent); err != nil {
		t.Fatal(err)
	}

	for name, path := range map[string]string{
		"empty":                "",
		"relative":             "relative.json",
		"root":                 string(filepath.Separator),
		"parent-traversal":     filepath.Join(root, "real-parent") + "/../target.json",
		"repeated-separator":   root + "//target.json",
		"final-symlink":        finalLink,
		"dangling-symlink":     dangling,
		"directory":            directory,
		"fifo":                 fifo,
		"socket":               socketPath,
		"character-device":     "/dev/null",
		"intermediate-symlink": filepath.Join(linkedParent, "nested.json"),
		"nul":                  target + "\x00suffix",
	} {
		t.Run(name, func(t *testing.T) {
			data, err := secureReadBoundedDocument(path, maxRuntimeConfigBytes)
			if err == nil || data != nil {
				t.Fatalf("unsafe document was accepted: %q", data)
			}
			if path != "" && bytes.Contains([]byte(err.Error()), []byte(path)) {
				t.Fatalf("error leaked document path: %v", err)
			}
		})
	}
}

func TestSecureDocumentReaderHoldsDirectoryAcrossParentReplacement(t *testing.T) {
	root := t.TempDir()
	parent := filepath.Join(root, "managed")
	moved := filepath.Join(root, "managed-held")
	attacker := filepath.Join(root, "attacker")
	if err := os.Mkdir(parent, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(attacker, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(parent, "registry.json")
	if err := os.WriteFile(path, []byte(`{"source":"trusted"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(
		filepath.Join(attacker, "registry.json"),
		[]byte(`{"source":"attacker"}`),
		0o600,
	); err != nil {
		t.Fatal(err)
	}

	hooks := &secureDocumentOpenHooks{
		beforeFileOpen: func(_ int) error {
			if err := os.Rename(parent, moved); err != nil {
				return err
			}
			return os.Symlink(attacker, parent)
		},
	}
	data, err := secureReadBoundedDocumentWithHooks(
		path,
		maxRuntimeConfigBytes,
		hooks,
	)
	if err != nil || string(data) != `{"source":"trusted"}` {
		t.Fatalf("parent replacement redirected read: %q err=%v", data, err)
	}
	if bytes.Contains(data, []byte("attacker")) {
		t.Fatal("attacker document was returned")
	}
}

func TestSecureDocumentReaderHoldsIntermediateDirectoryDuringReplacement(t *testing.T) {
	root := t.TempDir()
	trusted := filepath.Join(root, "trusted")
	nested := filepath.Join(trusted, "nested")
	moved := filepath.Join(root, "trusted-held")
	attacker := filepath.Join(root, "attacker")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(attacker, "nested"), 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(nested, "mapping.json")
	if err := os.WriteFile(path, []byte(`{"source":"trusted"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(
		filepath.Join(attacker, "nested", "mapping.json"),
		[]byte(`{"source":"attacker"}`),
		0o600,
	); err != nil {
		t.Fatal(err)
	}
	replaced := false
	hooks := &secureDocumentOpenHooks{
		traversal: &securePathTraversalHooks{
			afterDirectoryOpen: func(_ int, component string, _ int) error {
				if component != "trusted" || replaced {
					return nil
				}
				replaced = true
				if err := os.Rename(trusted, moved); err != nil {
					return err
				}
				return os.Symlink(attacker, trusted)
			},
		},
	}
	data, err := secureReadBoundedDocumentWithHooks(
		path,
		maxRuntimeConfigBytes,
		hooks,
	)
	if err != nil || string(data) != `{"source":"trusted"}` {
		t.Fatalf("intermediate replacement redirected read: %q err=%v", data, err)
	}
}

func TestSecureDocumentReaderUsesOpenedFileAfterUnlink(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "config.json")
	if err := os.WriteFile(path, []byte(`{"opened":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	hooks := &secureDocumentOpenHooks{
		afterFileOpen: func(_ int) error {
			return os.Remove(path)
		},
	}
	data, err := secureReadBoundedDocumentWithHooks(
		path,
		maxRuntimeConfigBytes,
		hooks,
	)
	if err != nil || string(data) != `{"opened":true}` {
		t.Fatalf("opened descriptor was not used after unlink: %q err=%v", data, err)
	}
}

func TestSecureDocumentReaderConcurrentUseDoesNotLeakDescriptors(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("descriptor accounting requires Linux /proc")
	}
	root := t.TempDir()
	path := filepath.Join(root, "config.json")
	if err := os.WriteFile(path, []byte(`{"version":1}`), 0o600); err != nil {
		t.Fatal(err)
	}
	oversized := filepath.Join(root, "oversized.json")
	if err := os.WriteFile(
		oversized,
		bytes.Repeat([]byte("x"), maxRuntimeConfigBytes+1),
		0o600,
	); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, "directory.json")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	before := countOpenDescriptors(t)
	const workers = 16
	const iterations = 100
	var wait sync.WaitGroup
	errorsChannel := make(chan error, workers)
	for worker := 0; worker < workers; worker++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			for index := 0; index < iterations; index++ {
				if _, err := secureReadBoundedDocument(
					path,
					maxRuntimeConfigBytes,
				); err != nil {
					errorsChannel <- err
					return
				}
				_, _ = secureReadBoundedDocument(
					filepath.Join(root, fmt.Sprintf("missing-%d", index)),
					maxRuntimeConfigBytes,
				)
				_, _ = secureReadBoundedDocument(
					oversized,
					maxRuntimeConfigBytes,
				)
				_, _ = secureReadBoundedDocument(
					directory,
					maxRuntimeConfigBytes,
				)
			}
		}()
	}
	wait.Wait()
	close(errorsChannel)
	for err := range errorsChannel {
		t.Fatal(err)
	}
	after := countOpenDescriptors(t)
	if after > before+4 {
		t.Fatalf("secure document reads leaked descriptors: before=%d after=%d", before, after)
	}
}

func TestUnsafeConfiguredDocumentPreventsAppCreationAndStateWrites(t *testing.T) {
	for _, document := range []string{"config", "registry", "mapping"} {
		t.Run(document, func(t *testing.T) {
			root := t.TempDir()
			managed := filepath.Join(root, "managed")
			if err := os.Mkdir(managed, 0o700); err != nil {
				t.Fatal(err)
			}
			configPath := filepath.Join(managed, "config.json")
			registryPath := filepath.Join(managed, "registry.json")
			mappingPath := filepath.Join(managed, "mapping.json")
			writeJSONTestFile(t, configPath, minimalTestConfig())
			writeJSONTestFile(t, registryPath, testRegistry(
				testRegistryDevice(
					"device-alpha",
					"Alpha",
					10,
					true,
					"legacy",
					nil,
				),
			))
			writeJSONTestFile(
				t,
				mappingPath,
				struct {
					Version int `json:"version"`
				}{Version: 1},
			)
			linked := filepath.Join(root, "linked")
			if err := os.Symlink(managed, linked); err != nil {
				t.Fatal(err)
			}
			switch document {
			case "config":
				configPath = filepath.Join(linked, "config.json")
			case "registry":
				registryPath = filepath.Join(linked, "registry.json")
			case "mapping":
				mappingPath = filepath.Join(linked, "mapping.json")
			}
			statsPath := filepath.Join(root, "stats.json")
			statePath := filepath.Join(root, "state-v2.json")
			app, err := NewApp(Options{
				ConfigPath: configPath, StatsPath: statsPath,
				PersistencePath: statePath, RegistryPath: registryPath,
				LegacyMappingPath: mappingPath, WebDir: root,
				HTTPAddr: "127.0.0.1:0", AgentAddr: "127.0.0.1:0",
			})
			if err == nil || app != nil {
				if app != nil {
					app.Close()
				}
				t.Fatalf(
					"unsafe %s path did not fail startup: app=%#v err=%v",
					document,
					app,
					err,
				)
			}
			if bytes.Contains([]byte(err.Error()), []byte(root)) {
				t.Fatalf("startup error leaked configured path: %v", err)
			}
			for _, output := range []string{statsPath, statePath, statePath + "~"} {
				if _, statErr := os.Lstat(output); !os.IsNotExist(statErr) {
					t.Fatalf(
						"unsafe %s path wrote %s: %v",
						document,
						filepath.Base(output),
						statErr,
					)
				}
			}
		})
	}
}

func countOpenDescriptors(t *testing.T) int {
	t.Helper()
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Fatal(err)
	}
	return len(entries)
}
