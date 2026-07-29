package main

import (
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

type deviceConfigValidationSummary struct {
	TotalDevices    int
	EnabledDevices  int
	DisabledDevices int
	CredentialFiles int
	LegacyMappings  int
	DefaultDeviceID string
}

type deviceConfigValidationError struct {
	Code  string
	Field string
}

func validateDeviceConfiguration(
	opts Options,
	now time.Time,
) (deviceConfigValidationSummary, *deviceConfigValidationError) {
	if opts.RegistryPath == "" {
		return deviceConfigValidationSummary{}, configValidationError(
			"registry_missing", "registry",
		)
	}
	registryData, err := readBoundedFile(opts.RegistryPath, maxRuntimeConfigBytes)
	if err != nil {
		return deviceConfigValidationSummary{}, configValidationError(
			"registry_unavailable", "registry",
		)
	}
	registry, err := contracts.DecodeRegistry(registryData, now)
	if err != nil {
		return deviceConfigValidationSummary{}, validationContractError(
			"registry_invalid", "registry", err,
		)
	}

	if opts.DeviceCredentialsDir == "" {
		return deviceConfigValidationSummary{}, configValidationError(
			"credentials_missing", "credentials",
		)
	}
	credentials, err := loadDeviceCredentialDirectory(
		opts.DeviceCredentialsDir,
		registry,
	)
	if err != nil {
		return deviceConfigValidationSummary{}, configValidationError(
			"credentials_invalid", "credentials",
		)
	}
	if err := validateRequiredDeviceCredentials(credentials, registry, now); err != nil {
		return deviceConfigValidationSummary{}, configValidationError(
			"credentials_incomplete", "credentials.active",
		)
	}

	if opts.LegacyMappingPath == "" {
		return deviceConfigValidationSummary{}, configValidationError(
			"legacy_mapping_missing", "legacy_mapping",
		)
	}
	mappingData, err := readBoundedFile(
		opts.LegacyMappingPath,
		maxRuntimeConfigBytes,
	)
	if err != nil {
		return deviceConfigValidationSummary{}, configValidationError(
			"legacy_mapping_unavailable", "legacy_mapping",
		)
	}
	mappings, err := contracts.DecodeLegacyMappings(mappingData, registry, now)
	if err != nil {
		return deviceConfigValidationSummary{}, validationContractError(
			"legacy_mapping_invalid", "legacy_mapping", err,
		)
	}

	summary := deviceConfigValidationSummary{
		TotalDevices:    len(registry.Devices),
		CredentialFiles: len(credentials),
		LegacyMappings:  len(mappings.Mappings),
		DefaultDeviceID: registry.Defaults.DefaultDeviceID,
	}
	for _, device := range registry.Devices {
		if device.Enabled != nil && *device.Enabled {
			summary.EnabledDevices++
		} else {
			summary.DisabledDevices++
		}
	}
	return summary, nil
}

func runDeviceConfigValidation(
	opts Options,
	stdout io.Writer,
	stderr io.Writer,
	now time.Time,
) int {
	summary, validationErr := validateDeviceConfiguration(opts, now)
	if validationErr != nil {
		fmt.Fprintf(
			stderr,
			"validation failed code=%s field=%s\n",
			validationErr.Code,
			validationErr.Field,
		)
		return 2
	}
	fmt.Fprintln(stdout, "validation success")
	fmt.Fprintf(stdout, "total devices: %d\n", summary.TotalDevices)
	fmt.Fprintf(stdout, "enabled count: %d\n", summary.EnabledDevices)
	fmt.Fprintf(stdout, "disabled count: %d\n", summary.DisabledDevices)
	fmt.Fprintf(stdout, "credential records count: %d\n", summary.CredentialFiles)
	fmt.Fprintf(stdout, "legacy mappings count: %d\n", summary.LegacyMappings)
	fmt.Fprintf(stdout, "default device_id: %s\n", summary.DefaultDeviceID)
	return 0
}

func configValidationError(code, field string) *deviceConfigValidationError {
	return &deviceConfigValidationError{Code: code, Field: safeValidationField(field)}
}

func validationContractError(
	code string,
	prefix string,
	err error,
) *deviceConfigValidationError {
	field := prefix
	var contractErr *contracts.ContractError
	if errors.As(err, &contractErr) && contractErr.Field != "" {
		field += "." + contractErr.Field
	}
	return configValidationError(code, field)
}

func safeValidationField(field string) string {
	if field == "" || len(field) > 160 {
		return "configuration"
	}
	for _, character := range field {
		if !((character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			strings.ContainsRune("._[]-", character)) {
			return "configuration"
		}
	}
	return field
}
