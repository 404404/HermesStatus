package main

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestDecodeAgentUpdateStructuredAndNativeFields(t *testing.T) {
	payload := structuredUpdatePayload(t, "update-normal.json", map[string]any{
		"cpu": 37.5, "memory_total": 8192, "memory_used": 2048,
		"hdd_total": 120000, "hdd_used": 30000, "network_in": 1234,
	})
	native, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("unexpected extension issues: %#v", issues)
	}
	if native.CPU != 37.5 || native.MemoryTotal != 8192 || native.HDDUsed != 30000 || native.NetworkIn != 1234 {
		t.Fatalf("native fields changed during extension decode: %#v", native)
	}
	if extension.Hardware.CPUModel == nil || *extension.Hardware.CPUModel != "Example CPU 4-Core" {
		t.Fatalf("structured hardware was not decoded: %#v", extension.Hardware)
	}
	if len(extension.Docker.Containers) != 3 || extension.Docker.Containers[0].Names != "status-server" {
		t.Fatalf("Docker data was not decoded: %#v", extension.Docker)
	}
	if len(extension.Hermes.Profiles) != 2 {
		t.Fatalf("Hermes profiles were not decoded: %#v", extension.Hermes)
	}
	if extension.Lucky == nil || extension.Lucky.Status != LuckyStatusOK || extension.Lucky.Certificates.Total != 3 {
		t.Fatalf("Lucky data was not decoded: %#v", extension.Lucky)
	}
}

func TestDecodeAgentUpdateLegacyDomains(t *testing.T) {
	payload := legacyUpdatePayload(t, "update-normal.json", map[string]any{"cpu": 22.5, "memory_total": 4096})
	native, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("unexpected legacy issues: %#v", issues)
	}
	if native.CPU != 22.5 || native.MemoryTotal != 4096 {
		t.Fatalf("legacy decode changed native metrics: %#v", native)
	}
	if extension.Hardware.CPUModel == nil || extension.Docker.Total != 3 || len(extension.Hermes.Profiles) != 2 {
		t.Fatalf("legacy domains were not normalized: %#v", extension)
	}
	encoded, err := json.Marshal(extension)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), "_json") || strings.Contains(string(encoded), "/usr/local/bin/status-server") {
		t.Fatalf("legacy raw data survived normalization: %s", encoded)
	}
}

func TestStructuredDomainTakesPriorityOverLegacy(t *testing.T) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(structuredUpdatePayload(t, "update-normal.json", nil), &fields); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"hardware_json", "docker_json", "hermes_json"} {
		fields[field] = mustRawJSON(t, "not a JSON object")
	}
	payload, _ := json.Marshal(fields)
	_, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 || extension.Docker.Total != 3 || len(extension.Hermes.Profiles) != 2 {
		t.Fatalf("legacy field was not ignored: issues=%#v extension=%#v", issues, extension)
	}
}

func TestNativeClientGetsStableNotReportedDomains(t *testing.T) {
	native, extension, issues, err := decodeAgentUpdate([]byte(`{"cpu":19.5,"memory_total":1024,"hdd_total":2048}`))
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 || native.CPU != 19.5 {
		t.Fatalf("native update was not preserved: native=%#v issues=%#v", native, issues)
	}
	for domain, extensionError := range map[string]*ExtensionError{
		"hardware": extension.Hardware.Error,
		"docker":   extension.Docker.Error,
		"hermes":   extension.Hermes.Error,
		"lucky":    extension.Lucky.Error,
	} {
		if extensionError == nil || extensionError.Code != "not_reported" {
			t.Fatalf("%s did not receive not_reported: %#v", domain, extensionError)
		}
	}
	if extension.Docker.Containers == nil || extension.Hermes.Profiles == nil || extension.Lucky.DynamicDNS.Records == nil || extension.Lucky.Certificates.Items == nil {
		t.Fatal("default collections must be non-nil")
	}
}

func TestStructuredUpdateRequiresSupportedVersion(t *testing.T) {
	payload := structuredUpdatePayload(t, "update-normal.json", map[string]any{"cpu": 55})
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	delete(fields, "extension_version")
	payload, _ = json.Marshal(fields)
	native, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if native.CPU != 55 || len(issues) != 5 {
		t.Fatalf("version failure did not preserve native update: native=%#v issues=%#v", native, issues)
	}
	for _, extensionError := range []*ExtensionError{extension.Hardware.Error, extension.Docker.Error, extension.Hermes.Error, extension.Lucky.Error} {
		if extensionError == nil || extensionError.Code != validationCodeMissingField {
			t.Fatalf("structured domain was accepted without version: %#v", extensionError)
		}
	}
}

func TestDecodeAgentUpdateKeepsGlobalSizeLimit(t *testing.T) {
	_, _, _, err := decodeAgentUpdate(make([]byte, maxRequestBody+1))
	if err == nil {
		t.Fatal("oversized update was accepted")
	}
}

func TestInvalidStructuredDomainDoesNotBlockNativeOrOtherDomains(t *testing.T) {
	payload := structuredUpdatePayload(t, "update-normal.json", map[string]any{"cpu": 61, "memory_used": 333})
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	var hardware map[string]any
	if err := json.Unmarshal(fields["hardware"], &hardware); err != nil {
		t.Fatal(err)
	}
	hardware["unexpected_extension_field"] = "password=must-not-appear"
	fields["hardware"] = mustRawJSON(t, hardware)
	payload, _ = json.Marshal(fields)

	native, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if native.CPU != 61 || native.MemoryUsed != 333 {
		t.Fatalf("native fields were lost: %#v", native)
	}
	if extension.Hardware.Error == nil || extension.Hardware.Error.Code != validationCodeUnknownField {
		t.Fatalf("hardware was not degraded safely: %#v", extension.Hardware)
	}
	if extension.Docker.Total != 3 || len(extension.Hermes.Profiles) != 2 {
		t.Fatalf("valid domains were discarded: %#v", extension)
	}
	if len(issues) != 1 || issues[0].Domain != "hardware" || issues[0].Code != validationCodeUnknownField {
		t.Fatalf("unexpected issues: %#v", issues)
	}
	encoded, _ := json.Marshal(extension)
	if strings.Contains(string(encoded), "must-not-appear") || strings.Contains(string(encoded), "unexpected_extension_field") {
		t.Fatalf("invalid domain content leaked: %s", encoded)
	}
}

func TestLegacyDomainLimitsAndObjectRequirement(t *testing.T) {
	tests := []struct {
		name  string
		value string
		code  string
	}{
		{"too-large", strings.Repeat(" ", MaxLegacyHardwareJSONBytes) + `{}`, validationCodePayloadTooLarge},
		{"not-object", `[]`, validationCodeInvalidJSON},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			payload := mustRawJSON(t, map[string]any{"cpu": 48, "hardware_json": test.value})
			native, extension, issues, err := decodeAgentUpdate(payload)
			if err != nil {
				t.Fatal(err)
			}
			if native.CPU != 48 || len(issues) != 1 || issues[0].Code != test.code {
				t.Fatalf("unexpected decode result: native=%#v issues=%#v", native, issues)
			}
			if extension.Hardware.Error == nil || extension.Hardware.Error.Code != test.code {
				t.Fatalf("legacy domain was not degraded: %#v", extension.Hardware)
			}
		})
	}
}

func TestExtensionSecretsAreCleanedBeforeState(t *testing.T) {
	payload := structuredUpdatePayload(t, "update-normal.json", nil)
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(payload, &fields)
	var hardware map[string]any
	var dockerStats map[string]any
	var hermesStats map[string]any
	_ = json.Unmarshal(fields["hardware"], &hardware)
	_ = json.Unmarshal(fields["docker"], &dockerStats)
	_ = json.Unmarshal(fields["hermes"], &hermesStats)
	hardware["cpu_model"] = "password=private-value"
	dockerStats["containers"].([]any)[0].(map[string]any)["image"] = "image?token=private-value"
	hermesStats["profiles"].([]any)[0].(map[string]any)["provider"] = "api_key=private-value"
	fields["hardware"] = mustRawJSON(t, hardware)
	fields["docker"] = mustRawJSON(t, dockerStats)
	fields["hermes"] = mustRawJSON(t, hermesStats)
	payload, _ = json.Marshal(fields)

	_, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil || len(issues) != 0 {
		t.Fatalf("secret cleaning should preserve valid structure: err=%v issues=%#v", err, issues)
	}
	encoded, _ := json.Marshal(extension)
	if strings.Contains(string(encoded), "private-value") || !strings.Contains(string(encoded), RedactedValue) {
		t.Fatalf("sanitized extension is unsafe: %s", encoded)
	}
}

func TestNodeStateContainsOnlyStructuredExtensionState(t *testing.T) {
	typeOf := reflect.TypeOf(NodeState{})
	for _, name := range []string{"HardwareJSON", "DockerJSON", "HermesJSON"} {
		if _, ok := typeOf.FieldByName(name); ok {
			t.Fatalf("NodeState contains legacy field %s", name)
		}
	}
	node := NodeState{Extension: newNotReportedExtensionSnapshot(time.Now())}
	data, err := json.Marshal(node.Extension)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "_json") {
		t.Fatalf("structured state contains a legacy field: %s", data)
	}
}

func TestSnapshotRecomputesFreshnessWithoutMutatingNodeState(t *testing.T) {
	now := time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		name      string
		threshold time.Duration
		set       func(*ExtensionStats, string)
		stale     func(ExtensionSnapshot) bool
	}{
		{"hardware", hardwareStaleAfter, func(stats *ExtensionStats, value string) { stats.Hardware.UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Hardware.Stale }},
		{"docker", dockerStaleAfter, func(stats *ExtensionStats, value string) { stats.Docker.UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Docker.Stale }},
		{"hermes", hermesStaleAfter, func(stats *ExtensionStats, value string) { stats.Hermes.UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Hermes.Stale }},
		{"profile", profileStaleAfter, func(stats *ExtensionStats, value string) { stats.Hermes.Profiles[0].UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Hermes.Profiles[0].Stale }},
		{"lucky", luckyStaleAfter, func(stats *ExtensionStats, value string) { stats.Lucky.UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Lucky.Stale }},
		{"lucky-ddns", luckyStaleAfter, func(stats *ExtensionStats, value string) { stats.Lucky.DynamicDNS.UpdatedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Lucky.DynamicDNS.Stale }},
		{"lucky-version", luckyVersionStaleAfter, func(stats *ExtensionStats, value string) { stats.Lucky.Version.CheckedAt = &value }, func(snapshot ExtensionSnapshot) bool { return snapshot.Lucky.Version.Stale }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stats := mustDecodeUpdate(t, "update-normal.json")
			exact := now.Add(-test.threshold).Format(time.RFC3339)
			test.set(stats, exact)
			if test.stale(snapshotExtension(extensionSnapshotAt(*stats, now), now)) {
				t.Fatal("value at the exact threshold was marked stale")
			}
			old := now.Add(-test.threshold - time.Second).Format(time.RFC3339)
			test.set(stats, old)
			if !test.stale(snapshotExtension(extensionSnapshotAt(*stats, now), now)) {
				t.Fatal("value beyond the threshold was not marked stale")
			}
		})
	}

	stats := mustDecodeUpdate(t, "update-normal.json")
	future := now.Add(maxFutureClockSkew + time.Second).Format(time.RFC3339)
	stats.Hardware.UpdatedAt = &future
	stats.Hardware.Stale = false
	stats.Hardware.Error = nil
	snapshot := snapshotExtension(extensionSnapshotAt(*stats, now.Add(-24*time.Hour)), now)
	if !snapshot.Hardware.Stale || snapshot.Hardware.Error == nil || snapshot.Hardware.Error.Code != "clock_skew" {
		t.Fatalf("future timestamp did not generate clock_skew: %#v", snapshot.Hardware)
	}
	if stats.Hardware.Stale || stats.Hardware.Error != nil || *stats.Hardware.UpdatedAt != future {
		t.Fatalf("snapshot mutated NodeState input: %#v", stats.Hardware)
	}

	luckyStats := mustDecodeUpdate(t, "update-normal.json")
	luckyStats.Lucky.DynamicDNS.UpdatedAt = &future
	luckyStats.Lucky.DynamicDNS.Stale = false
	luckyStats.Lucky.DynamicDNS.Error = nil
	luckySnapshot := snapshotExtension(extensionSnapshotAt(*luckyStats, now), now)
	if !luckySnapshot.Lucky.DynamicDNS.Stale || luckySnapshot.Lucky.DynamicDNS.Error == nil || luckySnapshot.Lucky.DynamicDNS.Error.Code != "clock_skew" {
		t.Fatalf("future Lucky timestamp did not generate clock_skew: %#v", luckySnapshot.Lucky.DynamicDNS)
	}
	if luckyStats.Lucky.DynamicDNS.Stale || luckyStats.Lucky.DynamicDNS.Error != nil || *luckyStats.Lucky.DynamicDNS.UpdatedAt != future {
		t.Fatalf("Lucky snapshot mutated NodeState input: %#v", luckyStats.Lucky.DynamicDNS)
	}
}

func TestSnapshotReceivedAtAndUpdatedAtAreStable(t *testing.T) {
	app := newTestApp(t, minimalTestConfig())
	extension := mustDecodeUpdate(t, "update-normal.json")
	before := time.Now().UTC()
	connectNodeForUpdate(app, 7)
	if !app.updateAgent("s01", 7, AgentStats{CPU: 43, MemoryTotal: 1000, HDDTotal: 2000}, *extension) {
		t.Fatal("update was rejected")
	}
	after := time.Now().UTC()
	first := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	receivedAt, err := time.Parse(time.RFC3339, first["received_at"].(string))
	if err != nil || receivedAt.Before(before) || receivedAt.After(after) {
		t.Fatalf("received_at was not generated by the server: %v %v", receivedAt, err)
	}
	hardware := first["hardware"].(*HardwareStats)
	wantUpdatedAt := *extension.Hardware.UpdatedAt
	if hardware.UpdatedAt == nil || *hardware.UpdatedAt != wantUpdatedAt {
		t.Fatalf("updated_at changed in first snapshot: %#v", hardware)
	}
	time.Sleep(10 * time.Millisecond)
	second := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	if second["received_at"] != first["received_at"] || *second["hardware"].(*HardwareStats).UpdatedAt != wantUpdatedAt {
		t.Fatal("stats cycle rewrote received_at or updated_at")
	}
}

func TestSnapshotEmptyArraysAndPersistenceRestartSemantics(t *testing.T) {
	app := newTestApp(t, minimalTestConfig())
	emptyServer := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	emptyJSON, _ := json.Marshal(emptyServer)
	if !strings.Contains(string(emptyJSON), `"containers":[]`) || !strings.Contains(string(emptyJSON), `"profiles":[]`) {
		t.Fatalf("not_reported collections are not arrays: %s", emptyJSON)
	}

	extension := mustDecodeUpdate(t, "update-normal.json")
	connectNodeForUpdate(app, 9)
	native := AgentStats{CPU: 31, MemoryTotal: 4096, MemoryUsed: 1024, HDDTotal: 12000, HDDUsed: 3000, NetworkIn: 500, NetworkOut: 700, OS: "example-os", CPUModel: "Example CPU"}
	if !app.updateAgent("s01", 9, native, *extension) {
		t.Fatal("update was rejected")
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	persisted, err := os.ReadFile(app.opts.StatsPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(persisted), `"hardware"`) || !strings.Contains(string(persisted), `"docker"`) || !strings.Contains(string(persisted), `"hermes"`) || !strings.Contains(string(persisted), `"lucky"`) || strings.Contains(string(persisted), "_json") {
		t.Fatalf("persisted stats do not contain a safe extension snapshot: %s", persisted)
	}

	var document map[string]any
	if err := json.Unmarshal(persisted, &document); err != nil {
		t.Fatal(err)
	}
	savedServer := document["servers"].([]any)[0].(map[string]any)
	savedServer["hardware"] = "old-or-damaged-extension"
	savedServer["hardware_json"] = "password=must-not-be-restored"
	damaged, _ := json.Marshal(document)
	if err := os.WriteFile(app.opts.StatsPath, damaged, 0o644); err != nil {
		t.Fatal(err)
	}

	restarted, err := NewApp(app.opts)
	if err != nil {
		t.Fatalf("damaged persisted extension prevented startup: %v", err)
	}
	t.Cleanup(restarted.Close)
	restartedServer := restarted.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	if restartedServer["hardware"].(*HardwareStats).Error.Code != "not_reported" || restartedServer["docker"].(*DockerStats).Error.Code != "not_reported" || restartedServer["hermes"].(*HermesStats).Error.Code != "not_reported" || restartedServer["lucky"].(*LuckyStats).Error.Code != "not_reported" {
		t.Fatalf("restart restored extension freshness: %#v", restartedServer)
	}
	if restartedServer["os"] != "example-os" || restartedServer["cpu_model"] != "Example CPU" {
		t.Fatalf("native persistent metadata was not restored: %#v", restartedServer)
	}
	if restarted.nodes["s01"].LastNetworkIn != 500 || restarted.nodes["s01"].LastNetworkOut != 700 {
		t.Fatalf("native traffic baseline was not restored: %#v", restarted.nodes["s01"])
	}
}

func TestReloadResetsExtensionToNotReported(t *testing.T) {
	app := newTestApp(t, minimalTestConfig())
	extension := mustDecodeUpdate(t, "update-normal.json")
	connectNodeForUpdate(app, 13)
	if !app.updateAgent("s01", 13, AgentStats{CPU: 25}, *extension) {
		t.Fatal("update was rejected")
	}
	if app.SnapshotStats()["servers"].([]any)[0].(map[string]any)["docker"].(*DockerStats).Total != 3 {
		t.Fatal("precondition: extension was not stored")
	}
	if apiErr := app.ReloadConfig(); apiErr != nil {
		t.Fatal(apiErr)
	}
	server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	if server["hardware"].(*HardwareStats).Error.Code != "not_reported" || server["docker"].(*DockerStats).Error.Code != "not_reported" || server["hermes"].(*HermesStats).Error.Code != "not_reported" || server["lucky"].(*LuckyStats).Error.Code != "not_reported" {
		t.Fatalf("reload retained extension freshness: %#v", server)
	}
}

func structuredUpdatePayload(t *testing.T, fixture string, native map[string]any) []byte {
	t.Helper()
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(readFixture(t, fixture), &fields); err != nil {
		t.Fatal(err)
	}
	for key, value := range native {
		fields[key] = mustRawJSON(t, value)
	}
	data, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func legacyUpdatePayload(t *testing.T, fixture string, native map[string]any) []byte {
	t.Helper()
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(readFixture(t, fixture), &fields); err != nil {
		t.Fatal(err)
	}
	delete(fields, "extension_version")
	delete(fields, "lucky")
	for domain, legacy := range map[string]string{"hardware": "hardware_json", "docker": "docker_json", "hermes": "hermes_json"} {
		fields[legacy] = mustRawJSON(t, string(fields[domain]))
		delete(fields, domain)
	}
	for key, value := range native {
		fields[key] = mustRawJSON(t, value)
	}
	data, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func mustRawJSON(t *testing.T, value any) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func connectNodeForUpdate(app *App, connectionID uint64) {
	app.nodeMu.Lock()
	node := app.nodes["s01"]
	node.Connected = true
	node.ConnectionID = connectionID
	app.nodeMu.Unlock()
}
