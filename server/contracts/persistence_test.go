package contracts

import (
	"encoding/json"
	"testing"
)

func TestPersistenceV2RestoreIsNonOnlineAndFreshnessReset(t *testing.T) {
	snapshot, err := DecodePersistenceV2(fixture(t, "valid", "persistence-v2.json"))
	if err != nil {
		t.Fatal(err)
	}
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-single.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	restored := RestorePersistenceMock(*snapshot, *registry)
	state := restored["device-alpha"]
	if state.Status != "offline" || !state.Stale || state.LastAcceptedGeneration != 7 {
		t.Fatalf("restored state became fresh/online: %#v", state)
	}

	disabled := *registry
	disabled.Devices = append([]RegistryDevice(nil), registry.Devices...)
	disabled.Devices[0].Enabled = boolPointer(false)
	if state := RestorePersistenceMock(*snapshot, disabled)["device-alpha"]; state.Status != "disabled" {
		t.Fatalf("registry disabled state did not win: %#v", state)
	}

	removed := *registry
	removed.Devices = nil
	if restored := RestorePersistenceMock(*snapshot, removed); len(restored) != 0 {
		t.Fatalf("removed device was auto-registered: %#v", restored)
	}
}

func TestPersistenceV1MigrationExplicitBindingsOrphansAndCollision(t *testing.T) {
	var migration struct {
		Source   LegacyPersistenceV1 `json:"source"`
		Bindings []struct {
			SourceIndex int    `json:"source_index"`
			DeviceID    string `json:"device_id"`
		} `json:"bindings"`
	}
	if err := json.Unmarshal(
		fixture(t, "valid", "persistence-migration-v1-v2.json"), &migration,
	); err != nil {
		t.Fatal(err)
	}
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-single.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	bindings := map[int]string{}
	for _, binding := range migration.Bindings {
		bindings[binding.SourceIndex] = binding.DeviceID
	}
	snapshot, err := MigratePersistenceV1Mock(migration.Source, bindings, *registry, fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Devices) != 1 || len(snapshot.OrphanedDevices) != 1 ||
		snapshot.OrphanedDevices[0].Reason != "unmatched_v1" {
		t.Fatalf("unmatched migration was not retained as orphan: %#v", snapshot)
	}
	if restored := RestorePersistenceMock(snapshot, *registry)["device-alpha"]; restored.Status != "offline" || !restored.Stale {
		t.Fatalf("migrated device became online/fresh: %#v", restored)
	}

	if _, err := MigratePersistenceV1Mock(
		migration.Source, map[int]string{0: "device-alpha", 1: "device-alpha"},
		*registry, fixtureNow,
	); err == nil {
		t.Fatal("ambiguous collision was accepted")
	}

	snapshot, err = MigratePersistenceV1Mock(
		migration.Source, map[int]string{0: "device-removed"}, *registry, fixtureNow,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.OrphanedDevices) != 2 || snapshot.OrphanedDevices[0].Reason != "removed_device" {
		t.Fatalf("removed device was not retained: %#v", snapshot.OrphanedDevices)
	}
}

func TestPersistenceRejectsCorruptVersion(t *testing.T) {
	if _, err := DecodePersistenceV2(
		fixture(t, "invalid", "persistence-corrupt-version.json"),
	); err == nil {
		t.Fatal("corrupt persistence version was accepted")
	}
}

func TestPersistenceV1FourDeviceFixtureMigratesByExplicitIndex(t *testing.T) {
	var legacy LegacyPersistenceV1
	if err := json.Unmarshal(fixture(t, "valid", "persistence-v1-four.json"), &legacy); err != nil {
		t.Fatal(err)
	}
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-four.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	bindings := map[int]string{}
	for index, device := range registry.Devices {
		bindings[index] = device.ID
	}
	snapshot, err := MigratePersistenceV1Mock(legacy, bindings, *registry, fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Devices) != 4 || len(snapshot.OrphanedDevices) != 0 {
		t.Fatalf("four-device migration did not preserve cardinality: %#v", snapshot)
	}
	restored := RestorePersistenceMock(snapshot, *registry)
	if restored["device-delta"].Status != "disabled" {
		t.Fatalf("disabled registry authority did not win: %#v", restored["device-delta"])
	}
	for deviceID, state := range restored {
		if state.Status == "online" || !state.Stale {
			t.Fatalf("restored %s became online/fresh: %#v", deviceID, state)
		}
	}
}
