package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestPersistencePathIsCanonicalAndStableAcrossWorkingDirectories(t *testing.T) {
	root := t.TempDir()
	configDirectory := filepath.Join(root, "server")
	if err := os.MkdirAll(configDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	configPath := filepath.Join(configDirectory, "config.json")
	registryPath := filepath.Join(root, "registry.json")
	mappingPath := filepath.Join(root, "mapping.json")
	writeJSONTestFile(t, configPath, minimalTestConfig())
	writeJSONTestFile(t, registryPath, testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 1, true, "device_v2", nil),
	))
	writeJSONTestFile(t, mappingPath, contracts.LegacyMappingDocument{Version: 1})
	opts := Options{
		ConfigPath:   configPath,
		StatsPath:    "../web/json/stats.json",
		RegistryPath: registryPath, LegacyMappingPath: mappingPath,
		WebDir: "../web", HTTPAddr: "127.0.0.1:0", AgentAddr: "127.0.0.1:0",
	}
	app, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	wantStats := filepath.Join(root, "web", "json", "stats.json")
	wantState := wantStats + ".state-v2"
	if app.opts.StatsPath != wantStats || app.opts.PersistencePath != wantState ||
		!filepath.IsAbs(app.opts.PersistencePath) {
		t.Fatalf("paths were not canonical: stats=%q state=%q", app.opts.StatsPath, app.opts.PersistencePath)
	}
	now := time.Now().UTC()
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":64}`), Generation: 1,
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	app.Close()

	originalDirectory, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(originalDirectory) })
	otherDirectory := filepath.Join(root, "other-cwd")
	if err := os.Mkdir(otherDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(otherDirectory); err != nil {
		t.Fatal(err)
	}
	restarted, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	if restarted.opts.PersistencePath != wantState ||
		!restarted.nodes["device-alpha"].Restored ||
		restarted.nodes["device-alpha"].Stats.CPU != 64 {
		t.Fatalf("restart from another cwd lost state: path=%q node=%#v",
			restarted.opts.PersistencePath, restarted.nodes["device-alpha"])
	}
}

func TestExplicitRelativePersistencePathRuleAndTraversal(t *testing.T) {
	root := t.TempDir()
	configPath := filepath.Join(root, "config.json")
	resolved, err := resolveOptionsPaths(Options{
		ConfigPath:      configPath,
		StatsPath:       "data/stats.json",
		PersistencePath: "state/state-v2.json",
	})
	if err != nil {
		t.Fatal(err)
	}
	if resolved.PersistencePath != filepath.Join(root, "state", "state-v2.json") {
		t.Fatalf("relative state path did not resolve against config: %q", resolved.PersistencePath)
	}
	if _, err := resolveOptionsPaths(Options{
		ConfigPath:      configPath,
		StatsPath:       "data/stats.json",
		PersistencePath: "../state-v2.json",
	}); !errors.Is(err, errUnsafeRuntimePath) {
		t.Fatalf("parent traversal was accepted: %v", err)
	}
}

func TestPersistenceWriterRejectsSymlinkBeforeAnyWrite(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target.json")
	link := filepath.Join(root, "state-v2.json")
	original := []byte("target-must-remain-unchanged")
	if err := os.WriteFile(target, original, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	snapshot := contracts.PersistenceV2{
		Version:         2,
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339),
		Devices:         []contracts.PersistedDevice{},
		OrphanedDevices: []contracts.OrphanedDevice{},
	}
	if err := writePersistenceV2(link, snapshot); !errors.Is(err, errUnsafeRuntimePath) {
		t.Fatalf("symlink persistence path was accepted: %v", err)
	}
	after, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(after) != string(original) {
		t.Fatal("symlink target was modified")
	}
}
