package main

import (
	"encoding/json"
	"math"
	"sort"
)

func DecodeUniFiStatsJSON(data []byte) (*UniFiStats, error) {
	if len(data) > MaxUniFiPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "unifi", "object exceeds the allowed size")
	}
	if err := validateRequiredUniFi(data); err != nil {
		return nil, err
	}
	var stats UniFiStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	stats = SanitizeUniFiStats(stats)
	if err := ValidateUniFiStats(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}

func ValidateUniFiStats(stats *UniFiStats) error {
	if stats == nil || !validUniFiTransportStatus(stats.Transport.Status) {
		return validationError(validationCodeInvalidValue, "unifi", "contains an unsupported transport status")
	}
	if err := validateDateTime("unifi.transport.last_attempt", stats.Transport.LastAttempt, true); err != nil {
		return err
	}
	if err := validateDateTime("unifi.transport.last_success", stats.Transport.LastSuccess, true); err != nil {
		return err
	}
	if err := validateDateTime("unifi.updated_at", stats.UpdatedAt, true); err != nil {
		return err
	}
	if err := ValidateExtensionError("unifi.error", stats.Error); err != nil {
		return err
	}
	if !stats.Configured {
		if stats.Profile != nil || stats.System != nil || stats.Stale || stats.Error != nil || stats.Transport.Status != UniFiTransportDisabled {
			return validationError(validationCodeInvalidValue, "unifi", "disabled telemetry must not claim a collection result")
		}
	} else {
		if stats.Profile == nil || (*stats.Profile != "udw" && *stats.Profile != "ucg-max" && *stats.Profile != "unknown") {
			return validationError(validationCodeInvalidValue, "unifi.profile", "must be an explicitly supported profile or a decode-safe unknown marker")
		}
		if *stats.Profile == "unknown" && (!stats.Stale || stats.Error == nil) {
			return validationError(validationCodeInvalidValue, "unifi.profile", "unknown profile is only valid for a degraded decode-safe observation")
		}
		if stats.Transport.Status == UniFiTransportDisabled {
			return validationError(validationCodeInvalidValue, "unifi.transport.status", "configured telemetry cannot be disabled")
		}
		if stats.Stale && stats.Error == nil {
			return validationError(validationCodeInvalidValue, "unifi.error", "stale telemetry requires an error")
		}
		if !stats.Stale && stats.Error != nil {
			return validationError(validationCodeInvalidValue, "unifi.error", "fresh telemetry cannot carry an error")
		}
		if stats.System != nil {
			if err := validateUniFiSystem(stats.System); err != nil {
				return err
			}
		}
		if !stats.Stale && stats.System == nil {
			return validationError(validationCodeInvalidValue, "unifi.system", "fresh telemetry requires a system observation")
		}
	}
	if stats.Fans == nil || stats.PowerSupplies == nil || stats.Diagnostics.Ignored == nil {
		return validationError(validationCodeInvalidValue, "unifi", "arrays must not be null")
	}
	if len(stats.Fans) > MaxUniFiFans || len(stats.PowerSupplies) > MaxUniFiPowerSupplies || len(stats.Diagnostics.Ignored) > MaxUniFiIgnoredObservations {
		return validationError(validationCodeInvalidValue, "unifi", "collection exceeds the allowed size")
	}
	if err := validateUniFiFans(stats.Fans); err != nil {
		return err
	}
	if err := validateUniFiPower(stats.PowerSupplies); err != nil {
		return err
	}
	if err := validateUniFiStorage(stats.Storage); err != nil {
		return err
	}
	if stats.Diagnostics.CollectionStatus != "not_collected" && stats.Diagnostics.CollectionStatus != "available" && stats.Diagnostics.CollectionStatus != "partial" && stats.Diagnostics.CollectionStatus != "unavailable" {
		return validationError(validationCodeInvalidValue, "unifi.diagnostics.collection_status", "is invalid")
	}
	for _, item := range stats.Diagnostics.Ignored {
		if err := validateRequiredString("unifi.diagnostics.ignored_observations.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if item.Reason != "profile_not_populated" && item.Reason != "optional_sensor_unavailable" {
			return validationError(validationCodeInvalidValue, "unifi.diagnostics.ignored_observations.reason", "is invalid")
		}
	}
	return validatePayloadSize("unifi", stats, MaxUniFiPayloadBytes)
}

func validateUniFiSystem(value *UniFiSystemStats) error {
	if value == nil || value.Memory == nil || value.LoadAverage == nil {
		return validationError(validationCodeInvalidValue, "unifi.system", "is incomplete")
	}
	if err := validateOptionalBoundedFloat("unifi.system.cpu_usage_percent", value.CPUUsagePercent, 100); err != nil {
		return err
	}
	if err := validateOptionalEnum("unifi.system.cpu_usage_reason", value.CPUUsageReason, "insufficient_delta", "counter_reset", "zero_delta", "invalid_sample"); err != nil {
		return err
	}
	if value.CPUUsagePercent == nil && value.CPUUsageReason == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_usage", "unavailable CPU usage requires a reason")
	}
	if value.CPUUsagePercent != nil && value.CPUUsageReason != nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_usage", "numeric CPU usage cannot include a reason")
	}
	if value.CPUTemperatureC == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_temperature_c", "is required")
	}
	if err := validateTemperature("unifi.system.cpu_temperature_c", *value.CPUTemperatureC); err != nil {
		return err
	}
	if value.UptimeSeconds == nil || math.IsNaN(*value.UptimeSeconds) || math.IsInf(*value.UptimeSeconds, 0) || *value.UptimeSeconds < 0 || *value.UptimeSeconds > float64(MaxSafeInteger) {
		return validationError(validationCodeInvalidValue, "unifi.system.uptime_seconds", "is invalid")
	}
	for field, value := range map[string]*float64{"one_minute": value.LoadAverage.OneMinute, "five_minutes": value.LoadAverage.FiveMinutes, "fifteen_minutes": value.LoadAverage.FifteenMinutes} {
		if value == nil || math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > float64(MaxSafeInteger) {
			return validationError(validationCodeInvalidValue, "unifi.system.load_average."+field, "is invalid")
		}
	}
	return validateUniFiMemory(value.Memory)
}

func validateUniFiMemory(value *UniFiMemoryStats) error {
	if value == nil || value.TotalBytes == nil || value.AvailableBytes == nil || value.UsedBytes == nil || value.UsedPercent == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.memory", "is incomplete")
	}
	for field, item := range map[string]*int64{"total_bytes": value.TotalBytes, "available_bytes": value.AvailableBytes, "free_bytes": value.FreeBytes, "buffers_bytes": value.BuffersBytes, "cached_bytes": value.CachedBytes, "swap_total_bytes": value.SwapTotalBytes, "swap_free_bytes": value.SwapFreeBytes, "used_bytes": value.UsedBytes} {
		if err := validateCounter("unifi.system.memory."+field, item, MaxSafeInteger); err != nil {
			return err
		}
	}
	if *value.TotalBytes <= 0 || *value.AvailableBytes > *value.TotalBytes || *value.UsedBytes < 0 || *value.UsedBytes+*value.AvailableBytes != *value.TotalBytes {
		return validationError(validationCodeInvalidValue, "unifi.system.memory", "total, available, and used values are inconsistent")
	}
	if math.IsNaN(*value.UsedPercent) || math.IsInf(*value.UsedPercent, 0) || *value.UsedPercent < 0 || *value.UsedPercent > 100 {
		return validationError(validationCodeInvalidValue, "unifi.system.memory.used_percent", "is invalid")
	}
	if value.AvailableSource != "mem_available" && value.AvailableSource != "fallback_memfree_buffers_cached" {
		return validationError(validationCodeInvalidValue, "unifi.system.memory.available_source", "is invalid")
	}
	return nil
}

func validateUniFiFans(items []UniFiFanStats) error {
	ids := map[string]struct{}{}
	for _, item := range items {
		if err := validateRequiredString("unifi.fans.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if _, exists := ids[item.ID]; exists {
			return validationError(validationCodeInvalidValue, "unifi.fans", "IDs must be unique")
		}
		ids[item.ID] = struct{}{}
		if !validUniFiCapability(item.Supported) || !validUniFiPresence(item.Present) || !validUniFiObservation(item.State) {
			return validationError(validationCodeInvalidValue, "unifi.fans", "contains an invalid capability state")
		}
		if item.RPM != nil && (*item.RPM < 0 || *item.RPM > 100000) {
			return validationError(validationCodeInvalidValue, "unifi.fans.rpm", "is invalid")
		}
		if item.Observed != (item.State == UniFiObservationObserved || item.State == UniFiObservationObservedZeroRPM) {
			return validationError(validationCodeInvalidValue, "unifi.fans.observed", "does not match state")
		}
		if !item.Observed && item.RPM != nil {
			return validationError(validationCodeInvalidValue, "unifi.fans.rpm", "requires an observed fan")
		}
		if item.State == UniFiObservationObservedZeroRPM && (item.RPM == nil || *item.RPM != 0) {
			return validationError(validationCodeInvalidValue, "unifi.fans.state", "requires zero RPM")
		}
		if err := ValidateExtensionError("unifi.fans.error", item.Error); err != nil {
			return err
		}
	}
	return nil
}

func validateUniFiPower(items []UniFiPowerStats) error {
	ids := map[string]struct{}{}
	for _, item := range items {
		if err := validateRequiredString("unifi.power_supplies.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if _, exists := ids[item.ID]; exists {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies", "IDs must be unique")
		}
		ids[item.ID] = struct{}{}
		if !validUniFiCapability(item.Supported) || !validUniFiPresence(item.Present) || !validUniFiObservation(item.State) {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies", "contains an invalid capability state")
		}
		if item.Observed != (item.State == UniFiObservationObserved || item.State == UniFiObservationObservedZeroRPM) {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies.observed", "does not match state")
		}
		if err := ValidateExtensionError("unifi.power_supplies.error", item.Error); err != nil {
			return err
		}
	}
	return nil
}

func validateUniFiStorage(value UniFiStorageStats) error {
	if err := validateUniFiStorageCapability("unifi.storage.nvme", value.NVMe); err != nil {
		return err
	}
	for name, capability := range map[string]*UniFiStorageCapability{
		"sata_ssd": value.SATA,
		"tf":       value.TF,
	} {
		if capability != nil {
			if err := validateUniFiStorageCapability("unifi.storage."+name, *capability); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateUniFiStorageCapability(field string, value UniFiStorageCapability) error {
	if !validUniFiCapability(value.Supported) || !validUniFiPresence(value.Present) {
		return validationError(validationCodeInvalidValue, field, "contains an invalid capability state")
	}
	if value.CapacityBytes != nil && (*value.CapacityBytes < 0 || *value.CapacityBytes > MaxSafeInteger) {
		return validationError(validationCodeInvalidValue, field+".capacity_bytes", "is invalid")
	}
	return nil
}

func validUniFiTransportStatus(value UniFiTransportStatus) bool {
	return value == UniFiTransportDisabled || value == UniFiTransportNotCollected || value == UniFiTransportAvailable || value == UniFiTransportUnavailable
}
func validUniFiCapability(value UniFiCapabilityState) bool {
	return value == UniFiCapabilitySupported || value == UniFiCapabilityUnknown || value == UniFiCapabilityUnsupported
}
func validUniFiPresence(value UniFiPresenceState) bool {
	return value == UniFiPresencePresent || value == UniFiPresenceNotPresent || value == UniFiPresenceNotPopulated || value == UniFiPresenceUnknown
}
func validUniFiObservation(value UniFiObservationState) bool {
	return value == UniFiObservationNotObserved || value == UniFiObservationObserved || value == UniFiObservationObservedZeroRPM || value == UniFiObservationUnknown
}

func validateRequiredUniFi(raw json.RawMessage) error {
	object, err := requiredObject(raw, "unifi")
	if err != nil {
		return err
	}
	if err := requireFields(object, "unifi", "configured", "profile", "transport", "system", "fans", "power_supplies", "storage", "diagnostics", "updated_at", "stale", "error"); err != nil {
		return err
	}
	for _, spec := range []struct {
		key, field string
		required   []string
	}{
		{"transport", "unifi.transport", []string{"status", "last_attempt", "last_success"}},
		{"storage", "unifi.storage", []string{"nvme"}},
		{"diagnostics", "unifi.diagnostics", []string{"collection_status", "ignored_observations"}},
	} {
		child, childErr := requiredObject(object[spec.key], spec.field)
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, spec.field, spec.required...); childErr != nil {
			return childErr
		}
	}
	if object["system"] != nil && string(object["system"]) != "null" {
		child, childErr := requiredObject(object["system"], "unifi.system")
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, "unifi.system", "cpu_usage_percent", "cpu_usage_reason", "cpu_temperature_c", "memory", "uptime_seconds", "load_average"); childErr != nil {
			return childErr
		}
	}
	return nil
}

func SanitizeUniFiStats(input UniFiStats) UniFiStats {
	result := input
	result.Profile = sanitizeStringPointer(result.Profile)
	result.Transport.LastAttempt = sanitizeStringPointer(result.Transport.LastAttempt)
	result.Transport.LastSuccess = sanitizeStringPointer(result.Transport.LastSuccess)
	result.UpdatedAt = sanitizeStringPointer(result.UpdatedAt)
	result.Error = sanitizeExtensionError(result.Error)
	result.Fans = append([]UniFiFanStats(nil), input.Fans...)
	result.PowerSupplies = append([]UniFiPowerStats(nil), input.PowerSupplies...)
	result.Diagnostics.Ignored = append([]UniFiIgnoredObservation(nil), input.Diagnostics.Ignored...)
	if input.Fans != nil && result.Fans == nil {
		result.Fans = make([]UniFiFanStats, 0)
	}
	if input.PowerSupplies != nil && result.PowerSupplies == nil {
		result.PowerSupplies = make([]UniFiPowerStats, 0)
	}
	if input.Diagnostics.Ignored != nil && result.Diagnostics.Ignored == nil {
		result.Diagnostics.Ignored = make([]UniFiIgnoredObservation, 0)
	}
	for index := range result.Fans {
		result.Fans[index].ID = SanitizeText(result.Fans[index].ID)
		result.Fans[index].Error = sanitizeExtensionError(result.Fans[index].Error)
	}
	for index := range result.PowerSupplies {
		result.PowerSupplies[index].ID = SanitizeText(result.PowerSupplies[index].ID)
		result.PowerSupplies[index].Error = sanitizeExtensionError(result.PowerSupplies[index].Error)
	}
	for index := range result.Diagnostics.Ignored {
		result.Diagnostics.Ignored[index].ID = SanitizeText(result.Diagnostics.Ignored[index].ID)
		result.Diagnostics.Ignored[index].Reason = SanitizeText(result.Diagnostics.Ignored[index].Reason)
	}
	sort.SliceStable(result.Fans, func(i, j int) bool { return result.Fans[i].ID < result.Fans[j].ID })
	sort.SliceStable(result.PowerSupplies, func(i, j int) bool { return result.PowerSupplies[i].ID < result.PowerSupplies[j].ID })
	sort.SliceStable(result.Diagnostics.Ignored, func(i, j int) bool { return result.Diagnostics.Ignored[i].ID < result.Diagnostics.Ignored[j].ID })
	return result
}
