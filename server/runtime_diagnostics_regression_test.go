package main

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestReloadAndPersistenceRetainDecoderEvidenceForSameDevice(t *testing.T) {
	registry := testRegistry(testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil))
	app := newMultiDeviceTestApp(t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1})
	fields := map[string]json.RawMessage{}
	if err := json.Unmarshal(structuredUpdatePayload(t, "update-normal.json", nil), &fields); err != nil {
		t.Fatal(err)
	}
	invalidUniFi, err := json.Marshal(syntheticUniFiAPIPortStats(syntheticUniFiPorts(MaxUniFiSitePortObservations + 1)))
	if err != nil {
		t.Fatal(err)
	}
	fields["unifi"] = invalidUniFi
	payload, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	issues, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2", CollectedAt: now,
		FlatStats: payload, Generation: 1,
	}, now)
	if err != nil || len(issues) != 1 || issues[0].Field != "unifi.api.telemetry.ports" {
		t.Fatalf("decoder evidence was not recorded: issues=%#v err=%v", issues, err)
	}
	assertDecoderEvidence := func(candidate *App, want, restored bool) {
		server := candidate.snapshotStatsAt(false, now)["servers"].([]any)[0].(map[string]any)
		wantStatus, wantStale := "online", false
		if want {
			wantStatus = "degraded"
		}
		if restored {
			wantStatus, wantStale = "offline", true
		}
		if server["stale"] != wantStale || server["status"] != wantStatus {
			t.Fatalf("reload changed freshness or business status: %#v", server)
		}
		found := false
		for _, diagnostic := range server["collection_diagnostics"].([]CollectionDiagnostic) {
			if diagnostic.Field == "unifi.api.telemetry.ports" && diagnostic.Reason == "array exceeds the allowed size" {
				found = true
			}
		}
		if found != want {
			t.Fatalf("decoder evidence presence=%t want=%t: %#v", found, want, server["collection_diagnostics"])
		}
	}
	assertDecoderEvidence(app, true, false)
	if apiErr := app.ReloadConfig(); apiErr != nil {
		t.Fatal(apiErr)
	}
	assertDecoderEvidence(app, true, false)
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	restarted, err := NewApp(app.opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	assertDecoderEvidence(restarted, true, true)

	next := now.Add(time.Second)
	issues, err = restarted.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2", CollectedAt: next,
		FlatStats: []byte(`{"cpu":2}`), Generation: 2,
	}, next)
	if err != nil || len(issues) != 0 {
		t.Fatalf("successful replacement report failed: issues=%#v err=%v", issues, err)
	}
	now = next
	assertDecoderEvidence(restarted, false, false)
}
