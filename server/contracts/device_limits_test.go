package contracts

import (
	"encoding/json"
	"fmt"
	"testing"
)

func TestRegisteredDeviceLimitAndStableStatsProjection(t *testing.T) {
	if MaxRegisteredDevices != 16 || MaxDevices != MaxRegisteredDevices {
		t.Fatalf("registered-device constants diverged: registered=%d devices=%d",
			MaxRegisteredDevices, MaxDevices)
	}
	single, err := DecodeRegistry(fixture(t, "valid", "registry-single.json"), fixtureNow)
	if err != nil || len(single.Devices) != 1 {
		t.Fatalf("one registered device was rejected: devices=%d err=%v",
			len(single.Devices), err)
	}
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-16.json"), fixtureNow)
	if err != nil || len(registry.Devices) != MaxRegisteredDevices {
		t.Fatalf("sixteen registered devices were rejected: devices=%d err=%v",
			len(registry.Devices), err)
	}
	registry.Devices[MaxRegisteredDevices-1].Enabled = boolPointer(false)
	if err := ValidateRegistry(registry, fixtureNow); err != nil {
		t.Fatalf("disabled registered device did not remain in quota: %v", err)
	}
	document := ProjectStatsV2(*registry, nil, nil, fixtureNow)
	if len(document.Servers) != MaxRegisteredDevices {
		t.Fatalf("stats projection truncated registered devices: %d", len(document.Servers))
	}
	if err := ValidateStatsV2(document); err != nil {
		t.Fatalf("sixteen-device stats failed validation: %v", err)
	}
	encoded, err := SerializeStatsV2(document)
	if err != nil {
		t.Fatalf("sixteen-device stats failed serialization: %v", err)
	}
	var decoded StatsV2Document
	if err := json.Unmarshal(encoded, &decoded); err != nil ||
		len(decoded.Servers) != MaxRegisteredDevices {
		t.Fatalf("sixteen-device stats failed round trip: servers=%d err=%v",
			len(decoded.Servers), err)
	}
	for index := 1; index < len(document.Servers); index++ {
		if document.Servers[index-1].DeviceID >= document.Servers[index].DeviceID {
			t.Fatalf("sixteen-device stats are not stably sorted at %d", index)
		}
	}
	if _, err := DecodeRegistry(
		fixture(t, "invalid", "registry-17-devices.json"), fixtureNow,
	); err == nil {
		t.Fatal("seventeen registered devices were accepted")
	}
}

func TestLegacyMappingAndOrphanLimitsAreIndependent(t *testing.T) {
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-16.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	mappings := LegacyMappingDocument{Version: 1}
	for index, device := range registry.Devices {
		device.Ingestion = IngestionOwnership{
			Mode:           "legacy",
			ActiveProtocol: stringPointer("legacy_single_device"),
		}
		registry.Devices[index] = device
		mappings.Mappings = append(mappings.Mappings, LegacyDeviceMapping{
			Username: fmt.Sprintf("synthetic-user-%02d", index),
			DeviceID: device.ID,
		})
	}
	if err := ValidateLegacyMappings(&mappings, registry, fixtureNow); err != nil {
		t.Fatalf("sixteen legacy mappings were rejected: %v", err)
	}
	mappings.Mappings = append(mappings.Mappings, LegacyDeviceMapping{
		Username: "synthetic-user-17",
		DeviceID: registry.Devices[0].ID,
	})
	if err := ValidateLegacyMappings(&mappings, registry, fixtureNow); err == nil {
		t.Fatal("seventeen legacy mappings were accepted")
	}

	snapshot := PersistenceV2{
		Version: 2, GeneratedAt: fixtureNow.Format("2006-01-02T15:04:05Z"),
		Devices: []PersistedDevice{},
	}
	for index := 0; index < MaxOrphanedDevices; index++ {
		snapshot.OrphanedDevices = append(snapshot.OrphanedDevices, OrphanedDevice{
			OrphanID: fmt.Sprintf("orphan-%02d", index),
			Reason:   "removed_device", SourceVersion: 2,
			Snapshot: json.RawMessage(`{}`),
		})
	}
	if err := ValidatePersistenceV2(&snapshot); err != nil {
		t.Fatalf("%d independent orphans were rejected: %v", MaxOrphanedDevices, err)
	}
	snapshot.OrphanedDevices = append(snapshot.OrphanedDevices, OrphanedDevice{
		OrphanID: "orphan-over-limit", Reason: "removed_device",
		SourceVersion: 2, Snapshot: json.RawMessage(`{}`),
	})
	if err := ValidatePersistenceV2(&snapshot); err == nil {
		t.Fatalf("%d orphaned devices were accepted", MaxOrphanedDevices+1)
	}
}

func TestLegacyMigrationAcceptsSixteenAndRejectsSeventeen(t *testing.T) {
	legacy, err := DecodePersistenceV1(
		fixture(t, "valid", "persistence-v1-sixteen.json"),
	)
	if err != nil || len(legacy.Servers) != MaxRegisteredDevices {
		t.Fatalf("sixteen legacy migration entries were rejected: servers=%d err=%v",
			len(legacy.Servers), err)
	}
	legacy.Servers = append(legacy.Servers, map[string]any{
		"name": "Synthetic Legacy 17",
	})
	encoded, err := json.Marshal(legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodePersistenceV1(encoded); err == nil {
		t.Fatal("seventeen legacy migration entries were accepted")
	}
}
