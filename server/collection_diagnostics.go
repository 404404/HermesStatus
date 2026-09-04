package main

import (
	"strconv"
	"strings"
)

const (
	MaxCollectionDiagnostics      = 64
	maxCollectionDiagnosticText   = 160
	collectionNotConfiguredReason = "该组件未在配置文件中开启采集"
)

type CollectionDiagnostic struct {
	Domain    string `json:"domain"`
	Component string `json:"component"`
	Status    string `json:"status"`
	Code      string `json:"code,omitempty"`
	Field     string `json:"field,omitempty"`
	Reason    string `json:"reason,omitempty"`
	Source    string `json:"source,omitempty"`
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
		diagnostic.Code, diagnostic.Field, diagnostic.Reason, diagnostic.Source,
	}, "\x00")
	if _, exists := seen[key]; exists || len(*diagnostics) >= MaxCollectionDiagnostics {
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
	domain, component, field string,
	extensionError *ExtensionError,
) {
	if extensionError == nil {
		return
	}
	appendCollectionDiagnostic(diagnostics, seen, CollectionDiagnostic{
		Domain: domain, Component: component, Status: "degraded",
		Code:   safeExtensionDiagnostic(extensionError.Code),
		Field:  safeExtensionDiagnostic(field),
		Reason: safeExtensionDiagnostic(extensionError.Message),
		Source: safeExtensionDiagnostic(extensionError.Source),
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
				addCollectionErrorDiagnostic(&diagnostics, seen, "hardware", "storage.physical_disks", "hardware.storage.physical_disks[].error", disk.Error)
			}
			for _, filesystem := range storage.Filesystems {
				addCollectionErrorDiagnostic(&diagnostics, seen, "hardware", "storage.filesystems", "hardware.storage.filesystems[].error", filesystem.Error)
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
			addCollectionErrorDiagnostic(&diagnostics, seen, "hermes", "profiles", "hermes.profiles[].error", profile.Error)
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
					Status: apiDiagnosticStatus(endpoint.Status),
				})
				addCollectionErrorDiagnostic(&diagnostics, seen, "unifi", "api.endpoint", "unifi.api.endpoints[].error", endpoint.Error)
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
			Code:   safeExtensionDiagnostic(issue.Code),
			Field:  safeExtensionDiagnostic(issue.Field),
			Reason: safeExtensionDiagnostic(issue.Reason),
		})
	}
	return diagnostics
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
			"reason": diagnostic.Reason, "source": diagnostic.Source,
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
	}
	return nil
}
