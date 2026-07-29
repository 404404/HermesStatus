package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

const (
	testCurrentToken = "synthetic-current-token-000000000001"
	testNextToken    = "synthetic-next-token-000000000002"
	testWrongToken   = "synthetic-wrong-token-0000000000003"
)

func TestCredentialDirectoryLoadsCurrentAndOverlappingRotation(t *testing.T) {
	now := time.Now().UTC()
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	directory := t.TempDir()
	record := testCredentialRecord(
		"device-alpha",
		testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
		testCredentialSlot("next", testNextToken, now.Add(-time.Minute), now.Add(2*time.Hour)),
	)
	writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), record)
	loaded, err := loadDeviceCredentialDirectory(directory, &registry)
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded) != 1 || len(loaded["device-alpha"].Slots) != 2 {
		t.Fatalf("rotation was not loaded atomically: %#v", loaded)
	}
	for _, testCase := range []struct {
		token string
		slot  string
	}{
		{testCurrentToken, "current"},
		{testNextToken, "next"},
	} {
		authenticated, ok := authenticateDeviceBearer(
			[]string{"Bearer " + testCase.token}, loaded["device-alpha"], now,
		)
		if !ok || authenticated.DeviceID != "device-alpha" ||
			authenticated.SlotID != testCase.slot {
			t.Fatalf("credential slot %s was not accepted: %#v", testCase.slot, authenticated)
		}
	}
	if err := validateRequiredDeviceCredentials(loaded, &registry, now); err != nil {
		t.Fatalf("active credential was not considered available: %v", err)
	}
	currentOnlyDirectory := t.TempDir()
	writeJSONTestFile(t, filepath.Join(currentOnlyDirectory, "device-alpha.json"), testCredentialRecord(
		"device-alpha",
		testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
	))
	currentOnly, err := loadDeviceCredentialDirectory(currentOnlyDirectory, &registry)
	if err != nil || len(currentOnly["device-alpha"].Slots) != 1 {
		t.Fatalf("current-only credential failed to load: %#v err=%v", currentOnly, err)
	}
}

func TestCredentialAuthenticationRejectsMalformedAndInactiveTokens(t *testing.T) {
	now := time.Now().UTC()
	expired := compileTestCredentialSet(t, testCredentialRecord(
		"device-alpha",
		testCredentialSlot("current", testCurrentToken, now.Add(-2*time.Hour), now.Add(-time.Hour)),
	))
	notYet := compileTestCredentialSet(t, testCredentialRecord(
		"device-alpha",
		testCredentialSlot("current", testCurrentToken, now.Add(time.Hour), now.Add(2*time.Hour)),
	))
	for name, testCase := range map[string]struct {
		headers     []string
		credentials deviceCredentialSet
	}{
		"wrong-token":         {[]string{"Bearer " + testWrongToken}, expired},
		"missing-header":      {nil, expired},
		"duplicate-header":    {[]string{"Bearer " + testCurrentToken, "Bearer " + testCurrentToken}, expired},
		"wrong-scheme":        {[]string{"Basic " + testCurrentToken}, expired},
		"empty-token":         {[]string{"Bearer "}, expired},
		"short-token":         {[]string{"Bearer short"}, expired},
		"oversized-token":     {[]string{"Bearer " + strings.Repeat("x", maxDeviceTokenBytes+1)}, expired},
		"folded-whitespace":   {[]string{"Bearer " + testCurrentToken + " extra"}, expired},
		"control-character":   {[]string{"Bearer " + testCurrentToken + "\x7f"}, expired},
		"expired-token":       {[]string{"Bearer " + testCurrentToken}, expired},
		"not-yet-valid-token": {[]string{"Bearer " + testCurrentToken}, notYet},
	} {
		t.Run(name, func(t *testing.T) {
			if _, ok := authenticateDeviceBearer(
				testCase.headers, testCase.credentials, now,
			); ok {
				t.Fatal("malformed or inactive token was accepted")
			}
		})
	}
}

func TestCredentialDirectoryRejectsInvalidEntriesAtomically(t *testing.T) {
	now := time.Now().UTC()
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	valid := testCredentialRecord(
		"device-alpha",
		testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
	)
	tests := []struct {
		name  string
		setup func(*testing.T, string)
	}{
		{
			name: "unknown-slot",
			setup: func(t *testing.T, directory string) {
				record := cloneCredentialRecord(valid)
				record.Credentials[0].ID = "unexpected"
				writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), record)
			},
		},
		{
			name: "duplicate-slot",
			setup: func(t *testing.T, directory string) {
				record := cloneCredentialRecord(valid)
				record.Credentials = append(record.Credentials, record.Credentials[0])
				writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), record)
			},
		},
		{
			name: "duplicate-digest",
			setup: func(t *testing.T, directory string) {
				record := cloneCredentialRecord(valid)
				next := record.Credentials[0]
				next.ID = "next"
				record.Credentials = append(record.Credentials, next)
				writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), record)
			},
		},
		{
			name: "invalid-digest",
			setup: func(t *testing.T, directory string) {
				record := cloneCredentialRecord(valid)
				record.Credentials[0].Digest = "not-a-digest"
				writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), record)
			},
		},
		{
			name: "unknown-json-field",
			setup: func(t *testing.T, directory string) {
				data, _ := json.Marshal(valid)
				var object map[string]any
				_ = json.Unmarshal(data, &object)
				object["unexpected"] = "raw-secret-marker"
				writeJSONTestFile(t, filepath.Join(directory, "device-alpha.json"), object)
			},
		},
		{
			name: "device-file-mismatch",
			setup: func(t *testing.T, directory string) {
				writeJSONTestFile(t, filepath.Join(directory, "device-beta.json"), valid)
			},
		},
		{
			name: "unknown-device",
			setup: func(t *testing.T, directory string) {
				record := cloneCredentialRecord(valid)
				record.DeviceID = "unknown-device"
				writeJSONTestFile(t, filepath.Join(directory, "unknown-device.json"), record)
			},
		},
		{
			name: "symlink-file",
			setup: func(t *testing.T, directory string) {
				target := filepath.Join(t.TempDir(), "target.json")
				writeJSONTestFile(t, target, valid)
				if err := os.Symlink(target, filepath.Join(directory, "device-alpha.json")); err != nil {
					t.Fatal(err)
				}
			},
		},
		{
			name: "directory-entry",
			setup: func(t *testing.T, directory string) {
				if err := os.Mkdir(filepath.Join(directory, "device-alpha.json"), 0o700); err != nil {
					t.Fatal(err)
				}
			},
		},
		{
			name: "oversized-file",
			setup: func(t *testing.T, directory string) {
				if err := os.WriteFile(
					filepath.Join(directory, "device-alpha.json"),
					[]byte(strings.Repeat("x", maxCredentialFileBytes+1)),
					0o600,
				); err != nil {
					t.Fatal(err)
				}
			},
		},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			directory := t.TempDir()
			writeJSONTestFile(t, filepath.Join(directory, "device-beta.json"), testCredentialRecord(
				"device-beta",
				testCredentialSlot("current", testNextToken, now.Add(-time.Hour), now.Add(time.Hour)),
			))
			testCase.setup(t, directory)
			loaded, err := loadDeviceCredentialDirectory(directory, &registry)
			if err == nil || loaded != nil {
				t.Fatalf("invalid directory partially loaded credentials: %#v", loaded)
			}
			if strings.Contains(err.Error(), "raw-secret-marker") ||
				strings.Contains(err.Error(), directory) {
				t.Fatalf("credential error leaked content/path: %v", err)
			}
		})
	}
}

func TestCredentialDirectoryAndRequiredCredentialBoundaries(t *testing.T) {
	now := time.Now().UTC()
	legacy := testRegistry(
		testRegistryDevice("legacy-alpha", "Legacy", 10, true, "legacy", nil),
	)
	if loaded, err := loadDeviceCredentialDirectory(t.TempDir(), &legacy); err != nil ||
		validateRequiredDeviceCredentials(loaded, &legacy, now) != nil {
		t.Fatalf("legacy-only device incorrectly required a v2 credential: %v", err)
	}

	enabledV2 := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	if err := validateRequiredDeviceCredentials(
		map[string]deviceCredentialSet{}, &enabledV2, now,
	); err == nil {
		t.Fatal("enabled device_v2 device did not require an active credential")
	}
	for name, credentials := range map[string]deviceCredentialSet{
		"expired": compileTestCredentialSet(t, testCredentialRecord(
			"device-alpha",
			testCredentialSlot("current", testCurrentToken, now.Add(-2*time.Hour), now.Add(-time.Hour)),
		)),
		"not-yet-valid": compileTestCredentialSet(t, testCredentialRecord(
			"device-alpha",
			testCredentialSlot("current", testCurrentToken, now.Add(time.Hour), now.Add(2*time.Hour)),
		)),
	} {
		t.Run(name+"-required", func(t *testing.T) {
			if err := validateRequiredDeviceCredentials(
				map[string]deviceCredentialSet{"device-alpha": credentials}, &enabledV2, now,
			); err == nil {
				t.Fatal("inactive credential satisfied endpoint startup")
			}
		})
	}

	disabledV2 := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, false, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	disabledV2.Defaults.DefaultDeviceID = "device-beta"
	if err := validateRequiredDeviceCredentials(
		map[string]deviceCredentialSet{
			"device-beta": compileTestCredentialSet(t, testCredentialRecord(
				"device-beta",
				testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
			)),
		},
		&disabledV2,
		now,
	); err != nil {
		t.Fatalf("disabled device incorrectly required a credential: %v", err)
	}

	directory := t.TempDir()
	symlink := filepath.Join(t.TempDir(), "credentials-link")
	if err := os.Symlink(directory, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := loadDeviceCredentialDirectory(symlink, &enabledV2); err == nil {
		t.Fatal("credential directory symlink was accepted")
	}
	parentRoot := t.TempDir()
	realParent := filepath.Join(parentRoot, "real")
	realCredentials := filepath.Join(realParent, "credentials")
	if err := os.MkdirAll(realCredentials, 0o700); err != nil {
		t.Fatal(err)
	}
	linkedParent := filepath.Join(parentRoot, "linked")
	if err := os.Symlink(realParent, linkedParent); err != nil {
		t.Fatal(err)
	}
	if _, err := loadDeviceCredentialDirectory(
		filepath.Join(linkedParent, "credentials"), &enabledV2,
	); err == nil {
		t.Fatal("credential directory with a symlinked parent was accepted")
	}
	if _, err := loadDeviceCredentialDirectory("relative-credentials", &enabledV2); err == nil {
		t.Fatal("relative credential directory was accepted")
	}

	disabledEndpoint := &App{opts: Options{}, registry: &enabledV2}
	if err := disabledEndpoint.configureDeviceEndpoint(); err != nil ||
		disabledEndpoint.deviceEndpointEnabled {
		t.Fatalf("disabled endpoint incorrectly required credentials: %v", err)
	}
	enabledWithoutCredentials := &App{
		opts: Options{DeviceEndpointEnabled: true}, registry: &enabledV2,
	}
	if err := enabledWithoutCredentials.configureDeviceEndpoint(); err == nil {
		t.Fatal("enabled endpoint started without a credential directory")
	}

	ipRegistry := testRegistry(
		testRegistryDevice("192.0.2.10", "IP", 10, true, "device_v2", nil),
	)
	if err := validateRequiredDeviceCredentials(
		map[string]deviceCredentialSet{
			"192.0.2.10": compileTestCredentialSet(t, testCredentialRecord(
				"192.0.2.10",
				testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
			)),
		},
		&ipRegistry,
		now,
	); err == nil {
		t.Fatal("an IP-shaped active v2 identity could make the endpoint unusable")
	}
}

func TestTrustedProxyConfigurationFailsClosed(t *testing.T) {
	for name, testCase := range map[string]struct {
		enabled bool
		value   string
	}{
		"list-with-mode-disabled": {enabled: false, value: "192.0.2.10/32"},
		"empty-enabled-list":      {enabled: true, value: ""},
		"invalid-prefix":          {enabled: true, value: "not-a-prefix"},
		"empty-list-item":         {enabled: true, value: "192.0.2.10/32,"},
		"over-capacity": {
			enabled: true,
			value:   strings.Repeat("192.0.2.10/32,", 64) + "192.0.2.11/32",
		},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := parseTrustedProxyPrefixes(
				testCase.enabled, testCase.value,
			); err == nil {
				t.Fatal("invalid trusted proxy configuration was accepted")
			}
		})
	}
	prefixes, err := parseTrustedProxyPrefixes(
		true, "192.0.2.10,2001:db8::1/128",
	)
	if err != nil || len(prefixes) != 2 {
		t.Fatalf("explicit trusted proxy addresses failed: %#v err=%v", prefixes, err)
	}
}

func cloneCredentialRecord(
	record contracts.CredentialRecord,
) contracts.CredentialRecord {
	record.Credentials = append([]contracts.Credential(nil), record.Credentials...)
	return record
}

func testCredentialRecord(
	deviceID string,
	slots ...contracts.Credential,
) contracts.CredentialRecord {
	return contracts.CredentialRecord{
		Version: 1, DeviceID: deviceID, Algorithm: "sha256",
		Credentials: slots,
	}
}

func testCredentialSlot(
	id string,
	token string,
	notBefore time.Time,
	notAfter time.Time,
) contracts.Credential {
	digest := sha256.Sum256([]byte(token))
	return contracts.Credential{
		ID: id, Digest: hex.EncodeToString(digest[:]),
		NotBefore: notBefore.UTC().Format(time.RFC3339),
		NotAfter:  notAfter.UTC().Format(time.RFC3339),
	}
}

func compileTestCredentialSet(
	t *testing.T,
	record contracts.CredentialRecord,
) deviceCredentialSet {
	t.Helper()
	compiled, err := compileCredentialRecord(record)
	if err != nil {
		t.Fatal(err)
	}
	return compiled
}
