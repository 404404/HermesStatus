package contracts

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestStatsProjectionOrderingCompatibilityAndIsolation(t *testing.T) {
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-four.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	seen := "2026-07-01T12:00:00Z"
	observations := map[string]DeviceObservation{
		"device-alpha": {
			IdentityStatus: "matched", Status: "offline",
			ProtocolMode: "legacy_single_device", LastSeen: &seen, CollectedAt: &seen, Stale: true,
			LegacyFields: map[string]any{
				"type": "synthetic", "host": "alpha.example.invalid", "location": "fixture",
				"online4": false, "online6": false, "hardware_json": "{}",
			},
		},
		"device-gamma": {
			IdentityStatus: "matched", Status: "stale", ProtocolMode: "device_v2",
			LastSeen: &seen, CollectedAt: &seen, Stale: true,
			LegacyFields: map[string]any{"type": "synthetic", "host": "", "location": "fixture"},
		},
	}
	document := ProjectStatsV2(*registry, observations, []any{}, fixtureNow)
	if got := []string{
		document.Servers[0].DeviceID,
		document.Servers[1].DeviceID,
		document.Servers[2].DeviceID,
		document.Servers[3].DeviceID,
	}; strings.Join(got, ",") != "device-beta,device-gamma,device-alpha,device-delta" {
		t.Fatalf("unexpected stable ordering: %v", got)
	}
	if document.Servers[0].Status != "never_seen" || document.Servers[3].Status != "disabled" {
		t.Fatalf("registry states were not emitted: %#v", document.Servers)
	}
	if err := ValidateStatsV2(document); err != nil {
		t.Fatal(err)
	}
	encoded, err := SerializeStatsV2(document)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), `"devices"`) ||
		!strings.Contains(string(encoded), `"servers"`) ||
		!strings.Contains(string(encoded), `"sslcerts"`) ||
		!strings.Contains(string(encoded), `"updated"`) ||
		!strings.Contains(string(encoded), `"hardware_json"`) {
		t.Fatalf("stats compatibility shape changed: %s", encoded)
	}

	document.Servers[1].legacyFields["bad"] = make(chan int)
	encoded, err = SerializeStatsV2(document)
	if err != nil {
		t.Fatal(err)
	}
	var projected struct {
		Servers []map[string]any `json:"servers"`
	}
	if err := json.Unmarshal(encoded, &projected); err != nil {
		t.Fatal(err)
	}
	if projected.Servers[1]["status"] != "degraded" || len(projected.Servers) != 4 {
		t.Fatalf("single-device serialization failure was not isolated: %#v", projected.Servers)
	}
}

func TestStatsFixturesRetainMinimalEvolution(t *testing.T) {
	for _, name := range []string{
		"stats-v2-single.json",
		"stats-v2-four.json",
		"stats-never-seen.json",
		"stats-stale-offline.json",
		"stats-disabled.json",
	} {
		t.Run(name, func(t *testing.T) {
			var value map[string]any
			if err := json.Unmarshal(fixture(t, "valid", name), &value); err != nil {
				t.Fatal(err)
			}
			if _, exists := value["devices"]; exists {
				t.Fatal("duplicate devices[] collection exists")
			}
			for _, key := range []string{"schema_version", "generated_at", "default_device_id", "servers", "sslcerts", "updated"} {
				if _, exists := value[key]; !exists {
					t.Fatalf("missing retained/new field %s", key)
				}
			}
			for _, raw := range value["servers"].([]any) {
				server := raw.(map[string]any)
				if server["expected_fqdn"] != nil || server["reported_fqdn"] != nil {
					t.Fatal("browser-facing FQDN was exposed")
				}
				for _, key := range []string{
					"name", "type", "host", "location", "online4", "online6",
					"extension_version", "hardware", "docker", "hermes", "lucky",
				} {
					if _, exists := server[key]; !exists {
						t.Fatalf("2.1 field %s was not retained", key)
					}
				}
			}
		})
	}
}

func TestGenerationAndOwnershipIsolation(t *testing.T) {
	legacy := IngestionOwnership{
		Mode: "legacy", ActiveProtocol: stringPointer("legacy_single_device"),
	}
	state, err := ApplyGeneration(
		map[string]GenerationState{}, "device-alpha", legacy,
		"legacy_single_device", 2, "newer", fixtureNow,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ApplyGeneration(
		state, "device-alpha", legacy, "legacy_single_device", 1, "older", fixtureNow,
	); err == nil {
		t.Fatal("older generation overwrote newer state")
	}
	if _, err := ApplyGeneration(
		state, "device-alpha", legacy, "device_v2", 3, "inactive", fixtureNow,
	); err == nil {
		t.Fatal("inactive protocol obtained write ownership")
	}
	next, err := ApplyGeneration(
		state, "device-beta", legacy, "legacy_single_device", 1, "other", fixtureNow,
	)
	if err != nil {
		t.Fatal(err)
	}
	if next["device-alpha"].PayloadMark != "newer" || next["device-beta"].PayloadMark != "other" {
		t.Fatalf("different devices were not isolated: %#v", next)
	}

	cutover := IngestionOwnership{
		Mode: "cutover", ActiveProtocol: stringPointer("device_v2"),
		CutoverNotAfter: stringPointer("2099-01-01T00:00:00Z"),
	}
	if _, err := ApplyGeneration(
		state, "device-alpha", cutover, "legacy_single_device", 3, "inactive", fixtureNow,
	); err == nil {
		t.Fatal("cutover accepted the inactive writer")
	}
}

func TestStatusEnumValidation(t *testing.T) {
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-single.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	document := ProjectStatsV2(*registry, nil, nil, time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC))
	document.Servers[0].Status = "unexpected"
	if err := ValidateStatsV2(document); err == nil {
		t.Fatal("invalid device status was accepted")
	}
}
