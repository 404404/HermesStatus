package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
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
		CollectedAt: now, FlatStats: []byte(`{"cpu":44}`), Generation: 3,
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
			restarted, err := NewApp(opts)
			if err != nil {
				t.Fatal(err)
			}
			defer restarted.Close()
			node := restarted.nodes["device-alpha"]
			if node.Restored || node.HasUpdate ||
				restarted.deviceStatusAt(node, time.Now()) != "never_seen" {
				t.Fatalf("invalid persistence partially restored state: %#v", node)
			}
		})
	}
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
		CollectedAt: now, FlatStats: []byte(`{"cpu":44}`), Generation: 2,
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
