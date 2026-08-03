package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestDeviceConfigValidationIsReadOnlyAndUsesProductionValidators(t *testing.T) {
	now := time.Date(2026, 7, 29, 8, 0, 0, 0, time.UTC)
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Compute Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Legacy Beta", 20, true, "legacy", nil),
		testRegistryDevice("device-disabled", "Disabled", 30, false, "device_v2", nil),
	)
	registry.Defaults.DefaultDeviceID = "device-alpha"

	root := t.TempDir()
	configPath := filepath.Join(root, "config.json")
	registryPath := filepath.Join(root, "devices.json")
	mappingPath := filepath.Join(root, "legacy-device-mapping.json")
	credentialsPath := filepath.Join(root, "credentials.d")
	if err := os.Mkdir(credentialsPath, 0o700); err != nil {
		t.Fatal(err)
	}
	writeJSONTestFile(t, configPath, minimalTestConfig())
	writeJSONTestFile(t, registryPath, registry)
	writeJSONTestFile(t, mappingPath, contracts.LegacyMappingDocument{
		Version: 1,
		Mappings: []contracts.LegacyDeviceMapping{{
			Username: "s02", DeviceID: "device-beta",
		}},
	})
	writeJSONTestFile(
		t,
		filepath.Join(credentialsPath, "device-alpha.json"),
		testCredentialRecord(
			"device-alpha",
			testCredentialSlot(
				"current",
				testCurrentToken,
				now.Add(-time.Hour),
				now.Add(time.Hour),
			),
		),
	)
	opts := Options{
		ConfigPath:           configPath,
		RegistryPath:         registryPath,
		LegacyMappingPath:    mappingPath,
		DeviceCredentialsDir: credentialsPath,
	}
	before := snapshotValidationTree(t, root)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if exitCode := runDeviceConfigValidation(
		opts,
		&stdout,
		&stderr,
		now,
	); exitCode != 0 {
		t.Fatalf("valid configuration was rejected: code=%d stderr=%q", exitCode, stderr.String())
	}
	after := snapshotValidationTree(t, root)
	if before != after {
		t.Fatalf("read-only validation changed its input tree:\nbefore=%s\nafter=%s", before, after)
	}
	wantOutput := strings.Join([]string{
		"validation success",
		"total devices: 3",
		"enabled count: 2",
		"disabled count: 1",
		"credential records count: 1",
		"legacy mappings count: 1",
		"default device_id: device-alpha",
		"",
	}, "\n")
	if stdout.String() != wantOutput || stderr.Len() != 0 {
		t.Fatalf("unexpected safe validation output: stdout=%q stderr=%q", stdout.String(), stderr.String())
	}

	invalidConfig := minimalTestConfig()
	invalidConfig["monitors"] = []any{map[string]any{
		"name": "query-not-allowed", "host": "https://example.invalid/?check=health",
		"interval": 60, "type": "https",
	}}
	writeJSONTestFile(t, configPath, invalidConfig)
	stdout.Reset()
	stderr.Reset()
	if exitCode := runDeviceConfigValidation(
		opts,
		&stdout,
		&stderr,
		now,
	); exitCode != 2 ||
		stdout.Len() != 0 ||
		stderr.String() != "validation failed code=config_invalid field=config\n" {
		t.Fatalf(
			"query monitor bypassed operational validation: code=%d stdout=%q stderr=%q",
			exitCode,
			stdout.String(),
			stderr.String(),
		)
	}
}

func TestDeviceConfigValidationFailuresAreStableAndRedacted(t *testing.T) {
	now := time.Date(2026, 7, 29, 8, 0, 0, 0, time.UTC)
	root := t.TempDir()
	registryPath := filepath.Join(root, "devices.json")
	mappingPath := filepath.Join(root, "legacy-device-mapping.json")
	credentialsPath := filepath.Join(root, "credentials.d")
	if err := os.Mkdir(credentialsPath, 0o700); err != nil {
		t.Fatal(err)
	}
	hostileFQDN := "private-system.internal.example"
	registry := testRegistry(
		testRegistryDevice(
			"device-alpha",
			"Alpha",
			10,
			true,
			"device_v2",
			&hostileFQDN,
		),
	)
	registry.Devices[0].ExpectedFQDN = stringPointer("https://forbidden.invalid/secret")
	writeJSONTestFile(t, registryPath, registry)
	writeJSONTestFile(t, mappingPath, contracts.LegacyMappingDocument{Version: 1})
	secretToken := strings.Repeat("S", deviceTokenBytes)
	secretDigest := strings.Repeat("a", 64)
	writeJSONTestFile(
		t,
		filepath.Join(credentialsPath, "device-alpha.json"),
		map[string]any{
			"version": 1, "device_id": "device-alpha", "algorithm": "sha256",
			"credentials": []any{map[string]any{
				"id": "current", "digest": secretDigest,
				"not_before": "2026-01-01T00:00:00Z",
				"not_after":  "2099-01-01T00:00:00Z",
				"token":      secretToken,
			}},
		},
	)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	exitCode := runDeviceConfigValidation(
		Options{
			RegistryPath:         registryPath,
			LegacyMappingPath:    mappingPath,
			DeviceCredentialsDir: credentialsPath,
		},
		&stdout,
		&stderr,
		now,
	)
	if exitCode != 2 || stdout.Len() != 0 ||
		stderr.String() != "validation failed code=registry_invalid field=registry.devices[0].expected_fqdn\n" {
		t.Fatalf("unexpected failure contract: code=%d stdout=%q stderr=%q", exitCode, stdout.String(), stderr.String())
	}
	for _, forbidden := range []string{
		root,
		hostileFQDN,
		"forbidden.invalid",
		secretToken,
		secretDigest,
	} {
		if strings.Contains(stderr.String(), forbidden) {
			t.Fatalf("validation failure leaked %q: %q", forbidden, stderr.String())
		}
	}

	validRegistry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	writeJSONTestFile(t, registryPath, validRegistry)
	stdout.Reset()
	stderr.Reset()
	exitCode = runDeviceConfigValidation(
		Options{
			RegistryPath:         registryPath,
			LegacyMappingPath:    mappingPath,
			DeviceCredentialsDir: credentialsPath,
		},
		&stdout,
		&stderr,
		now,
	)
	if exitCode != 2 || stdout.Len() != 0 ||
		stderr.String() != "validation failed code=credentials_invalid field=credentials\n" {
		t.Fatalf(
			"unexpected credential failure contract: code=%d stdout=%q stderr=%q",
			exitCode,
			stdout.String(),
			stderr.String(),
		)
	}
	for _, forbidden := range []string{root, secretToken, secretDigest} {
		if strings.Contains(stderr.String(), forbidden) {
			t.Fatalf("credential failure leaked %q: %q", forbidden, stderr.String())
		}
	}
}

func TestDeviceConfigValidationRejectsMissingAndUnsafeInputs(t *testing.T) {
	now := time.Date(2026, 7, 29, 8, 0, 0, 0, time.UTC)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if exitCode := runDeviceConfigValidation(
		Options{},
		&stdout,
		&stderr,
		now,
	); exitCode != 2 ||
		stderr.String() != "validation failed code=registry_missing field=registry\n" {
		t.Fatalf("missing input did not fail safely: code=%d stderr=%q", exitCode, stderr.String())
	}

	root := t.TempDir()
	target := filepath.Join(root, "target.json")
	link := filepath.Join(root, "devices.json")
	writeJSONTestFile(t, target, testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	))
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	stdout.Reset()
	stderr.Reset()
	if exitCode := runDeviceConfigValidation(
		Options{RegistryPath: link},
		&stdout,
		&stderr,
		now,
	); exitCode != 2 ||
		stderr.String() != "validation failed code=registry_unavailable field=registry\n" {
		t.Fatalf("symlink input did not fail safely: code=%d stderr=%q", exitCode, stderr.String())
	}
	if data, err := secureReadBoundedDocument(
		"relative.json",
		maxRuntimeConfigBytes,
	); err == nil || data != nil {
		t.Fatal("relative multi-device document was accepted")
	}
}

func TestCheckedInManualRegistrationExamplesPassProductionValidation(t *testing.T) {
	exampleRoot, err := filepath.Abs(filepath.Join("..", "config", "examples"))
	if err != nil {
		t.Fatal(err)
	}
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	exitCode := runDeviceConfigValidation(
		Options{
			RegistryPath: filepath.Join(
				exampleRoot,
				"device-registry.example.json",
			),
			LegacyMappingPath: filepath.Join(
				exampleRoot,
				"legacy-device-mapping.example.json",
			),
			DeviceCredentialsDir: filepath.Join(
				exampleRoot,
				"credentials.d",
			),
		},
		&stdout,
		&stderr,
		time.Now().UTC(),
	)
	if exitCode != 0 || stderr.Len() != 0 {
		t.Fatalf(
			"checked-in examples failed production validation: code=%d stderr=%q",
			exitCode,
			stderr.String(),
		)
	}
	if !strings.Contains(stdout.String(), "total devices: 4") ||
		!strings.Contains(stdout.String(), "credential records count: 2") ||
		!strings.Contains(stdout.String(), "legacy mappings count: 1") {
		t.Fatalf("checked-in example summary is incomplete: %q", stdout.String())
	}
}

func snapshotValidationTree(t *testing.T, root string) string {
	t.Helper()
	var entries []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		relative, relativeErr := filepath.Rel(root, path)
		if relativeErr != nil {
			return relativeErr
		}
		entries = append(entries, fmt.Sprintf(
			"%s:%s:%d:%d",
			relative,
			info.Mode().String(),
			info.Size(),
			info.ModTime().UnixNano(),
		))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return strings.Join(entries, "\n")
}
