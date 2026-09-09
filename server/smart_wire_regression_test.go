package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestActualClientSMARTFallbackWireRetainsValueErrorAndFallbackEvidence(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "testdata", "smart-attribute-fallback-invalid-temperature.json"))
	if err != nil {
		t.Fatal(err)
	}
	registry := testRegistry(testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil))
	app := newMultiDeviceTestApp(t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1})
	now := time.Date(2026, 7, 15, 0, 0, 0, 0, time.UTC)
	issues, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2", CollectedAt: now,
		FlatStats: raw, Generation: 1,
	}, now)
	if err != nil || len(issues) != 0 {
		t.Fatalf("actual client wire payload was not accepted: issues=%#v err=%v", issues, err)
	}
	disk := app.nodes["device-alpha"].Extension.Hardware.Storage.PhysicalDisks[0]
	if disk.CollectionStatus != "invalid_data" || disk.SMARTStatus != DiskSMARTPassed ||
		disk.Error == nil || disk.Error.Code != "smart_value_invalid" ||
		disk.Completeness == nil || *disk.Completeness != "partial" ||
		disk.HealthSource == nil || *disk.HealthSource != "attribute_check" ||
		disk.NativeStatus == nil || *disk.NativeStatus != "unavailable" {
		t.Fatalf("client SMART facts changed during decode: %#v", disk)
	}
	server := app.snapshotStatsAt(false, now)["servers"].([]any)[0].(map[string]any)
	diagnostics := server["collection_diagnostics"].([]CollectionDiagnostic)
	found := map[string]string{}
	for _, diagnostic := range diagnostics {
		if diagnostic.Component == "storage.physical_disks" && diagnostic.Resource == "sdu" {
			found[diagnostic.Code] = diagnostic.Status
		}
	}
	if found["smart_value_invalid"] != "degraded" || found["smart_return_status_unavailable"] != "partial" {
		t.Fatalf("value error or trusted fallback evidence was lost: %#v", diagnostics)
	}
}
