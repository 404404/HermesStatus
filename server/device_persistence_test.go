package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
	"golang.org/x/sys/unix"
)

func TestPersistenceV2WriteReadAndRestartNeverRestoresOnline(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Now().UTC()
	for index, deviceID := range []string{"device-alpha", "device-beta"} {
		if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
			DeviceID: deviceID, ProtocolMode: "device_v2",
			CollectedAt: now.Add(-time.Duration(index) * time.Second),
			FlatStats:   []byte(`{"cpu":42,"network_in":100,"network_out":200}`),
			Generation:  uint64(index + 1),
		}, now); err != nil {
			t.Fatal(err)
		}
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(app.opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	snapshot, err := contracts.DecodePersistenceV2(data)
	if err != nil {
		t.Fatalf("written persistence is not a valid v2 snapshot: %v", err)
	}
	if len(snapshot.Devices) != 2 || snapshot.Version != 2 {
		t.Fatalf("multi-device state was not persisted: %#v", snapshot)
	}
	var rawDocument struct {
		Devices []map[string]json.RawMessage `json:"devices"`
	}
	if err := json.Unmarshal(data, &rawDocument); err != nil {
		t.Fatal(err)
	}
	for _, device := range rawDocument.Devices {
		for _, forbidden := range []string{
			"display_name", "expected_fqdn", "order", "enabled",
			"ingestion", "password", "username",
		} {
			if _, exists := device[forbidden]; exists {
				t.Fatalf("persistence device contains registry/auth authority %q", forbidden)
			}
		}
	}
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now.Add(time.Nanosecond),
		FlatStats:   []byte(`{"cpu":44}`), Generation: 3,
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	backup, err := os.ReadFile(app.opts.PersistencePath + "~")
	if err != nil {
		t.Fatalf("atomic persistence backup was not retained: %v", err)
	}
	if _, err := contracts.DecodePersistenceV2(backup); err != nil {
		t.Fatalf("persistence backup is invalid: %v", err)
	}

	restarted, err := NewApp(app.opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	for _, deviceID := range []string{"device-alpha", "device-beta"} {
		node := restarted.nodes[deviceID]
		if !node.Restored || !node.HasUpdate ||
			restarted.deviceStatusAt(node, time.Now()) != "offline" {
			t.Fatalf("%s was restored online/fresh: %#v", deviceID, node)
		}
	}
	public := restarted.SnapshotStats()["servers"].([]any)
	for _, item := range public {
		server := item.(map[string]any)
		if server["status"] != "offline" || server["stale"] != true ||
			!server["hardware"].(*HardwareStats).Stale {
			t.Fatalf("restored projection became fresh: %#v", server)
		}
	}
}

func TestPersistenceRegistryRenameOrderDisableRemoveAndReadd(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Now()
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":51}`), Generation: 7,
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	opts := app.opts

	renamed := testRegistry(
		testRegistryDevice("device-beta", "Beta renamed", 5, true, "device_v2", nil),
		testRegistryDevice("device-alpha", "Alpha renamed", 50, false, "device_v2", nil),
	)
	writeJSONTestFile(t, opts.RegistryPath, renamed)
	disabled, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	if disabled.nodes["device-alpha"].DisplayName != "Alpha renamed" ||
		disabled.deviceStatusAt(disabled.nodes["device-alpha"], time.Now()) != "disabled" ||
		disabled.nodes["device-alpha"].Stats.CPU != 51 {
		t.Fatalf("registry authority did not win over restored state: %#v", disabled.nodes["device-alpha"])
	}
	disabled.Close()

	removed := testRegistry(
		testRegistryDevice("device-beta", "Beta only", 5, true, "device_v2", nil),
	)
	writeJSONTestFile(t, opts.RegistryPath, removed)
	removedApp, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	if removedApp.nodes["device-alpha"] != nil || len(removedApp.orphans) != 1 ||
		removedApp.orphans[0].Reason != "unknown_v2" {
		t.Fatalf("removed device history was not orphaned: %#v", removedApp.orphans)
	}
	if err := removedApp.PersistStats(); err != nil {
		t.Fatal(err)
	}
	removedApp.Close()

	readdedRegistry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha readded", 1, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 5, true, "device_v2", nil),
	)
	writeJSONTestFile(t, opts.RegistryPath, readdedRegistry)
	readded, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(readded.Close)
	if readded.nodes["device-alpha"].Stats.CPU != 51 ||
		!readded.nodes["device-alpha"].Restored || len(readded.orphans) != 0 {
		t.Fatalf("re-added stable ID did not reclaim validated history: node=%#v orphans=%#v",
			readded.nodes["device-alpha"], readded.orphans)
	}
}

func TestPersistenceRejectsCorruptAndOversizedSnapshotsWithoutPartialState(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	opts := app.opts
	app.Close()

	for _, testCase := range []struct {
		name string
		data []byte
	}{
		{name: "corrupt", data: []byte(`{"version":99}`)},
		{name: "oversized", data: []byte(strings.Repeat("x", maxPersistenceBytes+1))},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			if err := os.WriteFile(opts.PersistencePath, testCase.data, 0o600); err != nil {
				t.Fatal(err)
			}
			if restarted, err := NewApp(opts); err == nil {
				restarted.Close()
				t.Fatal("invalid persistence did not fail startup")
			}
		})
	}
}

func TestPersistenceUnsafePathFailsStartupWithoutChangingTarget(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	opts := app.opts
	app.Close()
	_ = os.Remove(opts.PersistencePath)
	_ = os.Remove(opts.PersistencePath + "~")
	target := filepath.Join(filepath.Dir(opts.PersistencePath), "target.json")
	original := []byte("target-must-remain-unchanged")
	if err := os.WriteFile(target, original, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, opts.PersistencePath); err != nil {
		t.Fatal(err)
	}
	if restarted, err := NewApp(opts); err == nil {
		restarted.Close()
		t.Fatal("symlink persistence path did not fail startup")
	}
	after, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(after, original) {
		t.Fatal("failed startup changed symlink target")
	}
}

func TestPersistencePreflightRejectsUnsafeBackupEvenWithValidPrimary(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	opts := app.opts
	app.Close()
	primaryBefore, err := os.ReadFile(opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(opts.PersistencePath + "~"); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(filepath.Dir(opts.PersistencePath), "backup-target.json")
	targetBefore := []byte("backup-target-must-remain-unchanged")
	if err := os.WriteFile(target, targetBefore, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, opts.PersistencePath+"~"); err != nil {
		t.Fatal(err)
	}
	if restarted, err := NewApp(opts); err == nil || restarted != nil {
		if restarted != nil {
			restarted.Close()
		}
		t.Fatalf("valid primary bypassed unsafe backup preflight: app=%#v err=%v", restarted, err)
	}
	primaryAfter, err := os.ReadFile(opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	targetAfter, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(primaryBefore, primaryAfter) ||
		!bytes.Equal(targetBefore, targetAfter) {
		t.Fatal("failed backup preflight changed primary or symlink target")
	}
	matches, err := filepath.Glob(filepath.Join(
		filepath.Dir(opts.PersistencePath),
		".hermesstatus-*.tmp",
	))
	if err != nil || len(matches) != 0 {
		t.Fatalf("failed preflight left temporary state: %v %v", matches, err)
	}
}

func TestPersistencePreflightRejectsSpecialFilesAliasesAndUnsafeParent(t *testing.T) {
	snapshot := orphanBoundarySnapshot(0, false)
	t.Run("backup_directory", func(t *testing.T) {
		directory := t.TempDir()
		path := filepath.Join(directory, "state-v2.json")
		writeJSONTestFile(t, path, snapshot)
		if err := os.Mkdir(path+"~", 0o700); err != nil {
			t.Fatal(err)
		}
		if paths, err := openPersistencePaths(path, path+"~", true); err == nil {
			paths.close()
			t.Fatal("directory backup passed persistence preflight")
		}
	})
	t.Run("backup_fifo", func(t *testing.T) {
		directory := t.TempDir()
		path := filepath.Join(directory, "state-v2.json")
		writeJSONTestFile(t, path, snapshot)
		if err := unix.Mkfifo(path+"~", 0o600); err != nil {
			t.Fatal(err)
		}
		if paths, err := openPersistencePaths(path, path+"~", true); err == nil {
			paths.close()
			t.Fatal("FIFO backup passed persistence preflight")
		}
	})
	t.Run("hardlink_alias", func(t *testing.T) {
		directory := t.TempDir()
		path := filepath.Join(directory, "state-v2.json")
		writeJSONTestFile(t, path, snapshot)
		if err := os.Link(path, path+"~"); err != nil {
			t.Fatal(err)
		}
		if paths, err := openPersistencePaths(path, path+"~", true); err == nil {
			paths.close()
			t.Fatal("primary/backup inode alias passed persistence preflight")
		}
	})
	t.Run("same_path", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "state-v2.json")
		if paths, err := openPersistencePaths(path, path, true); err == nil {
			paths.close()
			t.Fatal("same primary and backup path passed persistence preflight")
		}
	})
	t.Run("missing_parent", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "missing", "state-v2.json")
		if paths, err := openPersistencePaths(path, path+"~", true); err == nil {
			paths.close()
			t.Fatal("missing persistence parent passed preflight")
		}
	})
	t.Run("symlink_parent", func(t *testing.T) {
		root := t.TempDir()
		targetDirectory := filepath.Join(root, "target")
		if err := os.Mkdir(targetDirectory, 0o700); err != nil {
			t.Fatal(err)
		}
		linkDirectory := filepath.Join(root, "linked")
		if err := os.Symlink(targetDirectory, linkDirectory); err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(linkDirectory, "state-v2.json")
		if paths, err := openPersistencePaths(path, path+"~", true); err == nil {
			paths.close()
			t.Fatal("symlinked persistence parent passed preflight")
		}
	})
	t.Run("inaccessible_backup", func(t *testing.T) {
		directory := t.TempDir()
		path := filepath.Join(directory, "state-v2.json")
		writeJSONTestFile(t, path, snapshot)
		writeJSONTestFile(t, path+"~", snapshot)
		if err := os.Chmod(path+"~", 0); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(path+"~", 0o600) })
		paths, err := openPersistencePaths(path, path+"~", true)
		if paths != nil {
			paths.close()
		}
		if os.Geteuid() != 0 && err == nil {
			t.Fatal("inaccessible backup passed persistence preflight")
		}
	})
}

func TestPersistenceStartupRecoveryMatrix(t *testing.T) {
	newOptions := func(t *testing.T) Options {
		t.Helper()
		app := newMultiDeviceTestApp(
			t,
			minimalTestConfig(),
			testRegistry(
				testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
			),
			contracts.LegacyMappingDocument{Version: 1},
		)
		return app.opts
	}
	validSnapshot := func() contracts.PersistenceV2 {
		return orphanBoundarySnapshot(0, false)
	}

	t.Run("both_missing_first_start", func(t *testing.T) {
		_ = newOptions(t)
	})
	t.Run("valid_primary_valid_backup", func(t *testing.T) {
		opts := newOptions(t)
		writeJSONTestFile(t, opts.PersistencePath, validSnapshot())
		writeJSONTestFile(t, opts.PersistencePath+"~", validSnapshot())
		restarted, err := NewApp(opts)
		if err != nil {
			t.Fatal(err)
		}
		restarted.Close()
	})
	t.Run("valid_primary_missing_backup", func(t *testing.T) {
		opts := newOptions(t)
		writeJSONTestFile(t, opts.PersistencePath, validSnapshot())
		restarted, err := NewApp(opts)
		if err != nil {
			t.Fatal(err)
		}
		restarted.Close()
	})
	t.Run("missing_primary_valid_backup", func(t *testing.T) {
		opts := newOptions(t)
		writeJSONTestFile(t, opts.PersistencePath+"~", validSnapshot())
		restarted, err := NewApp(opts)
		if err != nil {
			t.Fatal(err)
		}
		restarted.Close()
	})
	t.Run("both_corrupt", func(t *testing.T) {
		opts := newOptions(t)
		if err := os.WriteFile(opts.PersistencePath, []byte(`{"version":`), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(opts.PersistencePath+"~", []byte(`{"version":`), 0o600); err != nil {
			t.Fatal(err)
		}
		if restarted, err := NewApp(opts); err == nil || restarted != nil {
			if restarted != nil {
				restarted.Close()
			}
			t.Fatalf("two corrupt persistence files did not fail closed: app=%#v err=%v", restarted, err)
		}
	})
	t.Run("corrupt_primary_unsafe_backup", func(t *testing.T) {
		opts := newOptions(t)
		if err := os.WriteFile(opts.PersistencePath, []byte(`{"version":`), 0o600); err != nil {
			t.Fatal(err)
		}
		target := filepath.Join(filepath.Dir(opts.PersistencePath), "unsafe-backup-target")
		before := []byte("must-not-change")
		if err := os.WriteFile(target, before, 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, opts.PersistencePath+"~"); err != nil {
			t.Fatal(err)
		}
		if restarted, err := NewApp(opts); err == nil || restarted != nil {
			if restarted != nil {
				restarted.Close()
			}
			t.Fatalf("corrupt primary bypassed unsafe backup: app=%#v err=%v", restarted, err)
		}
		after, err := os.ReadFile(target)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(before, after) {
			t.Fatal("unsafe backup target changed during failed recovery")
		}
	})
}

func TestPersistenceUsesValidatedBackupWhenPrimaryIsCorrupt(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Now()
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":33}`), Generation: 1,
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now.Add(time.Nanosecond), FlatStats: []byte(`{"cpu":44}`), Generation: 2,
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(app.opts.PersistencePath, []byte(`{"version":`), 0o600); err != nil {
		t.Fatal(err)
	}
	restarted, err := NewApp(app.opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	if node := restarted.nodes["device-alpha"]; !node.Restored ||
		node.Stats.CPU != 33 || node.LastAcceptedGeneration != 1 {
		t.Fatalf("validated persistence backup was not restored: %#v", node)
	}
}

func TestCorruptEntryIsQuarantinedWithoutRetainingRawPayload(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	opts := app.opts
	app.Close()
	observedAt := time.Now().UTC().Format(time.RFC3339)
	corrupt := contracts.PersistenceV2{
		Version: 2, GeneratedAt: observedAt,
		Devices: []contracts.PersistedDevice{{
			DeviceID: "device-alpha", LastAcceptedGeneration: 9,
			ProtocolMode: "device_v2", StatusAtSnapshot: "offline",
			RuntimeObservations: map[string]json.RawMessage{},
			Domains: map[string]json.RawMessage{
				"hardware": json.RawMessage(`{"cpu_model":"raw-secret-marker","unexpected":true}`),
			},
		}},
		OrphanedDevices: []contracts.OrphanedDevice{},
	}
	writeJSONTestFile(t, opts.PersistencePath, corrupt)
	restarted, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	node := restarted.nodes["device-alpha"]
	if node.Restored || node.HasUpdate || node.LastAcceptedGeneration != 0 {
		t.Fatalf("corrupt entry was associated with active state: %#v", node)
	}
	if len(restarted.orphans) != 1 {
		t.Fatalf("corrupt entry did not produce one quarantine record: %#v", restarted.orphans)
	}
	orphan := restarted.orphans[0]
	if orphan.DeviceID != nil || orphan.Reason != "corrupt_entry" {
		t.Fatalf("corrupt quarantine could be re-associated: %#v", orphan)
	}
	quarantineText := string(orphan.Snapshot)
	for _, forbidden := range []string{"raw-secret-marker", "unexpected", "cpu_model"} {
		if strings.Contains(quarantineText, forbidden) {
			t.Fatalf("quarantine retained raw corrupt content %q: %s", forbidden, quarantineText)
		}
	}
	for _, required := range []string{"entry_reference", "sha256", "error_code", "observed_at"} {
		if !strings.Contains(quarantineText, required) {
			t.Fatalf("quarantine omitted bounded metadata %q: %s", required, quarantineText)
		}
	}
	if err := restarted.PersistStats(); err != nil {
		t.Fatal(err)
	}
	persisted, err := os.ReadFile(opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(persisted), "raw-secret-marker") {
		t.Fatal("raw corrupt payload was written into the new active snapshot")
	}
}

func TestPersistenceSnapshotIsSelfConsistentDuringConcurrentUpdates(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Now()
	done := make(chan struct{})
	go func() {
		defer close(done)
		for generation := uint64(1); generation <= 100; generation++ {
			for _, deviceID := range []string{"device-alpha", "device-beta"} {
				_, _ = app.ingestDeviceUpdateAt(deviceIngestRequest{
					DeviceID: deviceID, ProtocolMode: "device_v2",
					CollectedAt: now, FlatStats: []byte(`{"cpu":12}`),
					Generation: generation,
				}, now)
			}
		}
	}()
	for index := 0; index < 25; index++ {
		snapshot, err := app.snapshotPersistenceV2(now)
		if err != nil {
			t.Fatal(err)
		}
		data, err := json.Marshal(snapshot)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := contracts.DecodePersistenceV2(data); err != nil {
			t.Fatalf("concurrent snapshot was inconsistent: %v", err)
		}
	}
	<-done
}

func TestOrphanLimitFailsClosedBeforeRegistryTransition(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	opts := app.opts
	app.Close()
	snapshot := orphanBoundarySnapshot(contracts.MaxOrphanedDevices, true)
	writeJSONTestFile(t, opts.PersistencePath, snapshot)
	writeJSONTestFile(t, opts.PersistencePath+"~", snapshot)
	beforePrimary, err := os.ReadFile(opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	beforeBackup, err := os.ReadFile(opts.PersistencePath + "~")
	if err != nil {
		t.Fatal(err)
	}
	writeJSONTestFile(t, opts.RegistryPath, testRegistry(
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	))
	restarted, err := NewApp(opts)
	if restarted != nil || !errors.Is(err, errOrphanLimitExceeded) {
		t.Fatalf("65th projected orphan did not fail closed: app=%#v err=%v", restarted, err)
	}
	afterPrimary, err := os.ReadFile(opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	afterBackup, err := os.ReadFile(opts.PersistencePath + "~")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(beforePrimary, afterPrimary) || !bytes.Equal(beforeBackup, afterBackup) {
		t.Fatal("rejected orphan transition changed primary or backup")
	}
}

func TestOrphanLimitAllowsExactlySixtyFourAndRestarts(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	opts := app.opts
	app.Close()
	snapshot := orphanBoundarySnapshot(contracts.MaxOrphanedDevices-1, true)
	writeJSONTestFile(t, opts.PersistencePath, snapshot)
	writeJSONTestFile(t, opts.RegistryPath, testRegistry(
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	))
	restarted, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(restarted.orphans) != contracts.MaxOrphanedDevices {
		t.Fatalf("63 + removed device did not become 64: %d", len(restarted.orphans))
	}
	if err := restarted.PersistStats(); err != nil {
		t.Fatal(err)
	}
	restarted.Close()
	again, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(again.Close)
	if len(again.orphans) != contracts.MaxOrphanedDevices {
		t.Fatalf("64-orphan snapshot did not restart: %d", len(again.orphans))
	}
}

func TestPersistenceWriterRejectsInvalidSnapshotBeforeFileChanges(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "state-v2.json")
	primary := []byte("primary-must-remain")
	backup := []byte("backup-must-remain")
	if err := os.WriteFile(path, primary, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path+"~", backup, 0o600); err != nil {
		t.Fatal(err)
	}
	invalid := orphanBoundarySnapshot(contracts.MaxOrphanedDevices+1, false)
	if err := writePersistenceV2(path, invalid); err == nil {
		t.Fatal("65-orphan snapshot was written")
	}
	afterPrimary, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	afterBackup, err := os.ReadFile(path + "~")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(primary, afterPrimary) || !bytes.Equal(backup, afterBackup) {
		t.Fatal("invalid writer input changed primary or backup")
	}
	matches, err := filepath.Glob(filepath.Join(root, ".serverstatus-*.tmp"))
	if err != nil || len(matches) != 0 {
		t.Fatalf("invalid snapshot created temporary files: %v %v", matches, err)
	}
}

func orphanBoundarySnapshot(
	orphanCount int,
	includeRemovedDevice bool,
) contracts.PersistenceV2 {
	snapshot := contracts.PersistenceV2{
		Version:         2,
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339),
		Devices:         []contracts.PersistedDevice{},
		OrphanedDevices: make([]contracts.OrphanedDevice, 0, orphanCount),
	}
	if includeRemovedDevice {
		snapshot.Devices = append(snapshot.Devices, contracts.PersistedDevice{
			DeviceID:            "device-alpha",
			ProtocolMode:        "device_v2",
			StatusAtSnapshot:    "offline",
			RuntimeObservations: map[string]json.RawMessage{},
			Domains:             map[string]json.RawMessage{},
		})
	}
	for index := 0; index < orphanCount; index++ {
		snapshot.OrphanedDevices = append(
			snapshot.OrphanedDevices,
			contracts.OrphanedDevice{
				OrphanID: fmt.Sprintf("orphan-%02d", index),
				Reason:   "removed_device", SourceVersion: 2,
				Snapshot: json.RawMessage(`{}`),
			},
		)
	}
	return snapshot
}
