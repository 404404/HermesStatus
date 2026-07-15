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
	for _, forbidden := range []string{"hardware_json", "docker_json", "hermes_json", "/usr/local/bin/status-server", "Authorization: Bearer", "api_key="} {
		if strings.Contains(body, forbidden) {
			t.Fatalf("stats response contains forbidden content %q: %s", forbidden, body)
		}
	}
	var stats map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &stats); err != nil {
		t.Fatal(err)
	}
	server := stats["servers"].([]any)[0].(map[string]any)
	for _, field := range []string{"extension_version", "received_at", "hardware", "docker", "hermes"} {
		if _, ok := server[field]; !ok {
			t.Fatalf("stats server is missing %s: %#v", field, server)
		}
	}
	containers := server["docker"].(map[string]any)["containers"].([]any)
	if containers[0].(map[string]any)["command"] != HiddenDockerCommand {
		t.Fatalf("HTTP response exposed a Docker command: %#v", containers[0])
	}

	response = performRequest(router, http.MethodGet, "/api/openapi.json", "", "")
	if response.Code != http.StatusOK {
		t.Fatalf("OpenAPI response: status=%d body=%s", response.Code, response.Body.String())
	}
	openAPIBody := response.Body.String()
	for _, forbidden := range []string{"/api/hermes", "hardware_json", "docker_json", "hermes_json", "API_SERVER_KEY", "Authorization: Bearer"} {
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
	for _, name := range []string{"HardwareStats", "DockerStats", "HermesStats", "StatsServer", "StatsDocument"} {
		schema := schemas[name].(map[string]any)
		if schema["additionalProperties"] != false {
			t.Fatalf("%s is not allowlisted: %#v", name, schema)
		}
	}
}
