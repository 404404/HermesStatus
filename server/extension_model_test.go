package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func fixturePath(name string) string {
	return filepath.Join("..", "testdata", "migration", name)
}

func readFixture(t *testing.T, name string) []byte {
	t.Helper()
	data, err := os.ReadFile(fixturePath(name))
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func mustDecodeUpdate(t *testing.T, name string) *ExtensionStats {
	t.Helper()
	stats, err := DecodeExtensionStatsJSON(readFixture(t, name))
	if err != nil {
		t.Fatalf("decode %s: %v", name, err)
	}
	return stats
}

func TestExtensionModelJSONTags(t *testing.T) {
	tests := []struct {
		typeOf reflect.Type
		field  string
		tag    string
	}{
		{reflect.TypeOf(ExtensionStats{}), "ExtensionVersion", "extension_version"},
		{reflect.TypeOf(ExtensionSnapshot{}), "ReceivedAt", "received_at"},
		{reflect.TypeOf(HardwareStats{}), "DiskPowerOnHours", "disk_power_on_hours"},
		{reflect.TypeOf(DockerStats{}), "Containers", "containers"},
		{reflect.TypeOf(DockerContainerStats{}), "Names", "names"},
		{reflect.TypeOf(HermesProfileStats{}), "AuthRefreshedAt", "auth_refreshed_at"},
		{reflect.TypeOf(TokenUsageStats{}), "InputTokens", "input_tokens"},
		{reflect.TypeOf(ExtensionError{}), "HTTPStatus", "http_status"},
		{reflect.TypeOf(SanitizedConfigSummary{}), "DockerVolumes", "docker_volumes"},
	}
	for _, test := range tests {
		field, ok := test.typeOf.FieldByName(test.field)
		if !ok {
			t.Fatalf("missing field %s", test.field)
		}
		if got := strings.Split(field.Tag.Get("json"), ",")[0]; got != test.tag {
			t.Fatalf("%s json tag=%q, want %q", test.field, got, test.tag)
		}
	}
}

func TestDefaultConstructors(t *testing.T) {
	hardware := NewNotReportedHardwareStats()
	if hardware.UpdatedAt != nil || !hardware.Stale || hardware.DiskSMARTStatus != DiskSMARTUnknown || hardware.Error == nil {
		t.Fatalf("unexpected hardware default: %#v", hardware)
	}
	dockerStats := NewNotReportedDockerStats()
	if dockerStats.Containers == nil || len(dockerStats.Containers) != 0 || dockerStats.UpdatedAt != nil || !dockerStats.Stale || dockerStats.Error == nil {
		t.Fatalf("unexpected docker default: %#v", dockerStats)
	}
	hermesStats := NewNotReportedHermesStats()
	if hermesStats.Profiles == nil || len(hermesStats.Profiles) != 0 || hermesStats.UpdatedAt != nil || !hermesStats.Stale || hermesStats.Error == nil {
		t.Fatalf("unexpected hermes default: %#v", hermesStats)
	}
	luckyStats := NewNotReportedLuckyStats()
	if luckyStats.DynamicDNS.Records == nil || luckyStats.WebServices.Services == nil || luckyStats.PortForwards.Rules == nil || luckyStats.Certificates.Items == nil || !luckyStats.Stale || luckyStats.Error == nil {
		t.Fatalf("unexpected Lucky default: %#v", luckyStats)
	}
	for _, extensionError := range []*ExtensionError{hardware.Error, dockerStats.Error, hermesStats.Error, luckyStats.Error} {
		if extensionError.Code != "not_reported" || extensionError.Retryable || extensionError.HTTPStatus != nil {
			t.Fatalf("unexpected not-reported error: %#v", extensionError)
		}
	}
}

func TestUnavailableTokenUsageDefault(t *testing.T) {
	usage := NewUnavailableTokenUsageStats()
	if usage.InputTokens != nil || usage.OutputTokens != nil || usage.TotalTokens != nil || usage.WindowStart != nil || usage.WindowEnd != nil {
		t.Fatalf("unavailable usage contains values: %#v", usage)
	}
	if !usage.Estimated || usage.Source != TokenSourceUnavailable {
		t.Fatalf("unexpected unavailable usage: %#v", usage)
	}
	if err := ValidateTokenUsageStats("usage", &usage); err != nil {
		t.Fatal(err)
	}
}

func TestDefaultCollectionsMarshalAsEmptyArrays(t *testing.T) {
	payload := ExtensionStats{
		ExtensionVersion: ExtensionSchemaVersion,
		Hardware:         ptrHardware(NewNotReportedHardwareStats()),
		Docker:           ptrDocker(NewNotReportedDockerStats()),
		Hermes:           ptrHermes(NewNotReportedHermesStats()),
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if !strings.Contains(text, `"containers":[]`) || !strings.Contains(text, `"profiles":[]`) {
		t.Fatalf("empty arrays were not preserved: %s", text)
	}
}

func TestLegacyWireIsNotPartOfNormalSerialization(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	data, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	for _, legacyField := range []string{"hardware_json", "docker_json", "hermes_json"} {
		if strings.Contains(string(data), legacyField) {
			t.Fatalf("normal serialization contains %s", legacyField)
		}
	}
	wire := legacyExtensionWire{HardwareJSON: `{}`}
	wireData, err := json.Marshal(wire)
	if err != nil || !strings.Contains(string(wireData), "hardware_json") {
		t.Fatalf("legacy wire cannot represent transition input: %s, %v", wireData, err)
	}
}

func TestExtensionConstantsMatchSchemaLimits(t *testing.T) {
	data := readFixture(t, filepath.Join("..", "..", "docs", "migration", "schema", "agent-update-extension.schema.json"))
	var schema map[string]any
	if err := json.Unmarshal(data, &schema); err != nil {
		t.Fatal(err)
	}
	defs := schema["$defs"].(map[string]any)
	if got := int(defs["docker"].(map[string]any)["properties"].(map[string]any)["containers"].(map[string]any)["maxItems"].(float64)); got != MaxDockerContainers {
		t.Fatalf("docker maxItems=%d", got)
	}
	if got := int(defs["hermes"].(map[string]any)["properties"].(map[string]any)["profiles"].(map[string]any)["maxItems"].(float64)); got != MaxHermesProfiles {
		t.Fatalf("hermes maxItems=%d", got)
	}
	if got := int64(defs["nullableCounter"].(map[string]any)["maximum"].(float64)); got != MaxSafeInteger {
		t.Fatalf("safe integer maximum=%d", got)
	}
}

func ptrHardware(value HardwareStats) *HardwareStats { return &value }
func ptrDocker(value DockerStats) *DockerStats       { return &value }
func ptrHermes(value HermesStats) *HermesStats       { return &value }
