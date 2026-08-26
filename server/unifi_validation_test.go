package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func unifiString(value string) *string  { return &value }
func unifiInt64(value int64) *int64     { return &value }
func unifiInt(value int) *int           { return &value }
func unifiFloat(value float64) *float64 { return &value }

func validUniFiFixture(profile string) UniFiStats {
	now := "2026-08-27T01:02:03Z"
	return UniFiStats{
		Configured: true, Profile: unifiString(profile),
		Transport: UniFiTransportStats{Status: UniFiTransportAvailable, LastAttempt: &now, LastSuccess: &now},
		System: &UniFiSystemStats{
			CPUUsageReason: unifiString("insufficient_delta"), CPUTemperatureC: unifiFloat(67.1), UptimeSeconds: unifiFloat(1234.5),
			Memory:      &UniFiMemoryStats{TotalBytes: unifiInt64(4096), AvailableBytes: unifiInt64(1024), FreeBytes: unifiInt64(512), BuffersBytes: unifiInt64(128), CachedBytes: unifiInt64(384), SwapTotalBytes: unifiInt64(0), SwapFreeBytes: unifiInt64(0), UsedBytes: unifiInt64(3072), UsedPercent: unifiFloat(75), AvailableSource: "mem_available"},
			LoadAverage: &UniFiLoadAverage{OneMinute: unifiFloat(0.1), FiveMinutes: unifiFloat(0.2), FifteenMinutes: unifiFloat(0.3)},
		},
		Fans:          []UniFiFanStats{{ID: "fan1", Supported: UniFiCapabilitySupported, Present: UniFiPresenceUnknown, Observed: true, RPM: unifiInt(0), State: UniFiObservationObservedZeroRPM}},
		PowerSupplies: make([]UniFiPowerStats, 0),
		Storage:       UniFiStorageStats{NVMe: UniFiStorageCapability{Supported: UniFiCapabilityUnknown, Present: UniFiPresenceUnknown, Observed: false}},
		Diagnostics:   UniFiDiagnostics{CollectionStatus: "not_collected", Ignored: make([]UniFiIgnoredObservation, 0)},
		UpdatedAt:     &now, Stale: false, Error: nil,
	}
}

func TestUniFiValidationDisabledAndProfiles(t *testing.T) {
	disabled := NewNotReportedUniFiStats()
	if err := ValidateUniFiStats(&disabled); err != nil {
		t.Fatalf("disabled telemetry rejected: %v", err)
	}
	for _, profile := range []string{"udw", "ucg-max"} {
		stats := validUniFiFixture(profile)
		raw, err := json.Marshal(stats)
		if err != nil {
			t.Fatal(err)
		}
		decoded, err := DecodeUniFiStatsJSON(raw)
		if err != nil {
			t.Fatalf("%s valid fixture rejected: %v", profile, err)
		}
		if decoded.Profile == nil || *decoded.Profile != profile || decoded.Fans[0].RPM == nil || *decoded.Fans[0].RPM != 0 || decoded.Fans[0].Present != UniFiPresenceUnknown {
			t.Fatalf("%s profile projection changed: %#v", profile, decoded)
		}
	}
}

func TestUniFiPartialObservationIsValid(t *testing.T) {
	stats := validUniFiFixture("udw")
	stats.Diagnostics.CollectionStatus = "partial"
	if err := ValidateUniFiStats(&stats); err != nil {
		t.Fatalf("partial optional diagnostics should not invalidate generic telemetry: %v", err)
	}
}

func TestUniFiRejectsUnknownFieldsEnumsAndArrays(t *testing.T) {
	stats := validUniFiFixture("ucg-max")
	raw, _ := json.Marshal(stats)
	var object map[string]any
	if err := json.Unmarshal(raw, &object); err != nil {
		t.Fatal(err)
	}
	object["remote_command"] = "cat /etc/shadow"
	raw, _ = json.Marshal(object)
	_, err := DecodeUniFiStatsJSON(raw)
	assertValidationError(t, err, validationCodeUnknownField)
	if strings.Contains(err.Error(), "remote_command") {
		t.Fatalf("forbidden key leaked: %v", err)
	}
	stats = validUniFiFixture("ucg-max")
	stats.Fans[0].Present = "maybe"
	if err := ValidateUniFiStats(&stats); err == nil {
		t.Fatal("invalid presence enum accepted")
	}
	stats = validUniFiFixture("udw")
	stats.Fans = make([]UniFiFanStats, MaxUniFiFans+1)
	for index := range stats.Fans {
		stats.Fans[index] = UniFiFanStats{ID: "fan" + string(rune('a'+index)), Supported: UniFiCapabilitySupported, Present: UniFiPresenceUnknown, State: UniFiObservationNotObserved}
	}
	if err := ValidateUniFiStats(&stats); err == nil {
		t.Fatal("unbounded fan list accepted")
	}
}

func TestUniFiMalformedPayloadIsSafelyDegraded(t *testing.T) {
	payload := structuredUpdatePayload(t, "update-normal.json", nil)
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	fields["unifi"] = json.RawMessage(`{"configured":true,"remote_command":"id"}`)
	payload, _ = json.Marshal(fields)
	_, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 1 || issues[0].Domain != "unifi" || extension.UniFi == nil || extension.UniFi.Profile == nil || *extension.UniFi.Profile != "unknown" {
		t.Fatalf("invalid UniFi payload was not safely isolated: issues=%#v domain=%#v", issues, extension.UniFi)
	}
	if err := ValidateUniFiStats(extension.UniFi); err != nil {
		t.Fatalf("safe degraded UniFi state is not persistable: %v", err)
	}
}

func TestUniFiTransportFailureAndDeviceStatusIsolation(t *testing.T) {
	stats := validUniFiFixture("udw")
	stats.Transport.Status = UniFiTransportUnavailable
	stats.Stale = true
	stats.System = nil
	stats.UpdatedAt = nil
	stats.Error = &ExtensionError{Code: "ssh_transport_failure", Message: "UniFi SSH transport is unavailable", Source: "unifi", Retryable: true}
	if err := ValidateUniFiStats(&stats); err != nil {
		t.Fatalf("structured transport failure rejected: %v", err)
	}
	base := newNotReportedExtensionStats()
	base.UniFi = &stats
	if extensionHasBusinessError(base) {
		t.Fatal("UniFi remote transport failure must not degrade the host device")
	}
	app := newTestApp(t, minimalTestConfig())
	connectNodeForUpdate(app, 71)
	if !app.updateAgent("s01", 71, AgentStats{CPU: 1}, base) {
		t.Fatal("fresh Device v2 update was rejected")
	}
	node := app.nodes["s01"]
	if node.IdentityError || app.deviceStatusAt(node, time.Now()) != "online" {
		t.Fatalf("UniFi failure changed device identity or online state: %#v", node)
	}
}

func TestUniFiPersistenceRestoreAndStatsProjection(t *testing.T) {
	now := time.Date(2026, 8, 27, 1, 2, 3, 0, time.UTC)
	unifi := validUniFiFixture("ucg-max")
	hardware, docker, hermes := NewNotReportedHardwareStats(), NewNotReportedDockerStats(), NewNotReportedHermesStats()
	node := &NodeState{DeviceID: "device-alpha", ProtocolMode: "device_v2", HasUpdate: true, Extension: extensionSnapshotAt(ExtensionStats{ExtensionVersion: ExtensionSchemaVersion, Hardware: &hardware, Docker: &docker, Hermes: &hermes, UniFi: &unifi}, now)}
	persisted, err := persistedDeviceFromNode(&App{}, node, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := persisted.Domains["unifi"]; !ok {
		t.Fatalf("UniFi was not persisted: %#v", persisted.Domains)
	}
	restored := &NodeState{Extension: newNotReportedExtensionSnapshot(now)}
	if err := restorePersistedDeviceFields(restored, persisted); err != nil {
		t.Fatal(err)
	}
	if restored.Extension.UniFi == nil || restored.Extension.UniFi.Profile == nil || *restored.Extension.UniFi.Profile != "ucg-max" {
		t.Fatalf("UniFi was not restored: %#v", restored.Extension.UniFi)
	}
	forceExtensionStale(&restored.Extension)
	if !restored.Extension.UniFi.Stale || restored.Extension.UniFi.Error == nil {
		t.Fatalf("restored UniFi telemetry appeared fresh: %#v", restored.Extension.UniFi)
	}
	app := newTestApp(t, minimalTestConfig())
	app.nodes["s01"].Extension.UniFi = &unifi
	server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	if _, ok := server["unifi"].(*UniFiStats); !ok {
		t.Fatalf("stats omitted UniFi projection: %#v", server)
	}
}
