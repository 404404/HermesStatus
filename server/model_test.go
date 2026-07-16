package main

import (
	"encoding/json"
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
