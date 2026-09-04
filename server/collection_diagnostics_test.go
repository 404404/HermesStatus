package main

import (
	"strings"
	"testing"
)

func TestCollectionDiagnosticsExposeSanitizedBusinessError(t *testing.T) {
	error := &ExtensionError{Code: "smart_value_invalid", Message: "SMART attribute value is invalid", Source: "smartctl"}
	stats := ExtensionStats{Hardware: &HardwareStats{Storage: &StorageStats{PhysicalDisks: []PhysicalDiskStats{{CollectionStatus: "invalid_data", Error: error}}}}}
	diagnostics := buildCollectionDiagnostics(stats, nil)
	var found *CollectionDiagnostic
	for index := range diagnostics {
		if diagnostics[index].Component == "storage.physical_disks" {
			found = &diagnostics[index]
			break
		}
	}
	if found == nil {
		t.Fatalf("physical-disk diagnostic was not emitted: %#v", diagnostics)
	}
	if found.Code != "smart_value_invalid" || found.Field != "hardware.storage.physical_disks[].error" || found.Reason != error.Message || found.Source != "smartctl" {
		t.Fatalf("unexpected physical-disk diagnostic: %#v", *found)
	}
	if err := validateCollectionDiagnostics(diagnostics); err != nil {
		t.Fatalf("diagnostics failed validation: %v", err)
	}
}

func TestCollectionDiagnosticsPreserveDecoderFieldAndReason(t *testing.T) {
	diagnostics := buildCollectionDiagnostics(ExtensionStats{}, []extensionDecodeIssue{{
		Domain: "unifi", Code: "invalid_value", Field: "unifi.api.telemetry.ports", Reason: "port ownership contract rejected", PayloadLength: 999999,
	}})
	var found *CollectionDiagnostic
	for index := range diagnostics {
		if diagnostics[index].Domain == "unifi" && diagnostics[index].Code == "invalid_value" {
			found = &diagnostics[index]
			break
		}
	}
	if found == nil || found.Field != "unifi.api.telemetry.ports" || found.Reason != "port ownership contract rejected" {
		t.Fatalf("decoder issue was not preserved: %#v", diagnostics)
	}
	if err := validateCollectionDiagnostics(diagnostics); err != nil {
		t.Fatalf("decoder diagnostics failed validation: %v", err)
	}
}

func TestCollectionDiagnosticsDescribeDisabledCollectors(t *testing.T) {
	diagnostics := make([]CollectionDiagnostic, 0, 3)
	seen := make(map[string]struct{})
	addCollectionDomainDiagnostic(&diagnostics, seen, "hardware", "hardware", true, true, &ExtensionError{
		Code: "not_reported", Message: "Extension data was not reported", Source: "hardware",
	}, "hardware.error")
	addCollectionDomainDiagnostic(&diagnostics, seen, "easytier", "easytier", true, true, &ExtensionError{
		Code: "not_configured", Source: "easytier",
	}, "easytier.error")
	addCollectionDomainDiagnostic(&diagnostics, seen, "docker", "docker", true, true, &ExtensionError{
		Code: "source_error", Message: "Extension data is unavailable", Source: "docker-collector",
	}, "docker.error")

	if len(diagnostics) != 3 {
		t.Fatalf("unexpected diagnostic count: %#v", diagnostics)
	}
	if diagnostics[0].Status != "not_configured" || diagnostics[0].Reason != collectionNotConfiguredReason {
		t.Fatalf("not_reported collector was not described as disabled: %#v", diagnostics[0])
	}
	if diagnostics[1].Status != "not_configured" || diagnostics[1].Reason != collectionNotConfiguredReason {
		t.Fatalf("not_configured collector was not described as disabled: %#v", diagnostics[1])
	}
	if diagnostics[2].Status != "degraded" || diagnostics[2].Reason != "Extension data is unavailable" {
		t.Fatalf("source failure was incorrectly described as disabled: %#v", diagnostics[2])
	}
	if err := validateCollectionDiagnostics(diagnostics); err != nil {
		t.Fatalf("disabled collector diagnostics failed validation: %v", err)
	}
}

func TestCollectionDiagnosticsRejectSecretLikeText(t *testing.T) {
	diagnostics := []CollectionDiagnostic{{Domain: "unifi", Component: "api", Status: "degraded", Reason: strings.Join([]string{"api", "key=secret-value"}, "_")}}
	if err := validateCollectionDiagnostics(diagnostics); err == nil {
		t.Fatal("secret-like diagnostic text was accepted")
	}
}
