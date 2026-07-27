package main

import (
	"encoding/json"
	"fmt"
)

func DecodeLuckyStatsJSON(data []byte) (*LuckyStats, error) {
	if len(data) > MaxLuckyPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "lucky", "object exceeds the allowed size")
	}
	if err := validateRequiredLucky(data); err != nil {
		return nil, err
	}
	var stats LuckyStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	stats = SanitizeLuckyStats(stats)
	if err := ValidateLuckyStats(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}

func ValidateLuckyStats(stats *LuckyStats) error {
	if stats == nil {
		return validationError(validationCodeInvalidValue, "lucky", "object is required")
	}
	if !validLuckyStatus(stats.Status) {
		return validationError(validationCodeInvalidValue, "lucky.status", "unsupported status")
	}
	if !validLuckySource(stats.Source) {
		return validationError(validationCodeInvalidValue, "lucky.source", "unsupported source")
	}
	if err := validateRequiredString("lucky.service.state", stats.Service.State, MaxLuckyStatusLength); err != nil {
		return err
	}
	if err := validateCounter("lucky.service.process_pid", stats.Service.ProcessPID, MaxSafeInteger); err != nil {
		return err
	}
	if err := validateCounter("lucky.service.uptime_seconds", stats.Service.UptimeSeconds, MaxSafeInteger); err != nil {
		return err
	}
	if err := ValidateExtensionError("lucky.service.error", stats.Service.Error); err != nil {
		return err
	}
	if err := validateOptionalString("lucky.version.current", stats.Version.Current, MaxLuckyVersionLength); err != nil {
		return err
	}
	if err := validateOptionalString("lucky.version.latest", stats.Version.Latest, MaxLuckyVersionLength); err != nil {
		return err
	}
	if err := validateOptionalString("lucky.version.build_info", stats.Version.BuildInfo, MaxLuckyBuildInfoLength); err != nil {
		return err
	}
	if err := validateDateTime("lucky.version.checked_at", stats.Version.CheckedAt, true); err != nil {
		return err
	}
	if err := ValidateExtensionError("lucky.version.error", stats.Version.Error); err != nil {
		return err
	}
	if err := validateOptionalString("lucky.ip_resolution.mode", stats.IPResolution.Mode, MaxLuckyTextLength); err != nil {
		return err
	}
	if err := validateLuckyModule("lucky.ip_resolution", stats.IPResolution.Status, stats.IPResolution.UpdatedAt, stats.IPResolution.Stale, stats.IPResolution.Error); err != nil {
		return err
	}
	for field, value := range map[string]int{
		"resolved_ip_count": stats.IPResolution.ResolvedIPCount,
		"ipv4_count":        stats.IPResolution.IPv4Count,
		"ipv6_count":        stats.IPResolution.IPv6Count,
	} {
		if value < 0 || value > MaxDockerCount {
			return validationError(validationCodeInvalidValue, "lucky.ip_resolution."+field, "value is outside the allowed range")
		}
	}
	if stats.IPResolution.ResolvedIPCount != stats.IPResolution.IPv4Count+stats.IPResolution.IPv6Count {
		return validationError(validationCodeInvalidValue, "lucky.ip_resolution.resolved_ip_count", "count does not match address family totals")
	}
	if err := validateLuckyDDNS(&stats.DynamicDNS); err != nil {
		return err
	}
	if err := validateLuckyWebServices(&stats.WebServices); err != nil {
		return err
	}
	if err := validateLuckyPortForwards(&stats.PortForwards); err != nil {
		return err
	}
	if err := validateLuckyCertificates(&stats.Certificates); err != nil {
		return err
	}
	if err := validateUpdatedAt("lucky", stats.UpdatedAt, stats.Stale); err != nil {
		return err
	}
	if err := ValidateExtensionError("lucky.error", stats.Error); err != nil {
		return err
	}
	return validatePayloadSize("lucky", stats, MaxLuckyPayloadBytes)
}

func validateLuckyDDNS(stats *LuckyDynamicDNSStats) error {
	if len(stats.Records) > MaxLuckyItems {
		return validationError(validationCodeInvalidValue, "lucky.dynamic_dns.records", "array exceeds the allowed size")
	}
	if err := validateLuckyCollection("lucky.dynamic_dns", stats.Total, stats.Enabled, stats.Disabled, stats.Healthy, stats.ErrorCount, len(stats.Records), stats.Status, stats.UpdatedAt, stats.Stale, stats.Error); err != nil {
		return err
	}
	for index := range stats.Records {
		item := &stats.Records[index]
		prefix := fmt.Sprintf("lucky.dynamic_dns.records[%d]", index)
		if err := validateLuckyIdentity(prefix, item.ID, item.DisplayName, item.Status, item.Error); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".provider", item.Provider, MaxLuckyProviderLength); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".address_method", item.AddressMethod, MaxLuckyTextLength); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".local_record_change_status", item.LocalRecordChangeStatus, MaxLuckyStatusLength); err != nil {
			return err
		}
		if err := validateCounter(prefix+".updated_records", item.UpdatedRecords, MaxSafeInteger); err != nil {
			return err
		}
		if err := validateCounter(prefix+".total_records", item.TotalRecords, MaxSafeInteger); err != nil {
			return err
		}
		if item.UpdatedRecords != nil && item.TotalRecords != nil && *item.UpdatedRecords > *item.TotalRecords {
			return validationError(validationCodeInvalidValue, prefix+".updated_records", "updated record count exceeds total")
		}
		if err := validateOptionalString(prefix+".record_type", item.RecordType, MaxLuckyStatusLength); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".last_update_at", item.LastUpdateAt, true); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".next_sync_at", item.NextSyncAt, true); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".last_success_at", item.LastSuccessAt, true); err != nil {
			return err
		}
	}
	return nil
}

func validateLuckyWebServices(stats *LuckyWebServicesStats) error {
	if len(stats.Services) > MaxLuckyItems {
		return validationError(validationCodeInvalidValue, "lucky.web_services.services", "array exceeds the allowed size")
	}
	if err := validateLuckyCollection("lucky.web_services", stats.Total, stats.Enabled, stats.Disabled, stats.Healthy, stats.ErrorCount, len(stats.Services), stats.Status, stats.UpdatedAt, stats.Stale, stats.Error); err != nil {
		return err
	}
	for index := range stats.Services {
		item := &stats.Services[index]
		prefix := fmt.Sprintf("lucky.web_services.services[%d]", index)
		if err := validateLuckyIdentity(prefix, item.ID, item.DisplayName, item.Status, item.Error); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".protocol", item.Protocol, MaxLuckyProtocolLength); err != nil {
			return err
		}
		if err := validatePort(prefix+".listen_port", item.ListenPort); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".upstream_type", item.UpstreamType, MaxLuckyStatusLength); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".certificate_ref", item.CertificateRef, MaxLuckyNameLength); err != nil {
			return err
		}
		if err := validateCounter(prefix+".connection_count", item.ConnectionCount, MaxSafeInteger); err != nil {
			return err
		}
		if err := validateCounter(prefix+".enabled_subrules", item.EnabledSubrules, MaxSafeInteger); err != nil {
			return err
		}
		if err := validateCounter(prefix+".total_subrules", item.TotalSubrules, MaxSafeInteger); err != nil {
			return err
		}
		if item.EnabledSubrules != nil && item.TotalSubrules != nil && *item.EnabledSubrules > *item.TotalSubrules {
			return validationError(validationCodeInvalidValue, prefix+".enabled_subrules", "enabled subrule count exceeds total")
		}
	}
	return nil
}

func validateLuckyPortForwards(stats *LuckyPortForwardsStats) error {
	if len(stats.Rules) > MaxLuckyItems {
		return validationError(validationCodeInvalidValue, "lucky.port_forwards.rules", "array exceeds the allowed size")
	}
	if err := validateLuckyCollection("lucky.port_forwards", stats.Total, stats.Enabled, stats.Disabled, stats.Healthy, stats.ErrorCount, len(stats.Rules), stats.Status, stats.UpdatedAt, stats.Stale, stats.Error); err != nil {
		return err
	}
	for index := range stats.Rules {
		item := &stats.Rules[index]
		prefix := fmt.Sprintf("lucky.port_forwards.rules[%d]", index)
		if err := validateLuckyIdentity(prefix, item.ID, item.DisplayName, item.Status, item.Error); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".protocol", item.Protocol, MaxLuckyProtocolLength); err != nil {
			return err
		}
		if err := validatePort(prefix+".listen_port", item.ListenPort); err != nil {
			return err
		}
		if err := validateOptionalString(prefix+".target_type", item.TargetType, MaxLuckyStatusLength); err != nil {
			return err
		}
		if err := validateCounter(prefix+".connection_count", item.ConnectionCount, MaxSafeInteger); err != nil {
			return err
		}
	}
	return nil
}

func validateLuckyCertificates(stats *LuckyCertificatesStats) error {
	if len(stats.Items) > MaxLuckyItems {
		return validationError(validationCodeInvalidValue, "lucky.certificates.items", "array exceeds the allowed size")
	}
	counts := []int{stats.Valid, stats.Expiring, stats.Expired, stats.NotYetValid, stats.Invalid, stats.Unknown}
	if stats.Total != len(stats.Items) {
		return validationError(validationCodeInvalidValue, "lucky.certificates.total", "count does not match items")
	}
	sum := 0
	for _, value := range counts {
		if value < 0 || value > MaxLuckyItems {
			return validationError(validationCodeInvalidValue, "lucky.certificates", "count is outside the allowed range")
		}
		sum += value
	}
	if sum != stats.Total {
		return validationError(validationCodeInvalidValue, "lucky.certificates", "status counts do not match total")
	}
	if err := validateLuckyModule("lucky.certificates", stats.Status, stats.UpdatedAt, stats.Stale, stats.Error); err != nil {
		return err
	}
	for index := range stats.Items {
		item := &stats.Items[index]
		prefix := fmt.Sprintf("lucky.certificates.items[%d]", index)
		if err := validateLuckyIdentity(prefix, item.ID, item.DisplayName, item.Status, item.Error); err != nil {
			return err
		}
		if item.SANCount < 0 || item.SANCount > MaxDockerCount {
			return validationError(validationCodeInvalidValue, prefix+".san_count", "value is outside the allowed range")
		}
		if err := validateOptionalString(prefix+".issuer", item.Issuer, MaxLuckyNameLength); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".source", item.Source, MaxLuckyStatusLength); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".not_before", item.NotBefore, true); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".not_after", item.NotAfter, true); err != nil {
			return err
		}
		if item.RemainingDays != nil && (*item.RemainingDays < -MaxLuckyCertificateDays || *item.RemainingDays > MaxLuckyCertificateDays) {
			return validationError(validationCodeInvalidValue, prefix+".remaining_days", "value is outside the allowed range")
		}
		if err := validateDateTime(prefix+".last_renew_at", item.LastRenewAt, true); err != nil {
			return err
		}
		if err := validateDateTime(prefix+".next_renew_at", item.NextRenewAt, true); err != nil {
			return err
		}
	}
	return nil
}

func validateLuckyCollection(field string, total, enabled, disabled, healthy, errorCount, length int, status LuckyStatus, updatedAt *string, stale bool, errorValue *ExtensionError) error {
	values := []int{total, enabled, disabled, healthy, errorCount}
	for _, value := range values {
		if value < 0 || value > MaxLuckyItems {
			return validationError(validationCodeInvalidValue, field, "count is outside the allowed range")
		}
	}
	if total != length || enabled+disabled != total || healthy > total || errorCount > total {
		return validationError(validationCodeInvalidValue, field, "summary counts do not match items")
	}
	return validateLuckyModule(field, status, updatedAt, stale, errorValue)
}

func validateLuckyModule(field string, status LuckyStatus, updatedAt *string, stale bool, errorValue *ExtensionError) error {
	if !validLuckyStatus(status) {
		return validationError(validationCodeInvalidValue, field+".status", "unsupported status")
	}
	if err := validateUpdatedAt(field, updatedAt, stale); err != nil {
		return err
	}
	return ValidateExtensionError(field+".error", errorValue)
}

func validateLuckyIdentity(field, id, displayName, status string, errorValue *ExtensionError) error {
	if err := validateRequiredString(field+".id", id, MaxLuckyNameLength); err != nil {
		return err
	}
	if err := validateRequiredString(field+".display_name", displayName, MaxLuckyNameLength); err != nil {
		return err
	}
	if err := validateRequiredString(field+".status", status, MaxLuckyStatusLength); err != nil {
		return err
	}
	return ValidateExtensionError(field+".error", errorValue)
}

func validatePort(field string, value *int) error {
	if value != nil && (*value < 1 || *value > 65535) {
		return validationError(validationCodeInvalidValue, field, "port is outside the allowed range")
	}
	return nil
}

func validLuckyStatus(value LuckyStatus) bool {
	switch value {
	case LuckyStatusOK, LuckyStatusDegraded, LuckyStatusError, LuckyStatusNotConfigured, LuckyStatusUnavailable, LuckyStatusStale, LuckyStatusUnknown:
		return true
	default:
		return false
	}
}

func validLuckySource(value LuckySource) bool {
	switch value {
	case LuckySourceAPI, LuckySourceLocalAPI, LuckySourceConfig, LuckySourceCLI, LuckySourceWebFallback, LuckySourceUnavailable:
		return true
	default:
		return false
	}
}

func validateRequiredLucky(raw json.RawMessage) error {
	object, err := requiredObject(raw, "lucky")
	if err != nil {
		return err
	}
	return requireFields(object, "lucky", "status", "source", "service", "version", "ip_resolution", "dynamic_dns", "web_services", "port_forwards", "certificates", "updated_at", "stale", "error")
}

func SanitizeLuckyStats(input LuckyStats) LuckyStats {
	result := input
	result.Service.State = SanitizeText(result.Service.State)
	result.Service.Error = sanitizeExtensionError(result.Service.Error)
	result.Version.Current = sanitizeStringPointer(result.Version.Current)
	result.Version.Latest = sanitizeStringPointer(result.Version.Latest)
	result.Version.BuildInfo = sanitizeStringPointer(result.Version.BuildInfo)
	result.Version.CheckedAt = sanitizeStringPointer(result.Version.CheckedAt)
	result.Version.Error = sanitizeExtensionError(result.Version.Error)
	result.IPResolution.Mode = sanitizeStringPointer(result.IPResolution.Mode)
	result.IPResolution.UpdatedAt = sanitizeStringPointer(result.IPResolution.UpdatedAt)
	result.IPResolution.Error = sanitizeExtensionError(result.IPResolution.Error)
	result.DynamicDNS.Records = append([]LuckyDDNSRecord(nil), input.DynamicDNS.Records...)
	if result.DynamicDNS.Records == nil {
		result.DynamicDNS.Records = make([]LuckyDDNSRecord, 0)
	}
	for index := range result.DynamicDNS.Records {
		item := &result.DynamicDNS.Records[index]
		item.ID, item.DisplayName, item.Status = SanitizeText(item.ID), SanitizeText(item.DisplayName), SanitizeText(item.Status)
		item.Provider, item.RecordType = sanitizeStringPointer(item.Provider), sanitizeStringPointer(item.RecordType)
		item.AddressMethod = sanitizeStringPointer(item.AddressMethod)
		item.LocalRecordChangeStatus = sanitizeStringPointer(item.LocalRecordChangeStatus)
		item.LastUpdateAt, item.NextSyncAt, item.LastSuccessAt = sanitizeStringPointer(item.LastUpdateAt), sanitizeStringPointer(item.NextSyncAt), sanitizeStringPointer(item.LastSuccessAt)
		item.Error = sanitizeExtensionError(item.Error)
	}
	result.WebServices.Services = append([]LuckyWebService(nil), input.WebServices.Services...)
	if result.WebServices.Services == nil {
		result.WebServices.Services = make([]LuckyWebService, 0)
	}
	for index := range result.WebServices.Services {
		item := &result.WebServices.Services[index]
		item.ID, item.DisplayName, item.Status, item.Protocol = SanitizeText(item.ID), SanitizeText(item.DisplayName), SanitizeText(item.Status), SanitizeText(item.Protocol)
		item.UpstreamType, item.CertificateRef = sanitizeStringPointer(item.UpstreamType), sanitizeStringPointer(item.CertificateRef)
		item.Error = sanitizeExtensionError(item.Error)
	}
	result.PortForwards.Rules = append([]LuckyPortForward(nil), input.PortForwards.Rules...)
	if result.PortForwards.Rules == nil {
		result.PortForwards.Rules = make([]LuckyPortForward, 0)
	}
	for index := range result.PortForwards.Rules {
		item := &result.PortForwards.Rules[index]
		item.ID, item.DisplayName, item.Status, item.Protocol = SanitizeText(item.ID), SanitizeText(item.DisplayName), SanitizeText(item.Status), SanitizeText(item.Protocol)
		item.TargetType = sanitizeStringPointer(item.TargetType)
		item.Error = sanitizeExtensionError(item.Error)
	}
	result.Certificates.Items = append([]LuckyCertificate(nil), input.Certificates.Items...)
	if result.Certificates.Items == nil {
		result.Certificates.Items = make([]LuckyCertificate, 0)
	}
	for index := range result.Certificates.Items {
		item := &result.Certificates.Items[index]
		item.ID, item.DisplayName, item.Source, item.Status = SanitizeText(item.ID), SanitizeText(item.DisplayName), SanitizeText(item.Source), SanitizeText(item.Status)
		item.Issuer, item.NotBefore, item.NotAfter = sanitizeStringPointer(item.Issuer), sanitizeStringPointer(item.NotBefore), sanitizeStringPointer(item.NotAfter)
		item.LastRenewAt, item.NextRenewAt = sanitizeStringPointer(item.LastRenewAt), sanitizeStringPointer(item.NextRenewAt)
		item.Error = sanitizeExtensionError(item.Error)
	}
	result.DynamicDNS.UpdatedAt, result.WebServices.UpdatedAt = sanitizeStringPointer(result.DynamicDNS.UpdatedAt), sanitizeStringPointer(result.WebServices.UpdatedAt)
	result.PortForwards.UpdatedAt, result.Certificates.UpdatedAt = sanitizeStringPointer(result.PortForwards.UpdatedAt), sanitizeStringPointer(result.Certificates.UpdatedAt)
	result.DynamicDNS.Error, result.WebServices.Error = sanitizeExtensionError(result.DynamicDNS.Error), sanitizeExtensionError(result.WebServices.Error)
	result.PortForwards.Error, result.Certificates.Error = sanitizeExtensionError(result.PortForwards.Error), sanitizeExtensionError(result.Certificates.Error)
	result.UpdatedAt = sanitizeStringPointer(result.UpdatedAt)
	result.Error = sanitizeExtensionError(result.Error)
	return result
}
