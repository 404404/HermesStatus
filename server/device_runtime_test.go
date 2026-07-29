package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestMultiDeviceRuntimeLoadsAtomicallyAndRekeysNodes(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-beta", "Beta", 10, true, "device_v2", nil),
		testRegistryDevice("device-alpha", "Alpha", 20, true, "legacy", nil),
		testRegistryDevice("device-gamma", "Gamma", 25, true, "device_v2", nil),
		testRegistryDevice("device-delta", "Delta", 30, false, "device_v2", nil),
	)
	registry.Defaults.DefaultDeviceID = "device-alpha"
	app := newMultiDeviceTestApp(t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{
		Version: 1,
		Mappings: []contracts.LegacyDeviceMapping{{
			Username: "s01", DeviceID: "device-alpha",
		}},
	})
	if !app.multiDeviceEnabled() {
		t.Fatal("valid registry and mapping did not enable multi-device runtime")
	}
	if app.nodes["s01"] != nil || app.nodes["device-alpha"] == nil ||
		app.nodes["device-beta"] == nil || app.nodes["device-gamma"] == nil ||
		app.nodes["device-delta"] == nil {
		t.Fatalf("nodes were not exclusively re-keyed by device_id: %#v", app.nodes)
	}

	stats := app.SnapshotStats()
	servers := stats["servers"].([]any)
	if len(servers) != 4 {
		t.Fatalf("registered devices were not completely projected: %#v", servers)
	}
	wantIDs := []string{"device-beta", "device-alpha", "device-gamma", "device-delta"}
	wantStatuses := []string{"never_seen", "never_seen", "never_seen", "disabled"}
	for index, item := range servers {
		server := item.(map[string]any)
		if server["device_id"] != wantIDs[index] || server["status"] != wantStatuses[index] {
			t.Fatalf("unexpected stable projection at %d: %#v", index, server)
		}
		if server["status"] == "disabled" &&
			(server["identity_status"] != "disabled" || server["protocol_mode"] != "none") {
			t.Fatalf("disabled registry authority did not win: %#v", server)
		}
		if server["expected_fqdn"] != nil || server["reported_fqdn"] != nil {
			t.Fatalf("browser projection exposed FQDN evidence: %#v", server)
		}
	}
	if stats["default_device_id"] != "device-alpha" || stats["schema_version"] != 2 {
		t.Fatalf("missing multi-device document metadata: %#v", stats)
	}
	encoded, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{
		`"mappings"`, `"ownership"`, `"orphaned_devices"`,
		`"password"`, `"username"`, "alpha.example.invalid",
	} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatalf("browser stats leaked internal field %q", forbidden)
		}
	}
	if _, err := app.ingestDeviceUpdate(
		"device-delta", "device_v2", time.Now(), []byte(`{"cpu":99}`), 1,
	); !errors.Is(err, errDeviceDisabled) {
		t.Fatalf("disabled registry device accepted an update: %v", err)
	}
	before := len(app.nodes)
	if _, err := app.ingestDeviceUpdate(
		"unknown-device", "device_v2", time.Now(), []byte(`{"cpu":99}`), 1,
	); !errors.Is(err, errDeviceNotRegistered) || len(app.nodes) != before {
		t.Fatalf("unknown device was accepted or auto-created: %v", err)
	}
}

func TestInvalidMultiDeviceDocumentsFallBackWithoutPartialActivation(t *testing.T) {
	validRegistry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "legacy", nil),
	)
	cases := []struct {
		name        string
		registry    any
		mapping     any
		omitMapping bool
	}{
		{
			name: "unknown-registry-field",
			registry: map[string]any{
				"version": 1, "defaults": validRegistry.Defaults,
				"devices": validRegistry.Devices, "unexpected": true,
			},
			mapping: contracts.LegacyMappingDocument{Version: 1},
		},
		{
			name:     "missing-target",
			registry: validRegistry,
			mapping: contracts.LegacyMappingDocument{
				Version: 1,
				Mappings: []contracts.LegacyDeviceMapping{{
					Username: "s01", DeviceID: "missing-device",
				}},
			},
		},
		{
			name:     "missing-mapping-document",
			registry: validRegistry, omitMapping: true,
		},
		{
			name:     "mapping-username-not-in-runtime-config",
			registry: validRegistry,
			mapping: contracts.LegacyMappingDocument{
				Version: 1,
				Mappings: []contracts.LegacyDeviceMapping{{
					Username: "not-configured", DeviceID: "device-alpha",
				}},
			},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			app := newMultiDeviceTestAppRaw(
				t, minimalTestConfig(), testCase.registry, testCase.mapping, testCase.omitMapping,
			)
			if app.multiDeviceEnabled() || app.nodes["s01"] == nil ||
				app.nodes["device-alpha"] != nil {
				t.Fatalf("invalid documents partially activated 2.2: %#v", app.nodes)
			}
			if _, exists := app.SnapshotStats()["schema_version"]; exists {
				t.Fatal("fallback changed the 2.1 stats contract")
			}
		})
	}
}

func TestUnifiedIngestionOwnershipIdentityGenerationAndFreshness(t *testing.T) {
	expected := "alpha.example.invalid"
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", &expected),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Date(2026, 7, 29, 4, 0, 0, 0, time.UTC)
	reported := expected
	issues, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now.Add(-time.Minute), FlatStats: []byte(`{"cpu":11}`),
		Generation: 1, ReportedFQDN: &reported,
	}, now)
	if err != nil || len(issues) != 0 {
		t.Fatalf("valid v2 update was rejected: issues=%#v err=%v", issues, err)
	}
	if status := app.deviceStatusAt(app.nodes["device-alpha"], now); status != "online" {
		t.Fatalf("accepted device is not online: %s", status)
	}
	beforeRejected := *app.nodes["device-alpha"]
	beforeExtension, _ := json.Marshal(beforeRejected.Extension)

	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "legacy_single_device",
		CollectedAt: now, FlatStats: []byte(`{"cpu":99}`), Generation: 2,
	}, now); !errors.Is(err, errInactiveOwner) {
		t.Fatalf("inactive owner was not rejected: %v", err)
	}
	if app.nodes["device-alpha"].Stats.CPU != 11 {
		t.Fatal("inactive owner overwrote accepted data")
	}
	afterRejected := app.nodes["device-alpha"]
	afterExtension, _ := json.Marshal(afterRejected.Extension)
	if afterRejected.LastAcceptedGeneration != beforeRejected.LastAcceptedGeneration ||
		!afterRejected.LastSeen.Equal(beforeRejected.LastSeen) ||
		!afterRejected.CollectedAt.Equal(beforeRejected.CollectedAt) ||
		string(afterExtension) != string(beforeExtension) {
		t.Fatal("inactive owner modified generation, timestamps, or domain state")
	}

	mismatch := "other.example.invalid"
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":99}`), Generation: 2,
		ReportedFQDN: &mismatch,
	}, now); !errors.Is(err, errDeviceIdentity) {
		t.Fatalf("identity mismatch was not rejected: %v", err)
	}
	if app.nodes["device-alpha"].Stats.CPU != 11 ||
		app.deviceStatusAt(app.nodes["device-alpha"], now) != "identity_error" {
		t.Fatal("identity failure replaced data or did not set identity_error")
	}
	if app.deviceIsStaleAt(app.nodes["device-alpha"], now) {
		t.Fatal("identity failure incorrectly changed server-time freshness")
	}

	app.nodes["device-alpha"].IdentityError = false
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":22}`), Generation: 1,
		ReportedFQDN: &reported,
	}, now); !errors.Is(err, errStaleGeneration) {
		t.Fatalf("older generation was not rejected: %v", err)
	}
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now.Add(MaxDeviceClockSkew + time.Second),
		FlatStats:   []byte(`{"cpu":22}`), Generation: 2, ReportedFQDN: &reported,
	}, now); !errors.Is(err, errDeviceClockSkew) {
		t.Fatalf("clock-skew bound was not enforced: %v", err)
	}

	node := app.nodes["device-alpha"]
	node.LastSeen = now.Add(-31 * time.Second)
	if status := app.deviceStatusAt(node, now); status != "stale" {
		t.Fatalf("stale threshold was not server-time based: %s", status)
	}
	node.LastSeen = now.Add(-61 * time.Second)
	if status := app.deviceStatusAt(node, now); status != "offline" {
		t.Fatalf("offline threshold was not server-time based: %s", status)
	}
}

func TestMultiDeviceConcurrentUpdatesRemainIsolatedAndNewestWins(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	now := time.Now().UTC()
	var wait sync.WaitGroup
	for _, deviceID := range []string{"device-alpha", "device-beta"} {
		deviceID := deviceID
		for generation := uint64(1); generation <= 64; generation++ {
			generation := generation
			wait.Add(1)
			go func() {
				defer wait.Done()
				_, _ = app.ingestDeviceUpdateAt(deviceIngestRequest{
					DeviceID: deviceID, ProtocolMode: "device_v2",
					CollectedAt: now,
					FlatStats:   []byte(fmt.Sprintf(`{"cpu":%d}`, generation)),
					Generation:  generation,
				}, now)
			}()
		}
	}
	wait.Wait()
	for _, deviceID := range []string{"device-alpha", "device-beta"} {
		node := app.nodes[deviceID]
		if node.LastAcceptedGeneration != 64 || node.Stats.CPU != 64 {
			t.Fatalf("%s did not retain its newest isolated update: %#v", deviceID, node)
		}
	}
	if apiErr := app.ReloadConfig(); apiErr != nil {
		t.Fatal(apiErr)
	}
	for _, deviceID := range []string{"device-alpha", "device-beta"} {
		node := app.nodes[deviceID]
		if node.LastAcceptedGeneration != 64 || node.Stats.CPU != 64 {
			t.Fatalf("config merge crossed or erased %s: %#v", deviceID, node)
		}
	}
}

func TestPartialDomainFailureProducesDegradedWithoutDroppingNativeStats(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	payload := structuredUpdatePayload(t, "update-normal.json", map[string]any{"cpu": 41})
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(payload, &fields)
	var hardware map[string]any
	_ = json.Unmarshal(fields["hardware"], &hardware)
	hardware["unexpected"] = true
	fields["hardware"] = mustRawJSON(t, hardware)
	payload, _ = json.Marshal(fields)
	now := time.Now()
	issues, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: "device-alpha", ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: payload, Generation: 1,
	}, now)
	if err != nil || len(issues) != 1 || app.nodes["device-alpha"].Stats.CPU != 41 {
		t.Fatalf("partial domain isolation failed: issues=%#v err=%v", issues, err)
	}
	if status := app.deviceStatusAt(app.nodes["device-alpha"], now); status != "degraded" {
		t.Fatalf("partial domain failure did not produce degraded: %s", status)
	}
}

func TestLegacyTCPAuthenticationMapsExplicitlyAndKeepsDuplicateRule(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "legacy", nil),
	)
	app := newMultiDeviceTestApp(t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{
		Version: 1,
		Mappings: []contracts.LegacyDeviceMapping{{
			Username: "s01", DeviceID: "device-alpha",
		}},
	})
	server, client := net.Pipe()
	defer server.Close()
	defer client.Close()
	deviceID, connectionID, _, apiErr := app.connectAgent("s01", "secret", server, 4)
	if apiErr != nil || deviceID != "device-alpha" || connectionID == 0 {
		t.Fatalf("explicit legacy mapping failed: device=%q id=%d err=%v",
			deviceID, connectionID, apiErr)
	}
	now := time.Now()
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: deviceID, ProtocolMode: "legacy_single_device",
		CollectedAt: now, FlatStats: []byte(`{"cpu":17}`),
		Generation: 1, ConnectionID: connectionID,
	}, now); err != nil {
		t.Fatalf("legacy owner rejected legacy ingestion: %v", err)
	}
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: deviceID, ProtocolMode: "device_v2",
		CollectedAt: now, FlatStats: []byte(`{"cpu":99}`), Generation: 2,
	}, now); !errors.Is(err, errInactiveOwner) {
		t.Fatalf("legacy owner accepted device_v2 ingestion: %v", err)
	}
	otherServer, otherClient := net.Pipe()
	defer otherServer.Close()
	defer otherClient.Close()
	if _, _, _, apiErr := app.connectAgent("s01", "secret", otherServer, 4); apiErr == nil ||
		apiErr.Status != 409 {
		t.Fatalf("duplicate connection rule was not preserved: %v", apiErr)
	}
	app.disconnectAgent(deviceID, server, connectionID)
	if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID: deviceID, ProtocolMode: "legacy_single_device",
		CollectedAt: now, FlatStats: []byte(`{"cpu":18}`),
		Generation: 2, ConnectionID: connectionID,
	}, now); !errors.Is(err, errInactiveConnection) {
		t.Fatalf("inactive connection generation updated state: %v", err)
	}

	unmapped := newMultiDeviceTestApp(
		t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{Version: 1},
	)
	if _, _, _, apiErr := unmapped.connectAgent("s01", "secret", otherServer, 4); apiErr == nil ||
		apiErr.Status != 403 {
		t.Fatalf("username was implicitly promoted to device_id: %v", apiErr)
	}
}

func TestCutoverOwnershipAcceptsOnlyActiveProtocolAndExpiresFailClosed(t *testing.T) {
	future := time.Now().UTC().Add(24 * time.Hour).Format(time.RFC3339)
	for _, testCase := range []struct {
		name     string
		active   string
		mappings []contracts.LegacyDeviceMapping
		accept   string
		reject   string
	}{
		{
			name: "active-legacy", active: "legacy_single_device",
			mappings: []contracts.LegacyDeviceMapping{{
				Username: "s01", DeviceID: "device-alpha",
			}},
			accept: "legacy_single_device", reject: "device_v2",
		},
		{
			name: "active-v2", active: "device_v2",
			accept: "device_v2", reject: "legacy_single_device",
		},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			enabled := true
			registry := testRegistry(contracts.RegistryDevice{
				ID: "device-alpha", DisplayName: "Alpha", Enabled: &enabled,
				Order: 10, Tags: []string{},
				Ingestion: contracts.IngestionOwnership{
					Mode: "cutover", ActiveProtocol: &testCase.active,
					CutoverNotAfter: &future,
				},
			})
			app := newMultiDeviceTestApp(t, minimalTestConfig(), registry, contracts.LegacyMappingDocument{
				Version: 1, Mappings: testCase.mappings,
			})
			now := time.Now()
			if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
				DeviceID: "device-alpha", ProtocolMode: testCase.accept,
				CollectedAt: now, FlatStats: []byte(`{"cpu":10}`), Generation: 1,
			}, now); err != nil {
				t.Fatalf("active cutover protocol was rejected: %v", err)
			}
			if _, err := app.ingestDeviceUpdateAt(deviceIngestRequest{
				DeviceID: "device-alpha", ProtocolMode: testCase.reject,
				CollectedAt: now, FlatStats: []byte(`{"cpu":20}`), Generation: 2,
			}, now); !errors.Is(err, errInactiveOwner) {
				t.Fatalf("inactive cutover protocol was accepted: %v", err)
			}
		})
	}

	expired := time.Now().UTC().Add(-time.Minute).Format(time.RFC3339)
	active := "legacy_single_device"
	enabled := true
	expiredRegistry := testRegistry(contracts.RegistryDevice{
		ID: "device-alpha", DisplayName: "Alpha", Enabled: &enabled,
		Order: 10, Tags: []string{},
		Ingestion: contracts.IngestionOwnership{
			Mode: "cutover", ActiveProtocol: &active, CutoverNotAfter: &expired,
		},
	})
	app := newMultiDeviceTestApp(t, minimalTestConfig(), expiredRegistry, contracts.LegacyMappingDocument{
		Version: 1,
		Mappings: []contracts.LegacyDeviceMapping{{
			Username: "s01", DeviceID: "device-alpha",
		}},
	})
	if !app.ownershipFailClosed {
		t.Fatal("expired cutover did not enter fail-closed ownership mode")
	}
	server, client := net.Pipe()
	defer server.Close()
	defer client.Close()
	if _, _, _, apiErr := app.connectAgent("s01", "secret", server, 4); apiErr == nil ||
		apiErr.Status != 409 {
		t.Fatalf("expired cutover relaxed to legacy ingestion: %v", apiErr)
	}
}

func newMultiDeviceTestApp(
	t *testing.T,
	doc ConfigDocument,
	registry contracts.DeviceRegistry,
	mapping contracts.LegacyMappingDocument,
) *App {
	t.Helper()
	return newMultiDeviceTestAppRaw(t, doc, registry, mapping, false)
}

func newMultiDeviceTestAppRaw(
	t *testing.T,
	doc ConfigDocument,
	registry any,
	mapping any,
	omitMapping bool,
) *App {
	t.Helper()
	directory := t.TempDir()
	configPath := filepath.Join(directory, "config.json")
	statsPath := filepath.Join(directory, "stats.json")
	persistencePath := filepath.Join(directory, "state-v2.json")
	registryPath := filepath.Join(directory, "registry.json")
	mappingPath := filepath.Join(directory, "legacy-mapping.json")
	writeJSONTestFile(t, configPath, doc)
	writeJSONTestFile(t, registryPath, registry)
	if !omitMapping {
		writeJSONTestFile(t, mappingPath, mapping)
	}
	app, err := NewApp(Options{
		ConfigPath: configPath, StatsPath: statsPath,
		PersistencePath: persistencePath, RegistryPath: registryPath,
		LegacyMappingPath: mappingPath, WebDir: directory,
		HTTPAddr: "127.0.0.1:0", AgentAddr: "127.0.0.1:0",
		AdminToken: "test-token",
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Close)
	return app
}

func writeJSONTestFile(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
}

func testRegistry(devices ...contracts.RegistryDevice) contracts.DeviceRegistry {
	return contracts.DeviceRegistry{
		Version: 1,
		Defaults: contracts.RegistryDefaults{
			DefaultDeviceID: devices[0].ID,
			StaleSeconds:    30,
			OfflineSeconds:  60,
		},
		Devices: devices,
	}
}

func testRegistryDevice(
	id string,
	displayName string,
	order int,
	enabled bool,
	mode string,
	expectedFQDN *string,
) contracts.RegistryDevice {
	protocol := "device_v2"
	if mode == "legacy" {
		protocol = "legacy_single_device"
	}
	return contracts.RegistryDevice{
		ID: id, DisplayName: displayName, ExpectedFQDN: expectedFQDN,
		Enabled: &enabled, Order: order, Tags: []string{},
		Ingestion: contracts.IngestionOwnership{
			Mode: mode, ActiveProtocol: &protocol,
		},
	}
}
