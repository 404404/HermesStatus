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

func TestCollectionDiagnosticsRejectSecretLikeText(t *testing.T) {
	diagnostics := []CollectionDiagnostic{{Domain: "unifi", Component: "api", Status: "degraded", Reason: strings.Join([]string{"api", "key=secret-value"}, "_")}}
	if err := validateCollectionDiagnostics(diagnostics); err == nil {
		t.Fatal("secret-like diagnostic text was accepted")
	}
}
