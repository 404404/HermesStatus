package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestHTTPStatsAndOpenAPIExposeOnlyStructuredExtensions(t *testing.T) {
	app := newTestApp(t, minimalTestConfig())
	extension := mustDecodeUpdate(t, "update-normal.json")
	connectNodeForUpdate(app, 11)
	if !app.updateAgent("s01", 11, AgentStats{CPU: 27, MemoryTotal: 8192, MemoryUsed: 2048, HDDTotal: 120000, HDDUsed: 30000}, *extension) {
		t.Fatal("update was rejected")
	}
	router := app.router()

	response := performRequest(router, http.MethodGet, "/json/stats.json", "", "")
	if response.Code != http.StatusOK || response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("stats response: status=%d cache=%q", response.Code, response.Header().Get("Cache-Control"))
	}
	body := response.Body.String()
	for _, forbidden := range []string{"hardware_json", "docker_json", "hermes_json", "lucky_json", "/usr/local/bin/status-server", "Authorization: Bearer", "api_key="} {
		if strings.Contains(body, forbidden) {
			t.Fatalf("stats response contains forbidden content %q: %s", forbidden, body)
		}
	}
	var stats map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &stats); err != nil {
		t.Fatal(err)
	}
	server := stats["servers"].([]any)[0].(map[string]any)
	for _, field := range []string{"extension_version", "received_at", "hardware", "docker", "hermes", "lucky", "easytier"} {
		if _, ok := server[field]; !ok {
			t.Fatalf("stats server is missing %s: %#v", field, server)
		}
	}
	containers := server["docker"].(map[string]any)["containers"].([]any)
	container := containers[0].(map[string]any)
	if len(container) != 4 || container["names"] == nil || container["image"] == nil || container["status"] == nil || container["ports"] == nil {
		t.Fatalf("HTTP response did not use the Release C Docker allowlist: %#v", container)
	}

	response = performRequest(router, http.MethodGet, "/api/openapi.json", "", "")
	if response.Code != http.StatusOK {
		t.Fatalf("OpenAPI response: status=%d body=%s", response.Code, response.Body.String())
	}
	openAPIBody := response.Body.String()
	for _, forbidden := range []string{"/api/hermes", "hardware_json", "docker_json", "hermes_json", "lucky_json", "API_SERVER_KEY", "Authorization: Bearer"} {
		if strings.Contains(openAPIBody, forbidden) {
			t.Fatalf("OpenAPI contains forbidden content %q", forbidden)
		}
	}
	var spec map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &spec); err != nil {
		t.Fatal(err)
	}
	paths := spec["paths"].(map[string]any)
	statsOperation := paths["/json/stats.json"].(map[string]any)["get"].(map[string]any)
	responseSchema := statsOperation["responses"].(map[string]any)["200"].(map[string]any)["content"].(map[string]any)["application/json"].(map[string]any)["schema"].(map[string]any)
	if responseSchema["$ref"] != "#/components/schemas/StatsDocument" {
		t.Fatalf("stats response does not reference StatsDocument: %#v", responseSchema)
	}
	schemas := spec["components"].(map[string]any)["schemas"].(map[string]any)
	for _, name := range []string{"HardwareStats", "CPUUsageStats", "CPUDetails", "MemoryDetails", "DockerStats", "HermesStats", "LuckyStats", "LuckyServiceStats", "LuckyVersionStats", "LuckyDynamicDNSStats", "LuckyWebServicesStats", "LuckyPortForwardsStats", "LuckyCertificatesStats", "ConfigModelSummary", "AuxiliaryModelSummary", "DelegationSummary", "SanitizedConfigSummary", "MixtureOfAgentsStats", "EasyTierExpectationValues", "EasyTierExpectationProjection", "StatsServer", "StatsDocument"} {
		schema := schemas[name].(map[string]any)
		if schema["additionalProperties"] != false {
			t.Fatalf("%s is not allowlisted: %#v", name, schema)
		}
	}
	statsServer := schemas["StatsServer"].(map[string]any)
	if _, ok := statsServer["properties"].(map[string]any)["easytier_expectation"]; !ok {
		t.Fatalf("StatsServer is missing the emitted easytier_expectation property: %#v", statsServer)
	}
	cpuDetails := schemas["CPUDetails"].(map[string]any)
	required := cpuDetails["required"].([]any)
	for _, value := range required {
		field, ok := value.(string)
		if !ok {
			t.Fatalf("CPUDetails required field is not a string: %#v", value)
		}
		if field == "instruction_sets" {
			t.Fatalf("CPUDetails incorrectly requires additive instruction_sets: %#v", required)
		}
	}
	if _, ok := cpuDetails["properties"].(map[string]any)["instruction_sets"]; !ok {
		t.Fatalf("CPUDetails is missing the optional instruction_sets property: %#v", cpuDetails)
	}
	storage := schemas["StorageStats"].(map[string]any)
	filesystems := storage["properties"].(map[string]any)["filesystems"].(map[string]any)
	if filesystems["items"].(map[string]any)["$ref"] != "#/components/schemas/FilesystemStats" {
		t.Fatalf("StorageStats filesystems does not reference FilesystemStats: %#v", filesystems)
	}
	filesystem := schemas["FilesystemStats"].(map[string]any)
	backingIDs := filesystem["properties"].(map[string]any)["backing_disk_ids"].(map[string]any)
	backingID := backingIDs["items"].(map[string]any)
	if backingID["pattern"] != "^[A-Za-z0-9][A-Za-z0-9_.+-]*$" {
		t.Fatalf("filesystem backing ID OpenAPI contract rejects plus: %#v", backingID)
	}
}
