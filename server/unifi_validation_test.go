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
	powerSupported := profile == "udw"
	powerSlots := 0
	var maxPower *float64
	if powerSupported {
		powerSlots = 2
		maxPower = unifiFloat(550)
	}
	return UniFiStats{
		Configured: true, Profile: unifiString(profile),
		Transport: UniFiTransportStats{Status: UniFiTransportAvailable, LastAttempt: &now, LastSuccess: &now},
		System: &UniFiSystemStats{
			CPUUsageReason: unifiString("insufficient_delta"), CPUTemperatureC: unifiFloat(67.1), UptimeSeconds: unifiFloat(1234.5),
			Memory:      &UniFiMemoryStats{TotalBytes: unifiInt64(4096), AvailableBytes: unifiInt64(1024), FreeBytes: unifiInt64(512), BuffersBytes: unifiInt64(128), CachedBytes: unifiInt64(384), SwapTotalBytes: unifiInt64(0), SwapFreeBytes: unifiInt64(0), UsedBytes: unifiInt64(3072), UsedPercent: unifiFloat(75), AvailableSource: "mem_available"},
			LoadAverage: &UniFiLoadAverage{OneMinute: unifiFloat(0.1), FiveMinutes: unifiFloat(0.2), FifteenMinutes: unifiFloat(0.3)},
		},
		Fans:          []UniFiFanStats{{ID: "fan1", Supported: UniFiCapabilitySupported, Present: UniFiPresencePresent, Observed: true, RPM: unifiInt(0), State: UniFiObservationObservedZeroRPM}},
		Power:         &UniFiPowerProfile{Supported: powerSupported, PSUSlots: powerSlots, MaxPowerW: maxPower},
		PoE:           &UniFiPoEProfile{Supported: powerSupported, PortMaxPowerW: map[string]float64{}},
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
		expectedPower := profile == "udw"
		if decoded.Profile == nil || *decoded.Profile != profile || decoded.Fans[0].RPM == nil || *decoded.Fans[0].RPM != 0 || decoded.Fans[0].Present != UniFiPresencePresent || decoded.Power == nil || decoded.Power.Supported != expectedPower || decoded.PoE == nil || decoded.PoE.Supported != expectedPower {
			t.Fatalf("%s profile projection changed: %#v", profile, decoded)
		}
	}
}

func TestUniFiAPIFailureAndSuccessProjectionRoundTrip(t *testing.T) {
	stats := validUniFiFixture("udw")
	now := "2026-08-27T01:02:03Z"
	status := 401
	stats.API = &UniFiAPIStats{
		Enabled: true, Status: "unavailable", LastAttempt: &now,
		LastSuccess: nil, Endpoints: []UniFiAPIEndpoint{{Name: "info", Status: "error", HTTPStatus: &status, Error: &ExtensionError{Code: "api_auth_failure", Message: "UniFi API authentication failed", Source: "unifi-api", Retryable: true, HTTPStatus: &status}}},
		Error: &ExtensionError{Code: "api_auth_failure", Message: "UniFi API authentication failed", Source: "unifi-api", Retryable: true, HTTPStatus: &status},
	}
	if err := ValidateUniFiStats(&stats); err != nil {
		t.Fatalf("API failure projection rejected: %v", err)
	}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeUniFiStatsJSON(raw)
	if err != nil {
		t.Fatalf("API projection round trip rejected: %v", err)
	}
	if decoded.API == nil || decoded.API.Status != "unavailable" || decoded.API.Error == nil || decoded.API.Error.Code != "api_auth_failure" {
		t.Fatalf("API projection changed: %#v", decoded.API)
	}
}

func TestUniFiAPIDisabledArraysRemainEmpty(t *testing.T) {
	stats := NewNotReportedUniFiStats()
	disabled := "disabled"
	stats.API = &UniFiAPIStats{
		Enabled: false, Status: disabled, Endpoints: []UniFiAPIEndpoint{},
	}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeUniFiStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.API == nil || decoded.API.Endpoints == nil {
		t.Fatal("disabled API endpoints must remain an empty array")
	}
}

func TestUniFiAPITelemetryProjectionAndPartialFailure(t *testing.T) {
	stats := validUniFiFixture("udw")
	now := "2026-08-27T01:02:03Z"
	status := 200
	stats.API = &UniFiAPIStats{
		Enabled: true, Status: "available", LastAttempt: &now, LastSuccess: &now,
		Endpoints: []UniFiAPIEndpoint{
			{Name: "info", Status: "ok", HTTPStatus: &status},
			{Name: "sites", Status: "ok", HTTPStatus: &status},
			{Name: "devices", Status: "ok", HTTPStatus: &status},
			{Name: "clients", Status: "ok", HTTPStatus: &status},
			{Name: "networks", Status: "ok", HTTPStatus: &status}, {Name: "legacy_stat_device", Status: "ok", HTTPStatus: &status}, {Name: "lags", Status: "ok", HTTPStatus: &status}, {Name: "topology", Status: "ok", HTTPStatus: &status}, {Name: "port_anomalies", Status: "ok", HTTPStatus: &status}, {Name: "wan_official", Status: "ok", HTTPStatus: &status}, {Name: "wan_enriched", Status: "ok", HTTPStatus: &status}, {Name: "wan_isp_status", Status: "ok", HTTPStatus: &status}, {Name: "wan_load_balance", Status: "ok", HTTPStatus: &status}, {Name: "wan_slas", Status: "ok", HTTPStatus: &status},
		},
		Summary: &UniFiAPISummary{Model: unifiString("UDW"), Firmware: unifiString("5.0.1"), ApplicationVersion: unifiString("9.1.2")},
		Telemetry: &UniFiAPITelemetry{
			Site:         &UniFiAPISite{IntegrationID: unifiString("uuid-1"), InternalReference: unifiString("default"), Name: unifiString("Main")},
			Identity:     &UniFiAPIIdentity{Model: unifiString("UDW"), DisplayName: unifiString("Gateway"), Firmware: unifiString("5.0.1"), Status: unifiString("online"), UptimeSeconds: unifiFloat(1234)},
			Controller:   &UniFiAPIController{ApplicationVersion: unifiString("9.1.2"), Build: unifiString("build-1"), UpdateAvailable: func() *bool { value := false; return &value }(), State: unifiString("healthy")},
			WANs:         []UniFiAPIWAN{{ID: unifiString("wan1"), NetworkGroup: unifiString("wan"), Role: unifiString("active"), ASN: unifiString("64500"), Name: unifiString("WAN1"), Interface: unifiString("eth0"), ISP: unifiString("Example ISP"), LinkState: unifiString("up"), Online: func() *bool { value := true; return &value }(), Speedtest: &UniFiAPISpeedtest{Observed: true, Timestamp: unifiString(now), LatencyMs: unifiFloat(2.5), DownloadMbps: unifiFloat(900), UploadMbps: unifiFloat(100)}, RxBPS: unifiInt64(0), TxBPS: unifiInt64(123)}},
			Uplinks:      []UniFiAPIUplink{{Name: unifiString("eth0"), LinkState: unifiString("up"), SpeedMbps: unifiFloat(1000), DeviceID: unifiString("udw-1"), ManagementIP: unifiString("192.168.1.1"), Model: unifiString("UDW"), DeviceType: unifiString("gateway"), Online: func() *bool { value := true; return &value }()}},
			Temperatures: []UniFiAPITemperature{{ID: "cpu", Label: "CPU", Celsius: 64.5, Source: "unifi-api"}},
			Clients:      &UniFiAPIClientSummary{Total: 2, Wired: unifiInt(1), Wireless: unifiInt(1), Observed: true},
			Devices:      &UniFiAPIDeviceSummary{Total: 2, Online: 2, Offline: 0, ByType: map[string]int{"gateway": 1, "switch": 1}},
			Networks:     &UniFiAPINetworkSummary{Total: 2, VLAN: 1},
		},
	}
	if err := ValidateUniFiStats(&stats); err != nil {
		t.Fatalf("API telemetry rejected: %v", err)
	}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeUniFiStatsJSON(raw)
	if err != nil {
		t.Fatalf("API telemetry round trip rejected: %v", err)
	}
	if decoded.API == nil || decoded.API.Telemetry == nil || decoded.API.Telemetry.Site == nil || decoded.API.Telemetry.WANs[0].Speedtest == nil || *decoded.API.Telemetry.WANs[0].Speedtest.DownloadMbps != 900 || decoded.API.Telemetry.Uplinks[0].DeviceID == nil || *decoded.API.Telemetry.Uplinks[0].DeviceID != "udw-1" {
		t.Fatalf("API telemetry was not preserved: %#v", decoded.API)
	}

	partial := stats
	partial.API = &UniFiAPIStats{
		Enabled: true, Status: "partial", LastAttempt: &now, LastSuccess: &now,
		Endpoints: []UniFiAPIEndpoint{{Name: "info", Status: "ok", HTTPStatus: &status}, {Name: "devices", Status: "error", HTTPStatus: func() *int { value := 401; return &value }(), Error: &ExtensionError{Code: "api_auth_failure", Message: "UniFi API authentication failed", Source: "unifi-api", Retryable: true, HTTPStatus: func() *int { value := 401; return &value }()}}},
		Telemetry: &UniFiAPITelemetry{Identity: &UniFiAPIIdentity{Model: unifiString("UDW")}, WANs: []UniFiAPIWAN{}, Uplinks: []UniFiAPIUplink{}, Temperatures: []UniFiAPITemperature{}, Clients: nil, Devices: nil, Networks: nil},
		Error:     &ExtensionError{Code: "api_partial_failure", Message: "UniFi API returned a partial observation", Source: "unifi-api", Retryable: true},
	}
	if err := ValidateUniFiStats(&partial); err != nil {
		t.Fatalf("partial API telemetry rejected: %v", err)
	}
}

func TestUniFiAPIPortTelemetryRoundTripAndNoRawTable(t *testing.T) {
	stats := validUniFiFixture("udw")
	now := "2026-08-27T01:02:03Z"
	status := 200
	poePower := 3.32
	maxPoePower := 30.0
	peerCount := 1
	stats.API = &UniFiAPIStats{
		Enabled: true, Status: "available", LastAttempt: &now, LastSuccess: &now,
		Endpoints: []UniFiAPIEndpoint{{Name: "info", Status: "ok", HTTPStatus: &status}},
		Telemetry: &UniFiAPITelemetry{
			Identity: &UniFiAPIIdentity{Model: unifiString("UDW")},
			WANs:     []UniFiAPIWAN{}, Uplinks: []UniFiAPIUplink{}, Temperatures: []UniFiAPITemperature{},
			Ports:       []UniFiAPIPort{{DeviceID: "udw-1", PortIndex: 7, Name: unifiString("LAN 7"), Media: unifiString("2.5GE"), Up: func() *bool { v := true; return &v }(), SpeedMbps: unifiFloat(2500), MaxSpeedMbps: unifiFloat(2500), RxBytes: unifiInt64(100), TxBytes: unifiInt64(200), RxBPS: unifiInt64(1000), TxBPS: unifiInt64(2000), PoE: &UniFiAPIPoE{Supported: func() *bool { v := true; return &v }(), PowerW: &poePower, MaxPowerW: &maxPoePower}, PeerCount: &peerCount}},
			PortSummary: &UniFiAPIPortSummary{Total: 1, Up: 1, Down: 0, PoEActive: 1, PoETotalPowerW: &poePower},
			LAGs:        []UniFiAPILAG{}, Topology: nil, Anomalies: nil,
		},
		Error: nil,
	}
	if err := ValidateUniFiStats(&stats); err != nil {
		t.Fatalf("port telemetry rejected: %v", err)
	}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "mac_table") || strings.Contains(string(raw), "mac_address") {
		t.Fatal("raw MAC table fields must not be projected")
	}
	decoded, err := DecodeUniFiStatsJSON(raw)
	if err != nil {
		t.Fatalf("port telemetry round trip rejected: %v", err)
	}
	if decoded.API == nil || decoded.API.Telemetry == nil || len(decoded.API.Telemetry.Ports) != 1 || decoded.API.Telemetry.Ports[0].MaxSpeedMbps == nil || decoded.API.Telemetry.Ports[0].PoE == nil || decoded.API.Telemetry.Ports[0].PoE.PowerW == nil || decoded.API.Telemetry.Ports[0].PoE.MaxPowerW == nil {
		t.Fatalf("port telemetry was not preserved: %#v", decoded.API)
	}
}

func TestUniFiStorageMediaCapabilitiesRoundTrip(t *testing.T) {
	stats := validUniFiFixture("udw")
	capacity := int64(128000000000)
	filesystemTotal := int64(109000000000)
	used := int64(106000000000)
	available := int64(3000000000)
	stats.Storage.SATA = &UniFiStorageCapability{
		Supported: UniFiCapabilitySupported, Present: UniFiPresencePresent,
		Observed: true, CapacityBytes: &capacity, FilesystemTotalBytes: &filesystemTotal,
		UsedBytes: &used, AvailableBytes: &available, UsagePercent: unifiFloat(97.25),
	}
	stats.Storage.TF = &UniFiStorageCapability{
		Supported: UniFiCapabilitySupported, Present: UniFiPresencePresent,
		Observed: false,
	}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeUniFiStatsJSON(raw)
	if err != nil {
		t.Fatalf("storage capability payload rejected: %v", err)
	}
	if decoded.Storage.SATA == nil || decoded.Storage.SATA.CapacityBytes == nil || *decoded.Storage.SATA.CapacityBytes != capacity || decoded.Storage.SATA.FilesystemTotalBytes == nil || *decoded.Storage.SATA.FilesystemTotalBytes != filesystemTotal || decoded.Storage.SATA.UsedBytes == nil || *decoded.Storage.SATA.UsedBytes != used {
		t.Fatalf("SATA capability was not preserved: %#v", decoded.Storage.SATA)
	}
	if decoded.Storage.TF == nil || decoded.Storage.TF.Present != UniFiPresencePresent {
		t.Fatalf("TF capability was not preserved: %#v", decoded.Storage.TF)
	}
	bad := stats
	negative := int64(-1)
	bad.Storage.SATA = &UniFiStorageCapability{Supported: UniFiCapabilitySupported, Present: UniFiPresencePresent, CapacityBytes: &negative}
	if err := ValidateUniFiStats(&bad); err == nil {
		t.Fatal("negative storage capacity accepted")
	}
	tooMuch := int64(110000000000)
	bad.Storage.SATA = &UniFiStorageCapability{Supported: UniFiCapabilitySupported, Present: UniFiPresencePresent, FilesystemTotalBytes: &filesystemTotal, UsedBytes: &tooMuch}
	if err := ValidateUniFiStats(&bad); err == nil {
		t.Fatal("filesystem usage above total accepted")
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
	if node.IdentityError || node.Degraded {
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

func syntheticUniFiAPIPortStats(ports []UniFiAPIPort) UniFiStats {
	stats := validUniFiFixture("ucg-max")
	now := "2026-08-27T01:02:03Z"
	stats.API = &UniFiAPIStats{
		Enabled: true, Status: "available", LastAttempt: &now, LastSuccess: &now,
		Telemetry: &UniFiAPITelemetry{Ports: ports, WANs: []UniFiAPIWAN{}, Uplinks: []UniFiAPIUplink{}, Temperatures: []UniFiAPITemperature{}},
	}
	return stats
}

func syntheticUniFiPorts(count int) []UniFiAPIPort {
	ports := make([]UniFiAPIPort, count)
	for index := range ports {
		ports[index] = UniFiAPIPort{DeviceID: "device-" + string(rune('a'+index/64)), PortIndex: index%64 + 1}
	}
	return ports
}

func TestUniFiSitePortObservationLimitAndUniqueJoinKey(t *testing.T) {
	for _, count := range []int{64, 65, 97, MaxUniFiSitePortObservations} {
		stats := syntheticUniFiAPIPortStats(syntheticUniFiPorts(count))
		if err := ValidateUniFiStats(&stats); err != nil {
			t.Fatalf("port count %d rejected: %v", count, err)
		}
	}

	over := syntheticUniFiAPIPortStats(syntheticUniFiPorts(MaxUniFiSitePortObservations + 1))
	assertValidationError(t, ValidateUniFiStats(&over), validationCodeInvalidValue)

	duplicate := syntheticUniFiAPIPortStats([]UniFiAPIPort{
		{DeviceID: "device-a", PortIndex: 1},
		{DeviceID: "device-a", PortIndex: 1},
	})
	duplicateErr := ValidateUniFiStats(&duplicate)
	assertValidationError(t, duplicateErr, validationCodeInvalidValue)
	duplicateValidation, ok := duplicateErr.(*ExtensionValidationError)
	if !ok || duplicateValidation.Field != "unifi.api.telemetry.ports" || duplicateValidation.Message != "contains duplicate device_id and port_idx" {
		t.Fatalf("duplicate port key diagnostics changed: %#v", duplicateErr)
	}

	invalidIndex := syntheticUniFiAPIPortStats([]UniFiAPIPort{{DeviceID: "device-a", PortIndex: 0}})
	invalidIndexErr := ValidateUniFiStats(&invalidIndex)
	assertValidationError(t, invalidIndexErr, validationCodeInvalidValue)
	invalidIndexValidation, ok := invalidIndexErr.(*ExtensionValidationError)
	if !ok || invalidIndexValidation.Field != "unifi.api.telemetry.ports[0].port_idx" {
		t.Fatalf("invalid port index field changed: %#v", invalidIndexErr)
	}

	malformedID := syntheticUniFiAPIPortStats([]UniFiAPIPort{{DeviceID: "", PortIndex: 1}})
	malformedIDErr := ValidateUniFiStats(&malformedID)
	assertValidationError(t, malformedIDErr, validationCodeInvalidValue)
	malformedIDValidation, ok := malformedIDErr.(*ExtensionValidationError)
	if !ok || malformedIDValidation.Field != "unifi.api.telemetry.ports[0].device_id" {
		t.Fatalf("malformed device id field changed: %#v", malformedIDErr)
	}

	raw, err := json.Marshal(syntheticUniFiAPIPortStats(syntheticUniFiPorts(97)))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodeUniFiStatsJSON(raw); err != nil {
		t.Fatalf("97-port strict JSON fixture rejected: %v", err)
	}
}
