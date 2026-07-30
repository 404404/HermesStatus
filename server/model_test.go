package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestNormalizeConfigPreservesCompatibility(t *testing.T) {
	doc := minimalTestConfig()
	doc["future"] = map[string]any{"enabled": true}
	doc["watchdog"] = []any{map[string]any{"name": "legacy", "rule": "cpu>90", "callback": "https://example.invalid"}}
	doc["sslcerts"] = []any{map[string]any{"name": "example", "domain": "example.invalid", "callback": "https://example.invalid"}}
	doc["servers"].([]any)[0].(map[string]any)["future_field"] = "kept"

	normalized, runtime, apiErr := normalizeConfig(doc)
	if apiErr != nil {
		t.Fatal(apiErr)
	}
	if _, exists := normalized["watchdog"]; exists {
		t.Fatalf("legacy alert rules survived normalization: %#v", normalized)
	}
	sslcert := normalized["sslcerts"].([]any)[0].(map[string]any)
	if _, exists := sslcert["callback"]; exists {
		t.Fatalf("legacy SSL callback survived normalization: %#v", sslcert)
	}
	if len(runtime.SSLCerts) != 1 {
		t.Fatalf("SSL status checks were not preserved: %#v", runtime.SSLCerts)
	}
	server := normalized["servers"].([]any)[0].(map[string]any)
	if server["future_field"] != "kept" || normalized["future"] == nil {
		t.Fatal("unknown config fields were discarded")
	}
	if server["monthstart"] != json.Number("1") && server["monthstart"] != 1 {
		t.Fatalf("monthstart not normalized: %#v", server["monthstart"])
	}
}

func TestConfigValidationErrors(t *testing.T) {
	doc := minimalTestConfig()
	doc["servers"] = append(doc["servers"].([]any), doc["servers"].([]any)[0])
	_, _, apiErr := normalizeConfig(doc)
	if apiErr == nil || apiErr.Status != 409 {
		t.Fatalf("expected duplicate username error, got %#v", apiErr)
	}

	if _, err := decodeDocument([]byte(`{"servers":[]} {"servers":[]}`)); err == nil || !strings.Contains(err.Error(), "more than one") {
		t.Fatalf("expected trailing JSON error, got %v", err)
	}
}

func TestMonitorConfigurationUsesDeviceResponseContract(t *testing.T) {
	valid := []map[string]any{
		{"name": "HTTP", "host": "http://example.invalid/health", "type": "http", "interval": 30},
		{"name": "HTTPS", "host": "https://example.invalid/status", "type": "https", "interval": 60},
		{"name": "TCP", "host": "127.0.0.1:443", "type": "tcp", "interval": 90},
	}
	doc := minimalTestConfig()
	doc["monitors"] = make([]any, 0, len(valid))
	for _, monitor := range valid {
		doc["monitors"] = append(doc["monitors"].([]any), monitor)
	}
	_, runtime, apiErr := normalizeConfig(doc)
	if apiErr != nil {
		t.Fatalf("valid shared monitor contract was rejected: %v", apiErr)
	}
	snapshot, err := sanitizedMonitorSnapshot(runtime.Monitors)
	if err != nil || len(snapshot) != len(valid) {
		t.Fatalf("management/device validators diverged: %#v err=%v", snapshot, err)
	}

	invalid := []map[string]any{
		{"name": "scheme", "host": "ftp://example.invalid", "type": "ftp", "interval": 30},
		{"name": "credentials", "host": "https://user:pass@example.invalid", "type": "https", "interval": 30},
		{"name": "query", "host": "https://example.invalid/?to%6ben=secret", "type": "https", "interval": 30},
		{"name": "path", "host": "https://example.invalid/%2e%2e/admin", "type": "https", "interval": 30},
		{"name": "tcp-url", "host": "tcp://127.0.0.1:80", "type": "tcp", "interval": 30},
		{"name": "long", "host": "https://" + strings.Repeat("a", 254), "type": "https", "interval": 30},
	}
	for _, monitor := range invalid {
		t.Run(fmt.Sprint(monitor["name"]), func(t *testing.T) {
			candidate := minimalTestConfig()
			candidate["monitors"] = []any{monitor}
			if _, _, apiErr := normalizeConfig(candidate); apiErr == nil ||
				apiErr.Status != 400 ||
				apiErr.Message != "monitor configuration is invalid" {
				t.Fatalf("invalid monitor was accepted or leaked details: %#v", apiErr)
			}
		})
	}

	tooMany := minimalTestConfig()
	monitors := make([]any, maxDeviceMonitors+1)
	for index := range monitors {
		monitors[index] = map[string]any{
			"name": fmt.Sprintf("monitor-%03d", index),
			"host": "https://example.invalid",
			"type": "https", "interval": 30,
		}
	}
	tooMany["monitors"] = monitors
	if _, _, apiErr := normalizeConfig(tooMany); apiErr == nil ||
		apiErr.Message != "monitor configuration is invalid" {
		t.Fatalf("monitor limit was not enforced by config validation: %#v", apiErr)
	}
}

func TestMonitorValidationFixtureMatchesManagementAndDeviceBoundaries(t *testing.T) {
	workingDirectory, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(
		filepath.Dir(workingDirectory),
		"testdata",
		"multi_device",
		"monitor_validation.json",
	))
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name     string `json:"name"`
		Host     string `json:"host"`
		Type     string `json:"type"`
		Accepted bool   `json:"accepted"`
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for _, testCase := range cases {
		t.Run(testCase.Name, func(t *testing.T) {
			monitor := map[string]any{
				"name": testCase.Name, "host": testCase.Host,
				"type": testCase.Type, "interval": 60,
			}
			doc := minimalTestConfig()
			doc["monitors"] = []any{monitor}
			_, runtime, apiErr := normalizeConfig(doc)
			managementAccepted := apiErr == nil
			deviceAccepted := false
			if managementAccepted {
				_, snapshotErr := sanitizedMonitorSnapshot(runtime.Monitors)
				deviceAccepted = snapshotErr == nil
			} else {
				_, snapshotErr := sanitizedMonitorSnapshot([]MonitorConfig{{
					Name: testCase.Name, Host: testCase.Host,
					Type: testCase.Type, Interval: 60,
				}})
				deviceAccepted = snapshotErr == nil
			}
			if managementAccepted != testCase.Accepted ||
				deviceAccepted != testCase.Accepted {
				t.Fatalf(
					"fixture divergence: expected=%t management=%t device=%t",
					testCase.Accepted,
					managementAccepted,
					deviceAccepted,
				)
			}
		})
	}
}

func TestFormattingHelpers(t *testing.T) {
	if got := formatUptime(90061); got != "1 天" {
		t.Fatalf("formatUptime=%q", got)
	}
	if got := formatUptime(3661); got != "01:01:01" {
		t.Fatalf("formatUptime=%q", got)
	}
	if got, err := certificateHost("https://example.com/path"); err != nil || got != "example.com" {
		t.Fatalf("certificateHost=%q", got)
	}
	if got := secondsDuration(0); got != time.Second {
		t.Fatalf("secondsDuration(0)=%s", got)
	}
	if got := secondsDuration(int(^uint(0) >> 1)); got < 365*24*time.Hour {
		t.Fatalf("large interval overflowed or was truncated: %s", got)
	}
}
