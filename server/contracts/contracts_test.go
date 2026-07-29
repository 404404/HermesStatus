package contracts

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var fixtureNow = time.Date(2026, 7, 29, 0, 0, 0, 0, time.UTC)

func fixture(t *testing.T, category, name string) []byte {
	t.Helper()
	path := filepath.Join("..", "..", "testdata", "multi_device", category, name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func boolPointer(value bool) *bool {
	return &value
}

func stringPointer(value string) *string {
	return &value
}

func TestRegistryFixturesAndStableOrdering(t *testing.T) {
	for _, name := range []string{
		"registry-single.json",
		"registry-four.json",
		"registry-legacy-only.json",
		"registry-v2-only.json",
		"registry-cutover-legacy.json",
		"registry-cutover-v2.json",
		"registry-order-tie.json",
		"registry-128.json",
	} {
		t.Run(name, func(t *testing.T) {
			registry, err := DecodeRegistry(fixture(t, "valid", name), fixtureNow)
			if err != nil {
				t.Fatal(err)
			}
			for index := 1; index < len(registry.Devices); index++ {
				previous, current := registry.Devices[index-1], registry.Devices[index]
				if previous.Order > current.Order ||
					(previous.Order == current.Order && previous.ID >= current.ID) {
					t.Fatalf("registry is not stably sorted: %s then %s", previous.ID, current.ID)
				}
			}
		})
	}
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-order-tie.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	if registry.Devices[0].ID != "device-alpha" || registry.Devices[1].ID != "device-zeta" {
		t.Fatalf("allowed order tie was not sorted by ID: %#v", registry.Devices)
	}
}

func TestRegistryInvalidFixtures(t *testing.T) {
	names := []string{
		"registry-duplicate-device-id.json",
		"registry-invalid-device-id.json",
		"registry-bad-default.json",
		"registry-default-disabled.json",
		"registry-bad-fqdn.json",
		"registry-ip-as-fqdn.json",
		"registry-url-as-fqdn.json",
		"registry-unknown-field.json",
		"registry-129-devices.json",
		"registry-invalid-stale-offline.json",
		"registry-missing-ingestion.json",
		"registry-invalid-ingestion-mode.json",
		"registry-cutover-without-active.json",
		"registry-cutover-without-expiry.json",
		"registry-expired-cutover.json",
	}
	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeRegistry(fixture(t, "invalid", name), fixtureNow); err == nil {
				t.Fatal("invalid registry was accepted")
			}
		})
	}
}

func TestRegistryNormalizesFQDNAndDisplayName(t *testing.T) {
	data := fixture(t, "valid", "registry-single.json")
	data = []byte(strings.Replace(string(data), "alpha.example.invalid", "ALPHA.EXAMPLE.INVALID.", 1))
	registry, err := DecodeRegistry(data, fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	if got := *registry.Devices[0].ExpectedFQDN; got != "alpha.example.invalid" {
		t.Fatalf("FQDN was not normalized: %q", got)
	}
}

func TestCredentialContractAndValidityWindows(t *testing.T) {
	record, err := DecodeCredentialRecord(fixture(t, "valid", "credential-rotation.json"))
	if err != nil {
		t.Fatal(err)
	}
	active := ActiveCredentialIDs(*record, fixtureNow)
	if strings.Join(active, ",") != "current,next" {
		t.Fatalf("unexpected active slots: %v", active)
	}
	if active := ActiveCredentialIDs(*record, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)); len(active) != 0 {
		t.Fatalf("not-yet-valid credentials became active: %v", active)
	}
	if active := ActiveCredentialIDs(*record, time.Date(2100, 1, 1, 0, 0, 0, 0, time.UTC)); len(active) != 0 {
		t.Fatalf("expired credentials remained active: %v", active)
	}
	currentOnly := *record
	currentOnly.Credentials = append([]Credential(nil), record.Credentials[0])
	if err := ValidateCredentialRecord(&currentOnly); err != nil {
		t.Fatalf("valid current-only credential was rejected: %v", err)
	}
	for _, name := range []string{
		"credential-duplicate-slot.json",
		"credential-invalid-digest.json",
		"credential-excessive-count.json",
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeCredentialRecord(fixture(t, "invalid", name)); err == nil {
				t.Fatal("invalid credential record was accepted")
			}
		})
	}
}

func TestLegacyMappingCrossFileValidation(t *testing.T) {
	registry, err := DecodeRegistry(fixture(t, "valid", "registry-legacy-only.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodeLegacyMappings(
		fixture(t, "valid", "legacy-mapping.json"), registry, fixtureNow,
	); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"legacy-duplicate-username.json", "legacy-duplicate-device.json"} {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeLegacyMappings(fixture(t, "invalid", name), registry, fixtureNow); err == nil {
				t.Fatal("invalid one-to-one mapping was accepted")
			}
		})
	}

	v2Registry, err := DecodeRegistry(fixture(t, "valid", "registry-v2-only.json"), fixtureNow)
	if err != nil {
		t.Fatal(err)
	}
	incompatible := []byte(`{"version":1,"mappings":[{"username":"synthetic-user","device_id":"v2-alpha"}]}`)
	if _, err := DecodeLegacyMappings(incompatible, v2Registry, fixtureNow); err == nil {
		t.Fatal("legacy mapping to device_v2 owner was accepted")
	}

	missing := []byte(`{"version":1,"mappings":[{"username":"synthetic-user","device_id":"missing-device"}]}`)
	if _, err := DecodeLegacyMappings(missing, registry, fixtureNow); err == nil {
		t.Fatal("legacy mapping to missing registry device was accepted")
	}

	disabled := *registry
	disabled.Devices = append([]RegistryDevice(nil), registry.Devices...)
	disabled.Devices[0].Enabled = boolPointer(false)
	if _, err := DecodeLegacyMappings(
		fixture(t, "valid", "legacy-mapping.json"), &disabled, fixtureNow,
	); err == nil {
		t.Fatal("legacy mapping to disabled registry device was accepted")
	}
}

func TestEnvelopeFixturesAndIdentityBinding(t *testing.T) {
	for _, name := range []string{"envelope-all-domains.json", "envelope-partial-domain-failure.json"} {
		t.Run(name, func(t *testing.T) {
			envelope, err := DecodeDeviceUpdateEnvelope(fixture(t, "valid", name))
			if err != nil {
				t.Fatal(err)
			}
			if err := ValidateEnvelopeIdentity(envelope.Device.ID, *envelope); err != nil {
				t.Fatal(err)
			}
		})
	}
	var mismatch struct {
		HeaderDeviceID string               `json:"header_device_id"`
		Body           DeviceUpdateEnvelope `json:"body"`
	}
	if err := json.Unmarshal(fixture(t, "invalid", "envelope-header-body-mismatch.json"), &mismatch); err != nil {
		t.Fatal(err)
	}
	if err := ValidateEnvelopeIdentity(mismatch.HeaderDeviceID, mismatch.Body); err == nil {
		t.Fatal("header/body mismatch was accepted")
	}
	for _, name := range []string{
		"envelope-unknown-field.json",
		"envelope-credential-in-body.json",
		"envelope-config-in-body.json",
		"envelope-command-in-body.json",
		"envelope-invalid-collected-at.json",
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeDeviceUpdateEnvelope(fixture(t, "invalid", name)); err == nil {
				t.Fatal("invalid envelope was accepted")
			}
		})
	}
}

func TestEnvelopeRejectsIDFQDNTimeAndBodyLimit(t *testing.T) {
	base := fixture(t, "valid", "envelope-all-domains.json")
	for name, oldNew := range map[string][2]string{
		"id":   {`"device-alpha"`, `"INVALID ID"`},
		"fqdn": {`"alpha.example.invalid"`, `"192.0.2.10"`},
		"time": {`"2026-07-01T12:00:00Z"`, `"2026-07-01 12:00:00"`},
	} {
		t.Run(name, func(t *testing.T) {
			data := []byte(strings.Replace(string(base), oldNew[0], oldNew[1], 1))
			if _, err := DecodeDeviceUpdateEnvelope(data); err == nil {
				t.Fatal("invalid envelope value was accepted")
			}
		})
	}
	var descriptor struct {
		SyntheticSizeBytes int `json:"synthetic_size_bytes"`
	}
	if err := json.Unmarshal(
		fixture(t, "invalid", "envelope-oversized-descriptor.json"), &descriptor,
	); err != nil {
		t.Fatal(err)
	}
	oversized := make([]byte, descriptor.SyntheticSizeBytes)
	if _, err := DecodeDeviceUpdateEnvelope(oversized); err == nil {
		t.Fatal("oversized envelope was accepted")
	}
}

func TestResponseContracts(t *testing.T) {
	var success SuccessResponse
	if err := decodeStrict(fixture(t, "valid", "response-success.json"), &success); err != nil {
		t.Fatal(err)
	}
	if err := ValidateSuccessResponse(success); err != nil {
		t.Fatal(err)
	}
	var publicError ErrorResponse
	if err := decodeStrict(fixture(t, "valid", "response-error.json"), &publicError); err != nil {
		t.Fatal(err)
	}
	if err := ValidateErrorResponse(publicError); err != nil {
		t.Fatal(err)
	}
}
