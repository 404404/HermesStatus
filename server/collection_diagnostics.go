package main

import (
	"sort"
	"strconv"
	"strings"
)

const (
	MaxCollectionDiagnostics      = 64
	maxCollectionDiagnosticIssues = 16
	maxCollectionDiagnosticText   = 160
	collectionNotConfiguredReason = "该组件未在配置文件中开启采集"
	smartAttributeFallbackReason  = "SMART 原生状态不可用，已使用属性检查结果"
)

type CollectionDiagnostic struct {
	Domain         string `json:"domain"`
	Component      string `json:"component"`
	Status         string `json:"status"`
	Code           string `json:"code,omitempty"`
	Field          string `json:"field,omitempty"`
	Reason         string `json:"reason,omitempty"`
	Source         string `json:"source,omitempty"`
	Resource       string `json:"resource,omitempty"`
	ObservedCount  int    `json:"observed_count,omitempty"`
	DisplayedCount int    `json:"displayed_count,omitempty"`
}

func cloneCollectionDiagnosticIssues(issues []extensionDecodeIssue) []extensionDecodeIssue {
	if len(issues) == 0 {
		return nil
	}
	return append([]extensionDecodeIssue(nil), issues...)
}

var collectionDiagnosticStatuses = map[string]struct{}{
	"available": {}, "degraded": {}, "unavailable": {}, "stale": {},
	"not_reported": {}, "not_configured": {}, "not_installed": {},
	"unsupported": {}, "partial": {}, "not_observed": {},
}

func collectionStatus(present, stale bool, extensionError *ExtensionError) string {
	if !present {
		return "not_reported"
	}
	if extensionError != nil {
		switch extensionError.Code {
		case "not_configured":
			return "not_configured"
		case "not_reported":
			// The current unified client uses this explicit error for a
			// collector disabled in its configuration. Keep source errors
			// (source_error, snapshot_unavailable, and similar) distinct.
			return "not_configured"
		case "not_installed":
			return "not_installed"
		}
		return "degraded"
	}
	if stale {
		return "stale"
	}
	return "available"
}

func appendCollectionDiagnostic(
	diagnostics *[]CollectionDiagnostic,
	seen map[string]struct{},
	diagnostic CollectionDiagnostic,
) {
	if diagnostic.Domain == "" || diagnostic.Component == "" || diagnostic.Status == "" {
		return
	}
	key := strings.Join([]string{
		diagnostic.Domain, diagnostic.Component, diagnostic.Status,
		diagnostic.Resource, diagnostic.Code, diagnostic.Field, diagnostic.Source,
	}, "\x00")
	if _, exists := seen[key]; exists {
		return
	}
	seen[key] = struct{}{}
	*diagnostics = append(*diagnostics, diagnostic)
}

func addCollectionDomainDiagnostic(
	diagnostics *[]CollectionDiagnostic,
	seen map[string]struct{},
	domain, component string,
	present, stale bool,
	extensionError *ExtensionError,
	field string,
) {
	diagnostic := CollectionDiagnostic{
		Domain: domain, Component: component,
		Status: collectionStatus(present, stale, extensionError),
	}
	if extensionError != nil {
		diagnostic.Code = safeExtensionDiagnostic(extensionError.Code)
		diagnostic.Reason = safeExtensionDiagnostic(extensionError.Message)
		diagnostic.Source = safeExtensionDiagnostic(extensionError.Source)
		diagnostic.Field = safeExtensionDiagnostic(field)
	}
	if diagnostic.Status == "not_configured" && diagnostic.Reason == "" {
		diagnostic.Reason = collectionNotConfiguredReason
	}
	if extensionError != nil && extensionError.Code == "not_reported" {
		diagnostic.Reason = collectionNotConfiguredReason
	}
	appendCollectionDiagnostic(diagnostics, seen, diagnostic)
}

func addCollectionErrorDiagnostic(
	diagnostics *[]CollectionDiagnostic,
	seen map[string]struct{},
	domain, component, resource, field string,
	extensionError *ExtensionError,
) {
	if extensionError == nil {
		return
	}
	appendCollectionDiagnostic(diagnostics, seen, CollectionDiagnostic{
		Domain: domain, Component: component, Status: "degraded",
		Code:     safeExtensionDiagnostic(extensionError.Code),
		Resource: safeExtensionDiagnostic(resource),
		Field:    safeExtensionDiagnostic(field),
		Reason:   safeExtensionDiagnostic(extensionError.Message),
		Source:   safeExtensionDiagnostic(extensionError.Source),
	})
}

func smartAttributeFallbackObservation(disk PhysicalDiskStats) bool {
	return (disk.SMARTStatus == DiskSMARTPassed || disk.SMARTStatus == DiskSMARTFailed) &&
		disk.CollectionStatus == "partial" &&
		disk.Completeness != nil && *disk.Completeness == "partial" &&
		disk.HealthSource != nil && *disk.HealthSource == "attribute_check" &&
		disk.NativeStatus != nil && *disk.NativeStatus == "unavailable"
}

func diagnosticResourceForDisk(disk PhysicalDiskStats) string {
	if value := safeExtensionDiagnostic(disk.ID); value != "" {
		return value
	}
	return safeExtensionDiagnostic(disk.Device)
}

func diagnosticResourceForFilesystem(filesystem FilesystemStats) string {
	if value := safeExtensionDiagnostic(filesystem.Mountpoint); value != "" {
		return value
	}
	if filesystem.Source != nil {
		return safeExtensionDiagnostic(*filesystem.Source)
	}
	return ""
}

func addPhysicalDiskDiagnostic(
	diagnostics *[]CollectionDiagnostic,
	seen map[string]struct{},
	disk PhysicalDiskStats,
) {
	resource := diagnosticResourceForDisk(disk)
	fallback := smartAttributeFallbackObservation(disk)
	if disk.Error != nil {
		status := "degraded"
		reason := safeExtensionDiagnostic(disk.Error.Message)
		if fallback && disk.SMARTStatus == DiskSMARTPassed && disk.Error.Code == "smart_return_status_unavailable" {
			status = "partial"
			reason = smartAttributeFallbackReason
		}
		appendCollectionDiagnostic(diagnostics, seen, CollectionDiagnostic{
			Domain: "hardware", Component: "storage.physical_disks", Status: status,
			Code: safeExtensionDiagnostic(disk.Error.Code), Resource: resource,
			Field: "hardware.storage.physical_disks[].error", Reason: reason,
			Source: safeExtensionDiagnostic(disk.Error.Source),
		})
	}
	if fallback && (disk.Error == nil || disk.Error.Code != "smart_return_status_unavailable") {
		status := "partial"
		if disk.SMARTStatus == DiskSMARTFailed {
			status = "degraded"
		}
		appendCollectionDiagnostic(diagnostics, seen, CollectionDiagnostic{
			Domain: "hardware", Component: "storage.physical_disks", Status: status,
			Code: "smart_return_status_unavailable", Resource: resource,
			Field: "hardware.storage.physical_disks[].native_status", Reason: smartAttributeFallbackReason,
			Source: "smartctl",
		})
	}
	if disk.SMARTStatus == DiskSMARTFailed && disk.Error == nil {
		appendCollectionDiagnostic(diagnostics, seen, CollectionDiagnostic{
			Domain: "hardware", Component: "storage.physical_disks", Status: "degraded",
			Code: "smart_health_failed", Resource: resource,
			Field: "hardware.storage.physical_disks[].smart_status", Reason: "SMART health check reported failed",
			Source: "smartctl",
		})
	}
}

func collectionDiagnosticSeverity(status string) int {
	switch status {
	case "degraded":
		return 0
	case "unavailable", "stale":
		return 1
	case "partial":
		return 2
	case "not_configured", "not_reported", "not_installed", "unsupported", "not_observed":
		return 3
	default:
		return 4
	}
}

func limitCollectionDiagnostics(diagnostics []CollectionDiagnostic) []CollectionDiagnostic {
	if len(diagnostics) <= MaxCollectionDiagnostics {
		return diagnostics
	}
	ordered := append([]CollectionDiagnostic(nil), diagnostics...)
	sort.SliceStable(ordered, func(left, right int) bool {
		return collectionDiagnosticSeverity(ordered[left].Status) < collectionDiagnosticSeverity(ordered[right].Status)
	})
	displayed := MaxCollectionDiagnostics - 1
	limited := append([]CollectionDiagnostic(nil), ordered[:displayed]...)
	return append(limited, CollectionDiagnostic{
		Domain: "collection_diagnostics", Component: "collection_diagnostics", Resource: "collection_diagnostics",
		Status: "partial", Code: "diagnostics_truncated", Field: "collection_diagnostics",
		Reason: "Collection diagnostics were truncated", Source: "server",
		ObservedCount: len(diagnostics), DisplayedCount: displayed,
	})
}

func apiDiagnosticStatus(value string) string {
	switch value {
	case "ok", "available":
		return "available"
	case "unsupported":
		return "unsupported"
	case "partial":
		return "partial"
	case "disabled", "not_configured":
		return "not_configured"
	case "not_collected":
		return "not_observed"
	default:
		return "degraded"
	}
}

func buildCollectionDiagnostics(extension ExtensionStats, issues []extensionDecodeIssue) []CollectionDiagnostic {
	diagnostics := make([]CollectionDiagnostic, 0, 24)
	seen := make(map[string]struct{})

	if extension.Hardware == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "hardware", "hardware", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "hardware", "hardware", true, extension.Hardware.Stale, extension.Hardware.Error, "hardware.error")
		storage := extension.Hardware.Storage
		if storage == nil {
			addCollectionDomainDiagnostic(&diagnostics, seen, "hardware", "storage", false, false, nil, "")
		} else {
			addCollectionDomainDiagnostic(&diagnostics, seen, "hardware", "storage", true, storage.Stale, storage.Error, "hardware.storage.error")
			for _, disk := range storage.PhysicalDisks {
				addPhysicalDiskDiagnostic(&diagnostics, seen, disk)
			}
			for _, filesystem := range storage.Filesystems {
				addCollectionErrorDiagnostic(&diagnostics, seen, "hardware", "storage.filesystems", diagnosticResourceForFilesystem(filesystem), "hardware.storage.filesystems[].error", filesystem.Error)
			}
		}
	}

	if extension.Docker == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "docker", "docker", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "docker", "docker", true, extension.Docker.Stale, extension.Docker.Error, "docker.error")
	}
	if extension.Hermes == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "hermes", "hermes", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "hermes", "hermes", true, extension.Hermes.Stale, extension.Hermes.Error, "hermes.error")
		for _, profile := range extension.Hermes.Profiles {
			addCollectionErrorDiagnostic(&diagnostics, seen, "hermes", "profiles", profile.Profile, "hermes.profiles[].error", profile.Error)
		}
	}

	if extension.Lucky == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "lucky", "lucky", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "lucky", "lucky", true, extension.Lucky.Stale, extension.Lucky.Error, "lucky.error")
	}
	if extension.EasyTier == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "easytier", "easytier", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "easytier", "easytier", true, extension.EasyTier.Stale, extension.EasyTier.Error, "easytier.error")
	}
	if extension.UniFi == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "unifi", "unifi", false, false, nil, "")
	} else {
		unifiStatus := collectionStatus(true, extension.UniFi.Stale, extension.UniFi.Error)
		if !extension.UniFi.Configured {
			unifiStatus = "not_configured"
		}
		unifiDiagnostic := CollectionDiagnostic{Domain: "unifi", Component: "unifi", Status: unifiStatus}
		if unifiStatus == "not_configured" {
			unifiDiagnostic.Reason = collectionNotConfiguredReason
		}
		appendCollectionDiagnostic(&diagnostics, seen, unifiDiagnostic)
		addCollectionDomainDiagnostic(&diagnostics, seen, "unifi", "transport", true, extension.UniFi.Stale, extension.UniFi.Error, "unifi.transport")
		api := extension.UniFi.API
		if api == nil {
			addCollectionDomainDiagnostic(&diagnostics, seen, "unifi", "api", false, false, nil, "")
		} else {
			addCollectionDomainDiagnostic(&diagnostics, seen, "unifi", "api", true, false, api.Error, "unifi.api.error")
			for _, endpoint := range api.Endpoints {
				endpointName := safeExtensionDiagnostic(endpoint.Name)
				if endpointName == "" {
					endpointName = "unknown"
				}
				component := safeExtensionDiagnostic("api.endpoint." + endpointName)
				if component == "" {
					component = "api.endpoint.unknown"
				}
				appendCollectionDiagnostic(&diagnostics, seen, CollectionDiagnostic{
					Domain: "unifi", Component: component,
					Status: apiDiagnosticStatus(endpoint.Status), Resource: endpointName,
				})
				addCollectionErrorDiagnostic(&diagnostics, seen, "unifi", "api.endpoint", endpointName, "unifi.api.endpoints[].error", endpoint.Error)
			}
		}
	}
	if extension.ClientBuild == nil {
		addCollectionDomainDiagnostic(&diagnostics, seen, "client_build", "client_build", false, false, nil, "")
	} else {
		addCollectionDomainDiagnostic(&diagnostics, seen, "client_build", "client_build", true, false, nil, "")
	}

	for _, issue := range issues {
		appendCollectionDiagnostic(&diagnostics, seen, CollectionDiagnostic{
			Domain: issue.Domain, Component: issue.Domain, Status: "degraded",
			Code:     safeExtensionDiagnostic(issue.Code),
			Resource: safeExtensionDiagnostic(issue.Domain),
			Field:    safeExtensionDiagnostic(issue.Field),
			Reason:   safeExtensionDiagnostic(issue.Reason),
		})
	}
	return limitCollectionDiagnostics(diagnostics)
}

func validateCollectionDiagnostics(diagnostics []CollectionDiagnostic) error {
	if diagnostics == nil || len(diagnostics) > MaxCollectionDiagnostics {
		return validationError(validationCodeInvalidValue, "collection_diagnostics", "array is invalid")
	}
	for index, diagnostic := range diagnostics {
		prefix := "collection_diagnostics[" + strconv.Itoa(index) + "]"
		for field, value := range map[string]string{
			"domain": diagnostic.Domain, "component": diagnostic.Component, "status": diagnostic.Status,
		} {
			if err := validateRequiredString(prefix+"."+field, value, maxCollectionDiagnosticText); err != nil {
				return err
			}
			if ContainsSecretLikeText(value) {
				return validationError(validationCodeInvalidValue, prefix+"."+field, "contains disallowed content")
			}
		}
		if _, ok := collectionDiagnosticStatuses[diagnostic.Status]; !ok {
			return validationError(validationCodeInvalidValue, prefix+".status", "status is not supported")
		}
		for field, value := range map[string]string{
			"code": diagnostic.Code, "field": diagnostic.Field,
			"reason": diagnostic.Reason, "source": diagnostic.Source, "resource": diagnostic.Resource,
		} {
			if value == "" {
				continue
			}
			if err := validateRequiredString(prefix+"."+field, value, maxCollectionDiagnosticText); err != nil {
				return err
			}
			if ContainsSecretLikeText(value) {
				return validationError(validationCodeInvalidValue, prefix+"."+field, "contains disallowed content")
			}
		}
		if diagnostic.Code != "" && !errorCodePattern.MatchString(diagnostic.Code) {
			return validationError(validationCodeInvalidValue, prefix+".code", "code contains unsupported characters")
		}
		if diagnostic.ObservedCount != 0 || diagnostic.DisplayedCount != 0 {
			if diagnostic.Code != "diagnostics_truncated" || diagnostic.ObservedCount <= diagnostic.DisplayedCount || diagnostic.DisplayedCount < 0 || diagnostic.ObservedCount > 4096 {
				return validationError(validationCodeInvalidValue, prefix+".observed_count", "truncation counts are invalid")
			}
		}
	}
	return nil
}

func validateCollectionDiagnosticIssues(issues []extensionDecodeIssue) error {
	if len(issues) > maxCollectionDiagnosticIssues {
		return validationError(validationCodeInvalidValue, "collection_diagnostic_issues", "array is too large")
	}
	for index, issue := range issues {
		prefix := "collection_diagnostic_issues[" + strconv.Itoa(index) + "]"
		for field, value := range map[string]string{
			"domain": issue.Domain, "code": issue.Code, "field": issue.Field, "reason": issue.Reason,
		} {
			if value == "" {
				continue
			}
			if err := validateRequiredString(prefix+"."+field, value, maxCollectionDiagnosticText); err != nil {
				return err
			}
			if ContainsSecretLikeText(value) {
				return validationError(validationCodeInvalidValue, prefix+"."+field, "contains disallowed content")
			}
		}
		if issue.Domain == "" || issue.Code == "" || !errorCodePattern.MatchString(issue.Code) || issue.PayloadLength < 0 || issue.PayloadLength > MaxExtensionPayloadBytes {
			return validationError(validationCodeInvalidValue, prefix, "issue is invalid")
		}
	}
	return nil
}
