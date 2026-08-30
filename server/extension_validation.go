package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	validationCodeInvalidJSON     = "invalid_json"
	validationCodeUnknownField    = "unknown_field"
	validationCodeMissingField    = "missing_field"
	validationCodeInvalidValue    = "invalid_value"
	validationCodePayloadTooLarge = "payload_too_large"
)

var (
	profileNamePattern      = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	errorCodePattern        = regexp.MustCompile(`^[a-z0-9_]+$`)
	errorSourcePattern      = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	physicalDiskIDPattern   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.+-]*$`)
	devicePathPattern       = regexp.MustCompile(`^/dev/[A-Za-z0-9._+/-]+$`)
	filesystemTextPattern   = regexp.MustCompile(`^[A-Za-z0-9._+-]+$`)
	gitRevisionPattern      = regexp.MustCompile(`^[0-9a-f]{40}$`)
	controlCharacterPattern = regexp.MustCompile(`[\x00-\x1F\x7F]`)
	secretPatterns          = []*regexp.Regexp{
		regexp.MustCompile(`(?i)authorization\s*:`),
		regexp.MustCompile(`(?i)\bbearer\s+\S+`),
		regexp.MustCompile(`(?i)(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|token)\s*[:=]`),
		regexp.MustCompile(`(?i)--(token|password)(=|\s+)`),
		regexp.MustCompile(`(?i)[?&](api[_-]?key|key|token|password)=`),
		regexp.MustCompile(`(?i)(^|/)\.env($|[./])`),
	}
	secretPathPattern = regexp.MustCompile(`(?i)(^|/)(\.env($|[.:/])|[^/:]*(secret|credential|password|token|auth)[^/:]*)($|[/:])`)
)

type ExtensionValidationError struct {
	Code    string
	Field   string
	Message string
}

func (e *ExtensionValidationError) Error() string {
	return fmt.Sprintf("%s: %s: %s", e.Code, e.Field, e.Message)
}

func validationError(code, field, message string) error {
	return &ExtensionValidationError{Code: code, Field: field, Message: message}
}

func DecodeExtensionStatsJSON(data []byte) (*ExtensionStats, error) {
	if len(data) > MaxExtensionPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "extension", "payload exceeds the allowed size")
	}
	if err := validateRequiredExtensionFields(data, false); err != nil {
		return nil, err
	}
	var stats ExtensionStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	stats = SanitizeExtensionStats(stats)
	if err := ValidateExtensionStats(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}

func DecodeExtensionSnapshotJSON(data []byte) (*ExtensionSnapshot, error) {
	if len(data) > MaxExtensionPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "extension", "payload exceeds the allowed size")
	}
	if err := validateRequiredExtensionFields(data, true); err != nil {
		return nil, err
	}
	var snapshot ExtensionSnapshot
	if err := decodeStrictJSON(data, &snapshot); err != nil {
		return nil, err
	}
	stats := SanitizeExtensionStats(ExtensionStats{
		ExtensionVersion: snapshot.ExtensionVersion,
		Hardware:         snapshot.Hardware,
		Docker:           snapshot.Docker,
		Hermes:           snapshot.Hermes,
		Lucky:            snapshot.Lucky,
		EasyTier:         snapshot.EasyTier,
		UniFi:            snapshot.UniFi,
		ClientBuild:      snapshot.ClientBuild,
	})
	snapshot.ExtensionVersion = stats.ExtensionVersion
	snapshot.Hardware = stats.Hardware
	snapshot.Docker = stats.Docker
	snapshot.Hermes = stats.Hermes
	snapshot.Lucky = stats.Lucky
	snapshot.EasyTier = stats.EasyTier
	snapshot.UniFi = stats.UniFi
	snapshot.ClientBuild = stats.ClientBuild
	if ContainsSecretLikeText(snapshot.ReceivedAt) {
		snapshot.ReceivedAt = RedactedValue
	}
	if err := ValidateExtensionSnapshot(&snapshot); err != nil {
		return nil, err
	}
	return &snapshot, nil
}

func DecodeHardwareStatsJSON(data []byte) (*HardwareStats, error) {
	if len(data) > MaxHardwarePayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "hardware", "object exceeds the allowed size")
	}
	if err := validateRequiredHardware(data); err != nil {
		return nil, err
	}
	var stats HardwareStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	sanitized := SanitizeExtensionStats(ExtensionStats{Hardware: &stats})
	if err := ValidateHardwareStats(sanitized.Hardware); err != nil {
		return nil, err
	}
	return sanitized.Hardware, nil
}

func DecodeDockerStatsJSON(data []byte) (*DockerStats, error) {
	if len(data) > MaxDockerPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "docker", "object exceeds the allowed size")
	}
	if err := validateRequiredDocker(data); err != nil {
		return nil, err
	}
	var stats DockerStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	sanitized := SanitizeExtensionStats(ExtensionStats{Docker: &stats})
	if err := ValidateDockerStats(sanitized.Docker); err != nil {
		return nil, err
	}
	return sanitized.Docker, nil
}

func DecodeHermesStatsJSON(data []byte) (*HermesStats, error) {
	if len(data) > MaxHermesPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "hermes", "object exceeds the allowed size")
	}
	if err := validateRequiredHermes(data); err != nil {
		return nil, err
	}
	var stats HermesStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	sanitized := SanitizeExtensionStats(ExtensionStats{Hermes: &stats})
	if err := ValidateHermesStats(sanitized.Hermes); err != nil {
		return nil, err
	}
	return sanitized.Hermes, nil
}

func decodeStrictJSON(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		if strings.Contains(err.Error(), "unknown field") {
			return validationError(validationCodeUnknownField, "extension", "payload contains an unknown field")
		}
		return validationError(validationCodeInvalidJSON, "extension", "payload is not valid JSON")
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return validationError(validationCodeInvalidJSON, "extension", "payload contains more than one JSON value")
	}
	return nil
}

func ValidateExtensionStats(stats *ExtensionStats) error {
	if stats == nil {
		return validationError(validationCodeInvalidValue, "extension", "object is required")
	}
	if stats.ExtensionVersion != ExtensionSchemaVersion || utf8.RuneCountInString(stats.ExtensionVersion) > MaxExtensionVersionLength {
		return validationError(validationCodeInvalidValue, "extension_version", "unsupported extension version")
	}
	if stats.Hardware == nil || stats.Docker == nil || stats.Hermes == nil {
		return validationError(validationCodeMissingField, "extension", "required domain object is missing")
	}
	if err := ValidateHardwareStats(stats.Hardware); err != nil {
		return err
	}
	if err := ValidateDockerStats(stats.Docker); err != nil {
		return err
	}
	if err := ValidateHermesStats(stats.Hermes); err != nil {
		return err
	}
	if stats.Lucky != nil {
		if err := ValidateLuckyStats(stats.Lucky); err != nil {
			return err
		}
	}
	if stats.EasyTier != nil {
		if err := ValidateEasyTierStats(stats.EasyTier); err != nil {
			return err
		}
	}
	if stats.UniFi != nil {
		if err := ValidateUniFiStats(stats.UniFi); err != nil {
			return err
		}
	}
	if stats.ClientBuild != nil {
		if err := ValidateClientBuildInfo(stats.ClientBuild); err != nil {
			return err
		}
	}
	return validatePayloadSize("extension", stats, MaxExtensionPayloadBytes)
}

func ValidateExtensionSnapshot(snapshot *ExtensionSnapshot) error {
	if snapshot == nil {
		return validationError(validationCodeInvalidValue, "extension", "object is required")
	}
	if err := validateDateTime("received_at", &snapshot.ReceivedAt, false); err != nil {
		return err
	}
	stats := &ExtensionStats{
		ExtensionVersion: snapshot.ExtensionVersion,
		Hardware:         snapshot.Hardware,
		Docker:           snapshot.Docker,
		Hermes:           snapshot.Hermes,
		Lucky:            snapshot.Lucky,
		EasyTier:         snapshot.EasyTier,
		UniFi:            snapshot.UniFi,
		ClientBuild:      snapshot.ClientBuild,
	}
	if err := ValidateExtensionStats(stats); err != nil {
		return err
	}
	return validatePayloadSize("extension", snapshot, MaxExtensionPayloadBytes)
}

func ValidateHardwareStats(stats *HardwareStats) error {
	if stats == nil {
		return validationError(validationCodeInvalidValue, "hardware", "object is required")
	}
	if err := validateOptionalString("hardware.cpu_model", stats.CPUModel, MaxCPUModelLength); err != nil {
		return err
	}
	if stats.CPUDetails != nil {
		if err := ValidateCPUDetails(stats.CPUDetails); err != nil {
			return err
		}
	}
	if stats.MemoryDetails != nil {
		if err := ValidateMemoryDetails(stats.MemoryDetails); err != nil {
			return err
		}
	}
	if stats.CPUTemperature != nil {
		if err := validateTemperature("hardware.cpu_temperature.value", stats.CPUTemperature.Value); err != nil {
			return err
		}
		if stats.CPUTemperature.Unit != "C" {
			return validationError(validationCodeInvalidValue, "hardware.cpu_temperature.unit", "unit must be C")
		}
		if err := validateOptionalString("hardware.cpu_temperature.source", stats.CPUTemperature.Source, MaxTemperatureSourceLength); err != nil {
			return err
		}
		if err := validateOptionalString("hardware.cpu_temperature.label", stats.CPUTemperature.Label, MaxTemperatureSourceLength); err != nil {
			return err
		}
	}
	if stats.DiskTemperature != nil {
		for field, value := range map[string]*float64{
			"current": stats.DiskTemperature.Current,
			"highest": stats.DiskTemperature.Highest,
			"lowest":  stats.DiskTemperature.Lowest,
		} {
			if value != nil {
				if err := validateTemperature("hardware.disk_temperature."+field, *value); err != nil {
					return err
				}
			}
		}
		if stats.DiskTemperature.Unit != "C" {
			return validationError(validationCodeInvalidValue, "hardware.disk_temperature.unit", "unit must be C")
		}
		if err := validateOptionalString("hardware.disk_temperature.source", stats.DiskTemperature.Source, MaxTemperatureSourceLength); err != nil {
			return err
		}
	}
	if !validDiskSMARTStatus(stats.DiskSMARTStatus) {
		return validationError(validationCodeInvalidValue, "hardware.disk_smart_status", "status is not supported")
	}
	for field, value := range map[string]*int64{
		"disk_power_on_hours": stats.DiskPowerOnHours,
		"disk_written_bytes":  stats.DiskWrittenBytes,
		"disk_read_bytes":     stats.DiskReadBytes,
	} {
		if err := validateCounter("hardware."+field, value, MaxSafeInteger); err != nil {
			return err
		}
	}
	if err := validateOptionalString("hardware.disk_device", stats.DiskDevice, MaxDiskDeviceLength); err != nil {
		return err
	}
	if err := validateOptionalString("hardware.disk_smart_source", stats.DiskSMARTSource, MaxDiskSmartSourceLength); err != nil {
		return err
	}
	if stats.Storage != nil {
		if err := ValidateStorageStats(stats.Storage); err != nil {
			return err
		}
	}
	if stats.SystemIdentity != nil {
		if err := ValidateSystemIdentity(stats.SystemIdentity); err != nil {
			return err
		}
	}
	if err := validateUpdatedAt("hardware", stats.UpdatedAt, stats.Stale); err != nil {
		return err
	}
	if err := ValidateExtensionError("hardware.error", stats.Error); err != nil {
		return err
	}
	return validatePayloadSize("hardware", stats, MaxHardwarePayloadBytes)
}

func ValidateCPUDetails(details *CPUDetails) error {
	if details == nil {
		return validationError(validationCodeInvalidValue, "hardware.cpu_details", "object is required")
	}
	for field, value := range map[string]*string{
		"architecture": details.Architecture, "vendor": details.Vendor, "family": details.Family,
		"model_id": details.ModelID, "model_name": details.ModelName, "stepping": details.Stepping,
		"virtualization": details.Virtualization, "l1d_cache": details.L1DCache, "l1i_cache": details.L1ICache,
		"l2_cache": details.L2Cache, "l3_cache": details.L3Cache, "instruction_sets": details.InstructionSets,
	} {
		if err := validateOptionalString("hardware.cpu_details."+field, value, MaxCPUTextLength); err != nil {
			return err
		}
	}
	for field, value := range map[string]*int{
		"logical_cpus": details.LogicalCPUs, "sockets": details.Sockets,
		"cores_per_socket": details.CoresPerSocket, "threads_per_core": details.ThreadsPerCore,
	} {
		if value != nil && (*value <= 0 || *value > MaxCPUCount) {
			return validationError(validationCodeInvalidValue, "hardware.cpu_details."+field, "value is outside the allowed range")
		}
	}
	for field, value := range map[string]*float64{
		"max_mhz": details.MaxMHz, "min_mhz": details.MinMHz, "current_mhz": details.CurrentMHz,
	} {
		if err := validateOptionalBoundedFloat("hardware.cpu_details."+field, value, MaxCPUFrequencyMHz); err != nil {
			return err
		}
	}
	if details.MinMHz != nil && details.MaxMHz != nil && *details.MinMHz > *details.MaxMHz {
		return validationError(validationCodeInvalidValue, "hardware.cpu_details", "min_mhz cannot exceed max_mhz")
	}
	if details.Usage != nil {
		if err := ValidateCPUUsageStats(details.Usage); err != nil {
			return err
		}
	}
	return nil
}

func ValidateCPUUsageStats(usage *CPUUsageStats) error {
	if usage == nil {
		return validationError(validationCodeInvalidValue, "hardware.cpu_details.usage", "object is required")
	}
	values := map[string]*float64{
		"user_percent": usage.UserPercent, "nice_percent": usage.NicePercent, "system_percent": usage.SystemPercent,
		"idle_percent": usage.IdlePercent, "iowait_percent": usage.IOWaitPercent, "irq_percent": usage.IRQPercent,
		"softirq_percent": usage.SoftIRQPercent, "steal_percent": usage.StealPercent, "total_percent": usage.TotalPercent,
	}
	for field, value := range values {
		if err := validateOptionalBoundedFloat("hardware.cpu_details.usage."+field, value, 100); err != nil {
			return err
		}
	}
	if usage.IdlePercent != nil && usage.TotalPercent != nil && math.Abs(*usage.TotalPercent-(100-*usage.IdlePercent)) > 0.2 {
		return validationError(validationCodeInvalidValue, "hardware.cpu_details.usage.total_percent", "must equal 100 minus idle_percent")
	}
	return nil
}

func ValidateMemoryDetails(memory *MemoryDetails) error {
	if memory == nil {
		return validationError(validationCodeInvalidValue, "hardware.memory_details", "object is required")
	}
	values := map[string]*int64{
		"total_bytes": memory.TotalBytes, "used_bytes": memory.UsedBytes, "available_bytes": memory.AvailableBytes,
		"free_bytes": memory.FreeBytes, "buffers_bytes": memory.BuffersBytes, "cached_bytes": memory.CachedBytes,
		"reclaimable_bytes": memory.ReclaimableBytes, "active_bytes": memory.ActiveBytes,
		"inactive_bytes": memory.InactiveBytes, "dirty_bytes": memory.DirtyBytes, "writeback_bytes": memory.WritebackBytes,
		"slab_bytes": memory.SlabBytes, "swap_total_bytes": memory.SwapTotalBytes,
		"swap_used_bytes": memory.SwapUsedBytes, "swap_free_bytes": memory.SwapFreeBytes,
		"swap_cached_bytes": memory.SwapCachedBytes,
	}
	for field, value := range values {
		if err := validateCounter("hardware.memory_details."+field, value, MaxSafeInteger); err != nil {
			return err
		}
	}
	if memory.TotalBytes == nil || *memory.TotalBytes <= 0 {
		return validationError(validationCodeInvalidValue, "hardware.memory_details.total_bytes", "must be present and positive")
	}
	for field, value := range map[string]*int64{
		"used_bytes": memory.UsedBytes, "available_bytes": memory.AvailableBytes, "free_bytes": memory.FreeBytes,
		"buffers_bytes": memory.BuffersBytes, "cached_bytes": memory.CachedBytes, "reclaimable_bytes": memory.ReclaimableBytes,
		"active_bytes": memory.ActiveBytes, "inactive_bytes": memory.InactiveBytes, "dirty_bytes": memory.DirtyBytes,
		"writeback_bytes": memory.WritebackBytes, "slab_bytes": memory.SlabBytes,
	} {
		if value != nil && *value > *memory.TotalBytes {
			return validationError(validationCodeInvalidValue, "hardware.memory_details."+field, "cannot exceed total_bytes")
		}
	}
	if memory.UsedBytes == nil || memory.AvailableBytes == nil || *memory.UsedBytes+*memory.AvailableBytes != *memory.TotalBytes {
		return validationError(validationCodeInvalidValue, "hardware.memory_details", "used_bytes and available_bytes must partition total_bytes")
	}
	if memory.SwapTotalBytes != nil {
		for field, value := range map[string]*int64{"swap_used_bytes": memory.SwapUsedBytes, "swap_free_bytes": memory.SwapFreeBytes, "swap_cached_bytes": memory.SwapCachedBytes} {
			if value != nil && *value > *memory.SwapTotalBytes {
				return validationError(validationCodeInvalidValue, "hardware.memory_details."+field, "cannot exceed swap_total_bytes")
			}
		}
		if memory.SwapUsedBytes == nil || memory.SwapFreeBytes == nil || *memory.SwapUsedBytes+*memory.SwapFreeBytes != *memory.SwapTotalBytes {
			return validationError(validationCodeInvalidValue, "hardware.memory_details", "swap_used_bytes and swap_free_bytes must partition swap_total_bytes")
		}
	}
	return nil
}

func ValidateStorageStats(storage *StorageStats) error {
	if storage == nil {
		return validationError(validationCodeInvalidValue, "hardware.storage", "object is required")
	}
	if storage.PhysicalDisks == nil || storage.Filesystems == nil {
		return validationError(validationCodeInvalidValue, "hardware.storage", "arrays must not be null")
	}
	if len(storage.PhysicalDisks) > MaxPhysicalDisks || len(storage.Filesystems) > MaxFilesystems {
		return validationError(validationCodeInvalidValue, "hardware.storage", "collection exceeds the allowed size")
	}
	diskIDs := make(map[string]struct{}, len(storage.PhysicalDisks))
	smartCounts := map[DiskSMARTStatus]int{DiskSMARTPassed: 0, DiskSMARTFailed: 0, DiskSMARTUnknown: 0}
	var temperatureMin, temperatureMax *float64
	for index := range storage.PhysicalDisks {
		disk := &storage.PhysicalDisks[index]
		if err := validatePhysicalDiskStats(index, disk); err != nil {
			return err
		}
		if _, exists := diskIDs[disk.ID]; exists {
			return validationError(validationCodeInvalidValue, "hardware.storage.physical_disks", "disk IDs must be unique")
		}
		diskIDs[disk.ID] = struct{}{}
		smartCounts[disk.SMARTStatus]++
		if disk.TemperatureC != nil {
			if temperatureMin == nil || *disk.TemperatureC < *temperatureMin {
				value := *disk.TemperatureC
				temperatureMin = &value
			}
			if temperatureMax == nil || *disk.TemperatureC > *temperatureMax {
				value := *disk.TemperatureC
				temperatureMax = &value
			}
		}
	}
	for index := range storage.Filesystems {
		if err := validateFilesystemStats(index, &storage.Filesystems[index], diskIDs); err != nil {
			return err
		}
	}
	if err := validateStorageSummary(storage.Summary, len(storage.PhysicalDisks), len(storage.Filesystems), smartCounts, temperatureMin, temperatureMax); err != nil {
		return err
	}
	if err := validateUpdatedAt("hardware.storage", storage.UpdatedAt, storage.Stale); err != nil {
		return err
	}
	if err := ValidateExtensionError("hardware.storage.error", storage.Error); err != nil {
		return err
	}
	return nil
}

func validatePhysicalDiskStats(index int, disk *PhysicalDiskStats) error {
	if disk == nil {
		return validationError(validationCodeInvalidValue, "hardware.storage.physical_disks", "item is required")
	}
	prefix := fmt.Sprintf("hardware.storage.physical_disks[%d]", index)
	if err := validateRequiredString(prefix+".id", disk.ID, MaxDiskDeviceLength); err != nil || !physicalDiskIDPattern.MatchString(disk.ID) {
		if err != nil {
			return err
		}
		return validationError(validationCodeInvalidValue, prefix+".id", "must be a safe kernel device ID")
	}
	if err := validateRequiredString(prefix+".device", disk.Device, MaxDiskDeviceLength); err != nil {
		return err
	}
	if !validSafeDevicePath(disk.Device) {
		return validationError(validationCodeInvalidValue, prefix+".device", "must be a safe /dev path")
	}
	if err := validateOptionalString(prefix+".model", disk.Model, MaxDiskModelLength); err != nil {
		return err
	}
	if err := validateCounter(prefix+".capacity_bytes", disk.CapacityBytes, MaxSafeInteger); err != nil {
		return err
	}
	if disk.TemperatureC != nil {
		if err := validateTemperature(prefix+".temperature_c", *disk.TemperatureC); err != nil {
			return err
		}
	}
	if !validDiskSMARTStatus(disk.SMARTStatus) {
		return validationError(validationCodeInvalidValue, prefix+".smart_status", "status is not supported")
	}
	for field, value := range map[string]*int64{
		"power_on_hours": disk.PowerOnHours,
		"written_bytes":  disk.WrittenBytes,
		"read_bytes":     disk.ReadBytes,
	} {
		if err := validateCounter(prefix+"."+field, value, MaxSafeInteger); err != nil {
			return err
		}
	}
	if err := validateOptionalString(prefix+".smart_source", disk.SMARTSource, MaxDiskSmartSourceLength); err != nil {
		return err
	}
	if err := validateOptionalEnum(prefix+".completeness", disk.Completeness, "complete", "partial", "unavailable"); err != nil {
		return err
	}
	if err := validateOptionalEnum(prefix+".health_source", disk.HealthSource, "native_status", "attribute_check", "unknown"); err != nil {
		return err
	}
	if err := validateOptionalEnum(prefix+".native_status", disk.NativeStatus, "available", "unavailable", "unknown"); err != nil {
		return err
	}
	if !validStorageCollectionStatus(disk.CollectionStatus) {
		return validationError(validationCodeInvalidValue, prefix+".collection_status", "status is not supported")
	}
	if disk.CollectionStatus == "partial" {
		if disk.Completeness == nil || *disk.Completeness != "partial" ||
			disk.HealthSource == nil || *disk.HealthSource != "attribute_check" ||
			disk.NativeStatus == nil || *disk.NativeStatus != "unavailable" ||
			(disk.SMARTStatus != DiskSMARTPassed && disk.SMARTStatus != DiskSMARTFailed) ||
			disk.Error == nil || disk.Error.Code != "smart_return_status_unavailable" {
			return validationError(validationCodeInvalidValue, prefix+".collection_status", "partial SMART requires an attribute-check fallback")
		}
	}
	if err := ValidateExtensionError(prefix+".error", disk.Error); err != nil {
		return err
	}
	return nil
}

func validateFilesystemStats(index int, filesystem *FilesystemStats, diskIDs map[string]struct{}) error {
	if filesystem == nil {
		return validationError(validationCodeInvalidValue, "hardware.storage.filesystems", "item is required")
	}
	prefix := fmt.Sprintf("hardware.storage.filesystems[%d]", index)
	if err := validateOptionalString(prefix+".source", filesystem.Source, MaxFilesystemSourceLength); err != nil {
		return err
	}
	if filesystem.Source != nil && !validSafeDevicePath(*filesystem.Source) {
		return validationError(validationCodeInvalidValue, prefix+".source", "must be a safe /dev path")
	}
	if err := validateRequiredString(prefix+".mountpoint", filesystem.Mountpoint, MaxMountpointLength); err != nil {
		return err
	}
	if !validSafeMountpoint(filesystem.Mountpoint) {
		return validationError(validationCodeInvalidValue, prefix+".mountpoint", "must be a safe absolute path")
	}
	if err := validateOptionalString(prefix+".fs_type", filesystem.FSType, MaxFilesystemTypeLength); err != nil {
		return err
	}
	if filesystem.FSType != nil && !filesystemTextPattern.MatchString(*filesystem.FSType) {
		return validationError(validationCodeInvalidValue, prefix+".fs_type", "contains unsupported characters")
	}
	for field, value := range map[string]*int64{
		"total_bytes":     filesystem.TotalBytes,
		"used_bytes":      filesystem.UsedBytes,
		"available_bytes": filesystem.AvailableBytes,
	} {
		if err := validateCounter(prefix+"."+field, value, MaxSafeInteger); err != nil {
			return err
		}
	}
	if filesystem.TotalBytes != nil {
		if filesystem.UsedBytes != nil && *filesystem.UsedBytes > *filesystem.TotalBytes {
			return validationError(validationCodeInvalidValue, prefix+".used_bytes", "cannot exceed total_bytes")
		}
		if filesystem.AvailableBytes != nil && *filesystem.AvailableBytes > *filesystem.TotalBytes {
			return validationError(validationCodeInvalidValue, prefix+".available_bytes", "cannot exceed total_bytes")
		}
	}
	if err := validateOptionalBoundedFloat(prefix+".usage_percent", filesystem.UsagePercent, 100); err != nil {
		return err
	}
	if filesystem.BackingDiskIDs == nil || len(filesystem.BackingDiskIDs) > MaxFilesystemBackingDisks {
		return validationError(validationCodeInvalidValue, prefix+".backing_disk_ids", "array is invalid")
	}
	seen := make(map[string]struct{}, len(filesystem.BackingDiskIDs))
	for diskIndex, diskID := range filesystem.BackingDiskIDs {
		field := fmt.Sprintf("%s.backing_disk_ids[%d]", prefix, diskIndex)
		if err := validateRequiredString(field, diskID, MaxDiskDeviceLength); err != nil || !physicalDiskIDPattern.MatchString(diskID) {
			if err != nil {
				return err
			}
			return validationError(validationCodeInvalidValue, field, "must be a safe kernel device ID")
		}
		if _, exists := seen[diskID]; exists {
			return validationError(validationCodeInvalidValue, prefix+".backing_disk_ids", "disk IDs must be unique")
		}
		if _, exists := diskIDs[diskID]; !exists {
			return validationError(validationCodeInvalidValue, field, "does not reference a reported physical disk")
		}
		seen[diskID] = struct{}{}
	}
	if err := validateRequiredString(prefix+".stack_type", filesystem.StackType, MaxStorageStackTypeLength); err != nil {
		return err
	}
	if !validStorageStackType(filesystem.StackType) || !validStorageCollectionStatus(filesystem.CollectionStatus) {
		return validationError(validationCodeInvalidValue, prefix, "contains an unsupported storage status")
	}
	if filesystem.CollectionStatus == "healthy" && filesystem.FSType == nil {
		return validationError(validationCodeInvalidValue, prefix, "healthy filesystem requires fs_type")
	}
	if err := ValidateExtensionError(prefix+".error", filesystem.Error); err != nil {
		return err
	}
	return nil
}

func validSafeDevicePath(value string) bool {
	if !devicePathPattern.MatchString(value) {
		return false
	}
	parts := strings.Split(value, "/")
	if len(parts) < 3 || parts[0] != "" || parts[1] != "dev" {
		return false
	}
	for _, part := range parts[2:] {
		if part == "" || part == "." || part == ".." {
			return false
		}
	}
	return true
}

func validSafeMountpoint(value string) bool {
	if !strings.HasPrefix(value, "/") {
		return false
	}
	// validateRequiredString has already checked UTF-8, maximum length, and
	// control characters.  Do not impose an ASCII-only restriction here: Linux
	// mountpoints may safely contain spaces and non-ASCII characters.
	for _, part := range strings.Split(value, "/")[1:] {
		if part == ".." {
			return false
		}
	}
	return true
}

func validateStorageSummary(summary StorageSummary, physicalDiskCount, filesystemCount int, smartCounts map[DiskSMARTStatus]int, temperatureMin, temperatureMax *float64) error {
	if summary.PhysicalDiskCount != physicalDiskCount || summary.FilesystemCount != filesystemCount ||
		summary.SMARTPassed != smartCounts[DiskSMARTPassed] || summary.SMARTFailed != smartCounts[DiskSMARTFailed] || summary.SMARTUnknown != smartCounts[DiskSMARTUnknown] {
		return validationError(validationCodeInvalidValue, "hardware.storage.summary", "does not match the bounded inventory")
	}
	if (summary.TemperatureMinC == nil) != (summary.TemperatureMaxC == nil) {
		return validationError(validationCodeInvalidValue, "hardware.storage.summary", "temperature bounds must both be null or present")
	}
	if temperatureMin == nil {
		if summary.TemperatureMinC != nil || summary.TemperatureMaxC != nil {
			return validationError(validationCodeInvalidValue, "hardware.storage.summary", "temperature summary requires observed disk temperatures")
		}
		return nil
	}
	if summary.TemperatureMinC == nil || summary.TemperatureMaxC == nil {
		return validationError(validationCodeInvalidValue, "hardware.storage.summary", "temperature summary is required")
	}
	for field, value := range map[string]float64{"temperature_min_c": *summary.TemperatureMinC, "temperature_max_c": *summary.TemperatureMaxC} {
		if err := validateTemperature("hardware.storage.summary."+field, value); err != nil {
			return err
		}
	}
	if *summary.TemperatureMinC > *summary.TemperatureMaxC || *summary.TemperatureMinC != *temperatureMin || *summary.TemperatureMaxC != *temperatureMax {
		return validationError(validationCodeInvalidValue, "hardware.storage.summary", "temperature bounds do not match observed disks")
	}
	return nil
}

func ValidateSystemIdentity(identity *SystemIdentity) error {
	if identity == nil {
		return validationError(validationCodeInvalidValue, "hardware.system_identity", "object is required")
	}
	for field, value := range map[string]*string{
		"distribution":    identity.Distribution,
		"release_version": identity.ReleaseVersion,
		"pretty_name":     identity.PrettyName,
		"kernel_release":  identity.KernelRelease,
		"architecture":    identity.Architecture,
	} {
		if err := validateOptionalString("hardware.system_identity."+field, value, MaxSystemIdentityLength); err != nil {
			return err
		}
	}
	if identity.Source != "os-release" && identity.Source != "dsm-version" && identity.Source != "unknown" && identity.Source != "unavailable" {
		return validationError(validationCodeInvalidValue, "hardware.system_identity.source", "source is not supported")
	}
	return nil
}

func ValidateClientBuildInfo(build *ClientBuildInfo) error {
	if build == nil {
		return validationError(validationCodeInvalidValue, "client_build", "object is required")
	}
	if err := validateRequiredString("client_build.version", build.Version, MaxBuildVersionLength); err != nil {
		return err
	}
	if err := validateRequiredString("client_build.revision", build.Revision, MaxBuildRevisionLength); err != nil {
		return err
	}
	if !gitRevisionPattern.MatchString(build.Revision) {
		return validationError(validationCodeInvalidValue, "client_build.revision", "must be a full lowercase Git SHA")
	}
	if err := validateDateTime("client_build.build_time", build.BuildTime, true); err != nil {
		return err
	}
	if build.Protocol != "device_v2" {
		return validationError(validationCodeInvalidValue, "client_build.protocol", "must be device_v2")
	}
	return nil
}

func validStorageCollectionStatus(value string) bool {
	return value == "healthy" || value == "partial" || value == "unavailable" || value == "unsupported" || value == "permission_denied" || value == "invalid_data"
}

func validStorageStackType(value string) bool {
	return value == "plain" || value == "lvm" || value == "mdraid" || value == "device_mapper" || value == "btrfs" || value == "unknown"
}

func ValidateDockerStats(stats *DockerStats) error {
	if stats == nil {
		return validationError(validationCodeInvalidValue, "docker", "object is required")
	}
	if stats.Running < 0 || stats.Running > MaxDockerCount || stats.Total < 0 || stats.Total > MaxDockerCount {
		return validationError(validationCodeInvalidValue, "docker", "container count is outside the allowed range")
	}
	if stats.Running > stats.Total {
		return validationError(validationCodeInvalidValue, "docker.running", "running count cannot exceed total count")
	}
	if stats.Limit < 0 || stats.Limit > MaxDockerContainers {
		return validationError(validationCodeInvalidValue, "docker.limit", "limit is outside the allowed range")
	}
	if stats.Containers == nil {
		return validationError(validationCodeInvalidValue, "docker.containers", "array must not be null")
	}
	if len(stats.Containers) > MaxDockerContainers {
		return validationError(validationCodeInvalidValue, "docker.containers", "array exceeds the allowed size")
	}
	if stats.Truncated {
		if len(stats.Containers) >= stats.Total {
			return validationError(validationCodeInvalidValue, "docker.truncated", "truncated list must contain fewer items than total")
		}
	} else if len(stats.Containers) != stats.Total {
		return validationError(validationCodeInvalidValue, "docker.containers", "complete list size must equal total")
	}
	for index := range stats.Containers {
		if err := validateDockerContainer(index, &stats.Containers[index]); err != nil {
			return err
		}
	}
	if err := validateUpdatedAt("docker", stats.UpdatedAt, stats.Stale); err != nil {
		return err
	}
	if err := ValidateExtensionError("docker.error", stats.Error); err != nil {
		return err
	}
	return validatePayloadSize("docker", stats, MaxDockerPayloadBytes)
}

func validateDockerContainer(index int, container *DockerContainerStats) error {
	prefix := fmt.Sprintf("docker.containers[%d]", index)
	for field, item := range map[string]struct {
		value string
		limit int
	}{
		"names":  {container.Names, MaxDockerNameLength},
		"image":  {container.Image, MaxDockerImageLength},
		"status": {container.Status, MaxDockerStatusLength},
		"ports":  {container.Ports, MaxDockerPortsLength},
	} {
		if err := validateRequiredString(prefix+"."+field, item.value, item.limit); err != nil {
			return err
		}
	}
	return nil
}

func ValidateHermesStats(stats *HermesStats) error {
	if stats == nil {
		return validationError(validationCodeInvalidValue, "hermes", "object is required")
	}
	if stats.Profiles == nil {
		return validationError(validationCodeInvalidValue, "hermes.profiles", "array must not be null")
	}
	if len(stats.Profiles) > MaxHermesProfiles {
		return validationError(validationCodeInvalidValue, "hermes.profiles", "array exceeds the allowed size")
	}
	seenProfiles := make(map[string]struct{}, len(stats.Profiles))
	for index := range stats.Profiles {
		if err := ValidateHermesProfileStats(index, &stats.Profiles[index]); err != nil {
			return err
		}
		name := stats.Profiles[index].Profile
		if _, exists := seenProfiles[name]; exists {
			return validationError(validationCodeInvalidValue, "hermes.profiles", "profile names must be unique")
		}
		seenProfiles[name] = struct{}{}
	}
	if err := validateUpdatedAt("hermes", stats.UpdatedAt, stats.Stale); err != nil {
		return err
	}
	if err := ValidateExtensionError("hermes.error", stats.Error); err != nil {
		return err
	}
	return validatePayloadSize("hermes", stats, MaxHermesPayloadBytes)
}

func ValidateHermesProfileStats(index int, profile *HermesProfileStats) error {
	prefix := fmt.Sprintf("hermes.profiles[%d]", index)
	if profile == nil {
		return validationError(validationCodeInvalidValue, prefix, "object is required")
	}
	if err := validateRequiredString(prefix+".profile", profile.Profile, MaxProfileNameLength); err != nil {
		return err
	}
	if !profileNamePattern.MatchString(profile.Profile) {
		return validationError(validationCodeInvalidValue, prefix+".profile", "profile name contains unsupported characters")
	}
	if !validHermesAPIStatus(profile.APIStatus) {
		return validationError(validationCodeInvalidValue, prefix+".api_status", "status is not supported")
	}
	for field, item := range map[string]struct {
		value *string
		limit int
	}{
		"agent_version":   {profile.AgentVersion, MaxAgentVersionLength},
		"service_status":  {profile.ServiceStatus, MaxServiceStatusLength},
		"gateway_service": {profile.GatewayService, MaxGatewayServiceLength},
		"manager_mode":    {profile.ManagerMode, MaxManagerModeLength},
		"provider":        {profile.Provider, MaxProviderLength},
		"model":           {profile.Model, MaxModelLength},
	} {
		if err := validateOptionalString(prefix+"."+field, item.value, item.limit); err != nil {
			return err
		}
	}
	if profile.UsageMode != nil && !validHermesUsageMode(*profile.UsageMode) {
		return validationError(validationCodeInvalidValue, prefix+".usage_mode", "mode is not supported")
	}
	if err := validateDateTime(prefix+".auth_refreshed_at", profile.AuthRefreshedAt, true); err != nil {
		return err
	}
	for field, value := range map[string]*int64{
		"scheduled_jobs_active": profile.ScheduledJobsActive,
		"scheduled_jobs_total":  profile.ScheduledJobsTotal,
		"sessions_active":       profile.SessionsActive,
		"sessions_total":        profile.SessionsTotal,
	} {
		if err := validateCounter(prefix+"."+field, value, MaxHermesCounter); err != nil {
			return err
		}
	}
	if profile.ScheduledJobsActive != nil && profile.ScheduledJobsTotal != nil && *profile.ScheduledJobsActive > *profile.ScheduledJobsTotal {
		return validationError(validationCodeInvalidValue, prefix+".scheduled_jobs_active", "active count cannot exceed total count")
	}
	if profile.SessionsActive != nil && profile.SessionsTotal != nil && *profile.SessionsActive > *profile.SessionsTotal {
		return validationError(validationCodeInvalidValue, prefix+".sessions_active", "active count cannot exceed total count")
	}
	if err := ValidateTokenUsageStats(prefix+".usage", &profile.Usage); err != nil {
		return err
	}
	if profile.ConfigSummary != nil {
		if err := validateConfigSummary(prefix+".config_summary", profile.ConfigSummary); err != nil {
			return err
		}
	}
	if profile.MixtureOfAgents != nil {
		if err := validateMixtureOfAgents(prefix+".mixture_of_agents", profile.MixtureOfAgents); err != nil {
			return err
		}
	}
	if err := validateDateTime(prefix+".received_at", profile.ReceivedAt, true); err != nil {
		return err
	}
	if err := validateUpdatedAt(prefix, profile.UpdatedAt, profile.Stale); err != nil {
		return err
	}
	return ValidateExtensionError(prefix+".error", profile.Error)
}

func validateConfigSummary(prefix string, summary *SanitizedConfigSummary) error {
	if summary == nil {
		return nil
	}
	for field, value := range map[string]string{
		"main_model.provider":         summary.MainModel.Provider,
		"main_model.model":            summary.MainModel.Model,
		"main_model.base_url":         summary.MainModel.BaseURL,
		"delegation.provider":         summary.Delegation.Provider,
		"delegation.model":            summary.Delegation.Model,
		"delegation.base_url":         summary.Delegation.BaseURL,
		"delegation.reasoning_effort": summary.Delegation.ReasoningEffort,
	} {
		limit := MaxModelLength
		if strings.Contains(field, "provider") {
			limit = MaxProviderLength
		} else if strings.Contains(field, "base_url") {
			limit = MaxBaseURLLength
		} else if strings.Contains(field, "reasoning_effort") {
			limit = MaxReasoningEffortLength
		}
		if err := validateStringValue(prefix+"."+field, value, limit); err != nil {
			return err
		}
	}
	if err := validateCounter(prefix+".main_model.concurrency", summary.MainModel.Concurrency, MaxHermesCounter); err != nil {
		return err
	}
	for field, value := range map[string]*int64{
		"delegation.max_concurrent_children": summary.Delegation.MaxConcurrentChildren,
		"delegation.max_spawn_depth":         summary.Delegation.MaxSpawnDepth,
	} {
		if err := validateCounter(prefix+"."+field, value, MaxHermesCounter); err != nil {
			return err
		}
	}
	for field, value := range map[string]*float64{
		"main_model.timeout_seconds":       summary.MainModel.TimeoutSeconds,
		"delegation.child_timeout_seconds": summary.Delegation.ChildTimeoutSeconds,
	} {
		if err := validateDuration(prefix+"."+field, value); err != nil {
			return err
		}
	}
	if summary.AuxiliaryModels == nil {
		return validationError(validationCodeInvalidValue, prefix+".auxiliary_models", "array must not be null")
	}
	if len(summary.AuxiliaryModels) > MaxAuxiliaryModels {
		return validationError(validationCodeInvalidValue, prefix+".auxiliary_models", "array exceeds the allowed size")
	}
	for index := range summary.AuxiliaryModels {
		item := &summary.AuxiliaryModels[index]
		itemPrefix := fmt.Sprintf("%s.auxiliary_models[%d]", prefix, index)
		for field, value := range map[string]string{
			"name": item.Name, "provider": item.Provider, "model": item.Model,
			"effective_provider": item.EffectiveProvider, "effective_model": item.EffectiveModel,
			"source": item.Source, "base_url_display": item.BaseURLDisplay, "language": item.Language,
		} {
			limit := MaxModelLength
			switch field {
			case "name", "source", "language":
				limit = MaxAuxiliaryNameLength
			case "provider", "effective_provider":
				limit = MaxProviderLength
			case "base_url_display":
				limit = MaxBaseURLLength
			}
			if err := validateStringValue(itemPrefix+"."+field, value, limit); err != nil {
				return err
			}
		}
		if err := validateCounter(itemPrefix+".max_concurrency", item.MaxConcurrency, MaxHermesCounter); err != nil {
			return err
		}
		if err := validateDuration(itemPrefix+".timeout_seconds", item.TimeoutSeconds); err != nil {
			return err
		}
		if err := validateDuration(itemPrefix+".download_timeout_seconds", item.DownloadTimeoutSeconds); err != nil {
			return err
		}
	}
	if summary.DockerVolumes == nil {
		return validationError(validationCodeInvalidValue, prefix+".docker_volumes", "array must not be null")
	}
	if len(summary.DockerVolumes) > MaxDockerVolumes {
		return validationError(validationCodeInvalidValue, prefix+".docker_volumes", "array exceeds the allowed size")
	}
	for volumeIndex, volume := range summary.DockerVolumes {
		if err := validateRequiredString(fmt.Sprintf("%s.docker_volumes[%d]", prefix, volumeIndex), volume, MaxDockerVolumeLength); err != nil {
			return err
		}
		if secretPathPattern.MatchString(volume) {
			return validationError(validationCodeInvalidValue, fmt.Sprintf("%s.docker_volumes[%d]", prefix, volumeIndex), "volume contains a disallowed secret path")
		}
	}
	return nil
}

func validateMixtureOfAgents(prefix string, value *MixtureOfAgentsStats) error {
	for field, item := range map[string]struct {
		value string
		limit int
	}{
		"source": {value.Source, MaxErrorSourceLength}, "name": {value.Name, MaxMOANameLength},
		"label": {value.Label, MaxMOANameLength}, "description": {value.Description, MaxMOADescriptionLength},
	} {
		if err := validateStringValue(prefix+"."+field, item.value, item.limit); err != nil {
			return err
		}
	}
	if value.Tools == nil {
		return validationError(validationCodeInvalidValue, prefix+".tools", "array must not be null")
	}
	if len(value.Tools) > MaxMOATools {
		return validationError(validationCodeInvalidValue, prefix+".tools", "array exceeds the allowed size")
	}
	for index, tool := range value.Tools {
		if err := validateRequiredString(fmt.Sprintf("%s.tools[%d]", prefix, index), tool, MaxMOANameLength); err != nil {
			return err
		}
	}
	if value.Error != nil {
		if err := validateOptionalString(prefix+".error", value.Error, MaxErrorCodeLength); err != nil {
			return err
		}
	}
	return nil
}

func ValidateTokenUsageStats(field string, usage *TokenUsageStats) error {
	if usage == nil {
		return validationError(validationCodeInvalidValue, field, "object is required")
	}
	if !validTokenSource(usage.Source) {
		return validationError(validationCodeInvalidValue, field+".source", "source is not supported")
	}
	values := []*int64{usage.InputTokens, usage.OutputTokens, usage.TotalTokens}
	nilValues := 0
	for index, value := range values {
		if value == nil {
			nilValues++
			continue
		}
		if err := validateCounter(fmt.Sprintf("%s.token[%d]", field, index), value, MaxSafeInteger); err != nil {
			return err
		}
	}
	if nilValues != 0 && nilValues != len(values) {
		return validationError(validationCodeInvalidValue, field, "token counters must be all null or all present")
	}
	if nilValues == 0 && *usage.TotalTokens != *usage.InputTokens+*usage.OutputTokens {
		return validationError(validationCodeInvalidValue, field+".total_tokens", "total must equal input plus output")
	}
	if (usage.WindowStart == nil) != (usage.WindowEnd == nil) {
		return validationError(validationCodeInvalidValue, field, "window timestamps must both be null or both be present")
	}
	if err := validateDateTime(field+".window_start", usage.WindowStart, true); err != nil {
		return err
	}
	if err := validateDateTime(field+".window_end", usage.WindowEnd, true); err != nil {
		return err
	}
	if usage.WindowStart != nil && usage.WindowEnd != nil {
		start, _ := time.Parse(time.RFC3339, *usage.WindowStart)
		end, _ := time.Parse(time.RFC3339, *usage.WindowEnd)
		if end.Before(start) {
			return validationError(validationCodeInvalidValue, field, "window end cannot precede window start")
		}
	}
	if usage.Source == TokenSourceUnavailable {
		if nilValues != len(values) || usage.WindowStart != nil || usage.WindowEnd != nil || !usage.Estimated {
			return validationError(validationCodeInvalidValue, field, "unavailable usage must be empty and estimated")
		}
	}
	if (usage.Source == TokenSourceLocalSessionState || usage.Source == TokenSourceLocalLogs) && !usage.Estimated {
		return validationError(validationCodeInvalidValue, field+".estimated", "local fallback usage must be estimated")
	}
	return nil
}

func ValidateExtensionError(field string, extensionError *ExtensionError) error {
	if extensionError == nil {
		return nil
	}
	if err := validateRequiredString(field+".code", extensionError.Code, MaxErrorCodeLength); err != nil {
		return err
	}
	if !errorCodePattern.MatchString(extensionError.Code) {
		return validationError(validationCodeInvalidValue, field+".code", "code contains unsupported characters")
	}
	if err := validateRequiredString(field+".message", extensionError.Message, MaxErrorMessageLength); err != nil {
		return err
	}
	if err := validateRequiredString(field+".source", extensionError.Source, MaxErrorSourceLength); err != nil {
		return err
	}
	if !errorSourcePattern.MatchString(extensionError.Source) {
		return validationError(validationCodeInvalidValue, field+".source", "source contains unsupported characters")
	}
	if ContainsSecretLikeText(extensionError.Code) || ContainsSecretLikeText(extensionError.Message) || ContainsSecretLikeText(extensionError.Source) {
		return validationError(validationCodeInvalidValue, field, "error contains disallowed content")
	}
	if extensionError.HTTPStatus != nil && (*extensionError.HTTPStatus < MinHTTPStatus || *extensionError.HTTPStatus > MaxHTTPStatus) {
		return validationError(validationCodeInvalidValue, field+".http_status", "status is outside the allowed range")
	}
	return nil
}

func ContainsSecretLikeText(value string) bool {
	for _, pattern := range secretPatterns {
		if pattern.MatchString(value) {
			return true
		}
	}
	return false
}

func SanitizeText(value string) string {
	if ContainsSecretLikeText(value) {
		return RedactedValue
	}
	return value
}

func SanitizeExtensionStats(input ExtensionStats) ExtensionStats {
	result := input
	if input.Hardware != nil {
		hardware := *input.Hardware
		hardware.CPUModel = sanitizeStringPointer(hardware.CPUModel)
		hardware.DiskDevice = sanitizeStringPointer(hardware.DiskDevice)
		hardware.DiskSMARTSource = sanitizeStringPointer(hardware.DiskSMARTSource)
		hardware.UpdatedAt = sanitizeStringPointer(hardware.UpdatedAt)
		hardware.Error = sanitizeExtensionError(hardware.Error)
		if hardware.CPUDetails != nil {
			details := *hardware.CPUDetails
			details.Architecture = sanitizeStringPointer(details.Architecture)
			details.Vendor = sanitizeStringPointer(details.Vendor)
			details.Family = sanitizeStringPointer(details.Family)
			details.ModelID = sanitizeStringPointer(details.ModelID)
			details.ModelName = sanitizeStringPointer(details.ModelName)
			details.Stepping = sanitizeStringPointer(details.Stepping)
			details.Virtualization = sanitizeStringPointer(details.Virtualization)
			details.L1DCache = sanitizeStringPointer(details.L1DCache)
			details.L1ICache = sanitizeStringPointer(details.L1ICache)
			details.L2Cache = sanitizeStringPointer(details.L2Cache)
			details.L3Cache = sanitizeStringPointer(details.L3Cache)
			hardware.CPUDetails = &details
		}
		if hardware.CPUTemperature != nil {
			temperature := *hardware.CPUTemperature
			temperature.Source = sanitizeStringPointer(temperature.Source)
			temperature.Label = sanitizeStringPointer(temperature.Label)
			hardware.CPUTemperature = &temperature
		}
		if hardware.DiskTemperature != nil {
			temperature := *hardware.DiskTemperature
			temperature.Source = sanitizeStringPointer(temperature.Source)
			hardware.DiskTemperature = &temperature
		}
		if hardware.Storage != nil {
			storage := *hardware.Storage
			storage.PhysicalDisks = append([]PhysicalDiskStats(nil), hardware.Storage.PhysicalDisks...)
			storage.Filesystems = append([]FilesystemStats(nil), hardware.Storage.Filesystems...)
			if hardware.Storage.PhysicalDisks != nil && storage.PhysicalDisks == nil {
				storage.PhysicalDisks = make([]PhysicalDiskStats, 0)
			}
			if hardware.Storage.Filesystems != nil && storage.Filesystems == nil {
				storage.Filesystems = make([]FilesystemStats, 0)
			}
			for index := range storage.PhysicalDisks {
				disk := &storage.PhysicalDisks[index]
				disk.ID = SanitizeText(disk.ID)
				disk.Device = SanitizeText(disk.Device)
				disk.Model = sanitizeStringPointer(disk.Model)
				disk.SMARTSource = sanitizeStringPointer(disk.SMARTSource)
				disk.CollectionStatus = SanitizeText(disk.CollectionStatus)
				disk.Error = sanitizeExtensionError(disk.Error)
			}
			for index := range storage.Filesystems {
				filesystem := &storage.Filesystems[index]
				filesystem.Source = sanitizeStringPointer(filesystem.Source)
				filesystem.Mountpoint = SanitizeText(filesystem.Mountpoint)
				filesystem.FSType = sanitizeStringPointer(filesystem.FSType)
				filesystem.StackType = SanitizeText(filesystem.StackType)
				filesystem.CollectionStatus = SanitizeText(filesystem.CollectionStatus)
				filesystem.Error = sanitizeExtensionError(filesystem.Error)
				filesystem.BackingDiskIDs = append([]string(nil), filesystem.BackingDiskIDs...)
				if filesystem.BackingDiskIDs == nil {
					filesystem.BackingDiskIDs = make([]string, 0)
				}
				for diskIndex := range filesystem.BackingDiskIDs {
					filesystem.BackingDiskIDs[diskIndex] = SanitizeText(filesystem.BackingDiskIDs[diskIndex])
				}
			}
			storage.UpdatedAt = sanitizeStringPointer(storage.UpdatedAt)
			storage.Error = sanitizeExtensionError(storage.Error)
			hardware.Storage = &storage
		}
		if hardware.SystemIdentity != nil {
			identity := *hardware.SystemIdentity
			identity.Distribution = sanitizeStringPointer(identity.Distribution)
			identity.ReleaseVersion = sanitizeStringPointer(identity.ReleaseVersion)
			identity.PrettyName = sanitizeStringPointer(identity.PrettyName)
			identity.KernelRelease = sanitizeStringPointer(identity.KernelRelease)
			identity.Architecture = sanitizeStringPointer(identity.Architecture)
			identity.Source = SanitizeText(identity.Source)
			hardware.SystemIdentity = &identity
		}
		result.Hardware = &hardware
	}
	if input.Docker != nil {
		dockerStats := *input.Docker
		dockerStats.Containers = append([]DockerContainerStats(nil), input.Docker.Containers...)
		if input.Docker.Containers != nil && dockerStats.Containers == nil {
			dockerStats.Containers = make([]DockerContainerStats, 0)
		}
		for index := range dockerStats.Containers {
			container := &dockerStats.Containers[index]
			container.Names = SanitizeText(container.Names)
			container.Image = SanitizeText(container.Image)
			container.Status = SanitizeText(container.Status)
			container.Ports = SanitizeText(container.Ports)
		}
		dockerStats.UpdatedAt = sanitizeStringPointer(dockerStats.UpdatedAt)
		dockerStats.Error = sanitizeExtensionError(dockerStats.Error)
		result.Docker = &dockerStats
	}
	if input.Hermes != nil {
		hermesStats := *input.Hermes
		hermesStats.Profiles = append([]HermesProfileStats(nil), input.Hermes.Profiles...)
		if input.Hermes.Profiles != nil && hermesStats.Profiles == nil {
			hermesStats.Profiles = make([]HermesProfileStats, 0)
		}
		for index := range hermesStats.Profiles {
			profile := &hermesStats.Profiles[index]
			if ContainsSecretLikeText(profile.Profile) {
				profile.Profile = "redacted"
			}
			profile.AgentVersion = sanitizeStringPointer(profile.AgentVersion)
			profile.ServiceStatus = sanitizeStringPointer(profile.ServiceStatus)
			profile.GatewayService = sanitizeStringPointer(profile.GatewayService)
			profile.ManagerMode = sanitizeStringPointer(profile.ManagerMode)
			profile.Provider = sanitizeStringPointer(profile.Provider)
			profile.Model = sanitizeStringPointer(profile.Model)
			profile.AuthRefreshedAt = sanitizeStringPointer(profile.AuthRefreshedAt)
			profile.UpdatedAt = sanitizeStringPointer(profile.UpdatedAt)
			profile.ReceivedAt = sanitizeStringPointer(profile.ReceivedAt)
			profile.Usage.WindowStart = sanitizeStringPointer(profile.Usage.WindowStart)
			profile.Usage.WindowEnd = sanitizeStringPointer(profile.Usage.WindowEnd)
			profile.Error = sanitizeExtensionError(profile.Error)
			if profile.ConfigSummary != nil {
				config := *profile.ConfigSummary
				config.MainModel.Provider = SanitizeText(config.MainModel.Provider)
				config.MainModel.Model = SanitizeText(config.MainModel.Model)
				config.MainModel.BaseURL = SanitizeText(config.MainModel.BaseURL)
				config.Delegation.Provider = SanitizeText(config.Delegation.Provider)
				config.Delegation.Model = SanitizeText(config.Delegation.Model)
				config.Delegation.BaseURL = SanitizeText(config.Delegation.BaseURL)
				config.Delegation.ReasoningEffort = SanitizeText(config.Delegation.ReasoningEffort)
				config.AuxiliaryModels = append([]AuxiliaryModelSummary(nil), profile.ConfigSummary.AuxiliaryModels...)
				if config.AuxiliaryModels == nil {
					config.AuxiliaryModels = make([]AuxiliaryModelSummary, 0)
				}
				for auxiliaryIndex := range config.AuxiliaryModels {
					item := &config.AuxiliaryModels[auxiliaryIndex]
					item.Name = SanitizeText(item.Name)
					item.Provider = SanitizeText(item.Provider)
					item.Model = SanitizeText(item.Model)
					item.EffectiveProvider = SanitizeText(item.EffectiveProvider)
					item.EffectiveModel = SanitizeText(item.EffectiveModel)
					item.Source = SanitizeText(item.Source)
					item.BaseURLDisplay = SanitizeText(item.BaseURLDisplay)
					item.Language = SanitizeText(item.Language)
				}
				config.DockerVolumes = append([]string(nil), profile.ConfigSummary.DockerVolumes...)
				if config.DockerVolumes == nil {
					config.DockerVolumes = make([]string, 0)
				}
				for volumeIndex := range config.DockerVolumes {
					if secretPathPattern.MatchString(config.DockerVolumes[volumeIndex]) {
						config.DockerVolumes[volumeIndex] = RedactedValue
					} else {
						config.DockerVolumes[volumeIndex] = SanitizeText(config.DockerVolumes[volumeIndex])
					}
				}
				profile.ConfigSummary = &config
			}
			if profile.MixtureOfAgents != nil {
				mixture := *profile.MixtureOfAgents
				mixture.Source = SanitizeText(mixture.Source)
				mixture.Name = SanitizeText(mixture.Name)
				mixture.Label = SanitizeText(mixture.Label)
				mixture.Description = SanitizeText(mixture.Description)
				mixture.Error = sanitizeStringPointer(mixture.Error)
				mixture.Tools = append([]string(nil), profile.MixtureOfAgents.Tools...)
				if mixture.Tools == nil {
					mixture.Tools = make([]string, 0)
				}
				for toolIndex := range mixture.Tools {
					mixture.Tools[toolIndex] = SanitizeText(mixture.Tools[toolIndex])
				}
				profile.MixtureOfAgents = &mixture
			}
		}
		hermesStats.UpdatedAt = sanitizeStringPointer(hermesStats.UpdatedAt)
		hermesStats.Error = sanitizeExtensionError(hermesStats.Error)
		result.Hermes = &hermesStats
	}
	if input.Lucky != nil {
		lucky := SanitizeLuckyStats(*input.Lucky)
		result.Lucky = &lucky
	}
	if input.EasyTier != nil {
		easytier := SanitizeEasyTierStats(*input.EasyTier)
		result.EasyTier = &easytier
	}
	if input.UniFi != nil {
		unifi := SanitizeUniFiStats(*input.UniFi)
		result.UniFi = &unifi
	}
	if input.ClientBuild != nil {
		build := *input.ClientBuild
		build.Version = SanitizeText(build.Version)
		build.Revision = SanitizeText(build.Revision)
		build.BuildTime = sanitizeStringPointer(build.BuildTime)
		build.Protocol = SanitizeText(build.Protocol)
		result.ClientBuild = &build
	}
	return result
}

func sanitizeStringPointer(value *string) *string {
	if value == nil {
		return nil
	}
	sanitized := SanitizeText(*value)
	return &sanitized
}

func sanitizeExtensionError(input *ExtensionError) *ExtensionError {
	if input == nil {
		return nil
	}
	result := *input
	if !errorCodePattern.MatchString(result.Code) || ContainsSecretLikeText(result.Code) {
		result.Code = "source_error"
	}
	if !errorSourcePattern.MatchString(result.Source) || ContainsSecretLikeText(result.Source) {
		result.Source = "extension-validator"
	}
	result.Message = safeErrorMessage(result.Code)
	return &result
}

func safeErrorMessage(code string) string {
	switch code {
	case "not_reported":
		return "Extension data was not reported"
	case "not_installed":
		return "Hermes Agent is not installed"
	case "smartctl_unavailable":
		return "SMART data is unavailable"
	case "sector_size_unknown":
		return "Logical sector size is unavailable"
	case "smart_value_invalid":
		return "One or more SMART values are invalid"
	case "smart_return_status_unavailable":
		return "SMART native return status is unavailable; attribute health fallback was used"
	case "hwmon_unavailable":
		return "CPU temperature is unavailable"
	case "host_os_unavailable":
		return "Host operating system data is unavailable"
	case "cpu_model_unavailable":
		return "Host CPU model is unavailable"
	case "docker_unavailable":
		return "Docker data is unavailable"
	case "docker_response_too_large":
		return "Docker data exceeds the allowed size"
	case "api_unauthorized":
		return "Hermes API authorization failed"
	case "api_timeout":
		return "Hermes API request timed out"
	case "api_disabled":
		return "Hermes API is not configured"
	case "api_unavailable":
		return "Hermes API is unavailable"
	case "api_http_error":
		return "Hermes API request failed"
	case "api_invalid_json":
		return "Hermes API returned invalid data"
	case "cli_unavailable":
		return "Hermes CLI status is unavailable"
	case "snapshot_unavailable":
		return "Hermes integration snapshot is unavailable"
	case "snapshot_invalid":
		return "Hermes integration snapshot is invalid"
	case "profile_unavailable":
		return "Hermes profile is unavailable"
	case "partial_failure":
		return "One or more extension sources are unavailable"
	case "easytier_cli_unavailable":
		return "EasyTier CLI is unavailable"
	case "rpc_unavailable":
		return "EasyTier loopback RPC is unavailable"
	case "command_failed":
		return "EasyTier command is unavailable"
	case "invalid_configuration":
		return "EasyTier monitoring configuration is invalid"
	case "clock_skew":
		return "Extension timestamp is too far in the future"
	default:
		return "Extension data is unavailable"
	}
}

func validateRequiredExtensionFields(data []byte, snapshot bool) error {
	root, err := requiredObject(data, "extension")
	if err != nil {
		return err
	}
	required := []string{"extension_version", "hardware", "docker", "hermes"}
	if snapshot {
		required = append(required, "received_at")
	}
	if err := requireFields(root, "extension", required...); err != nil {
		return err
	}
	if err := validateRequiredHardware(root["hardware"]); err != nil {
		return err
	}
	if err := validateRequiredDocker(root["docker"]); err != nil {
		return err
	}
	if err := validateRequiredHermes(root["hermes"]); err != nil {
		return err
	}
	if raw, ok := root["lucky"]; ok {
		if err := validateRequiredLucky(raw); err != nil {
			return err
		}
	}
	if raw, ok := root["easytier"]; ok {
		if err := validateRequiredEasyTier(raw); err != nil {
			return err
		}
	}
	if raw, ok := root["unifi"]; ok {
		if err := validateRequiredUniFi(raw); err != nil {
			return err
		}
	}
	if raw, ok := root["client_build"]; ok {
		if err := validateRequiredClientBuild(raw); err != nil {
			return err
		}
	}
	return nil
}

func validateRequiredHardware(raw json.RawMessage) error {
	object, err := requiredObject(raw, "hardware")
	if err != nil {
		return err
	}
	if err := requireFields(object, "hardware", "cpu_model", "cpu_temperature", "disk_temperature", "disk_smart_status", "disk_power_on_hours", "disk_written_bytes", "disk_read_bytes", "disk_device", "disk_smart_source", "updated_at", "stale", "error"); err != nil {
		return err
	}
	if err := validateNullableObjectFields(object["cpu_temperature"], "hardware.cpu_temperature", "value", "unit", "source"); err != nil {
		return err
	}
	if err := validateNullableObjectFields(object["disk_temperature"], "hardware.disk_temperature", "current", "highest", "lowest", "unit", "source"); err != nil {
		return err
	}
	if raw, ok := object["cpu_details"]; ok {
		// instruction_sets was added after the initial Device v2 CPU-details
		// contract. Keep it optional so an older compatible client does not
		// lose the entire hardware domain during a rolling server upgrade.
		if err := validateNullableObjectFields(raw, "hardware.cpu_details", "architecture", "vendor", "family", "model_id", "model_name", "stepping", "virtualization", "l1d_cache", "l1i_cache", "l2_cache", "l3_cache", "logical_cpus", "sockets", "cores_per_socket", "threads_per_core", "max_mhz", "min_mhz", "current_mhz", "usage"); err != nil {
			return err
		}
		if !bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			cpuDetails, detailErr := requiredObject(raw, "hardware.cpu_details")
			if detailErr != nil {
				return detailErr
			}
			if detailErr = validateNullableObjectFields(cpuDetails["usage"], "hardware.cpu_details.usage", "user_percent", "nice_percent", "system_percent", "idle_percent", "iowait_percent", "irq_percent", "softirq_percent", "steal_percent", "total_percent"); detailErr != nil {
				return detailErr
			}
		}
	}
	if raw, ok := object["memory_details"]; ok {
		if err := validateNullableObjectFields(raw, "hardware.memory_details", "total_bytes", "used_bytes", "available_bytes", "free_bytes", "buffers_bytes", "cached_bytes", "reclaimable_bytes", "active_bytes", "inactive_bytes", "dirty_bytes", "writeback_bytes", "slab_bytes", "swap_total_bytes", "swap_used_bytes", "swap_free_bytes", "swap_cached_bytes"); err != nil {
			return err
		}
	}
	if raw, ok := object["storage"]; ok {
		if err := validateRequiredStorage(raw); err != nil {
			return err
		}
	}
	if raw, ok := object["system_identity"]; ok {
		if err := validateRequiredSystemIdentity(raw); err != nil {
			return err
		}
	}
	return validateNullableObjectFields(object["error"], "hardware.error", "code", "message", "source", "retryable", "http_status")
}

func validateRequiredStorage(raw json.RawMessage) error {
	object, err := requiredObject(raw, "hardware.storage")
	if err != nil {
		return err
	}
	if err := requireFields(object, "hardware.storage", "physical_disks", "filesystems", "summary", "updated_at", "stale", "error"); err != nil {
		return err
	}
	var physicalDisks []json.RawMessage
	if err := json.Unmarshal(object["physical_disks"], &physicalDisks); err != nil || physicalDisks == nil {
		return validationError(validationCodeInvalidJSON, "hardware.storage.physical_disks", "field must be an array")
	}
	for index, rawDisk := range physicalDisks {
		field := fmt.Sprintf("hardware.storage.physical_disks[%d]", index)
		disk, diskErr := requiredObject(rawDisk, field)
		if diskErr != nil {
			return diskErr
		}
		if diskErr = requireFields(disk, field, "id", "device", "model", "capacity_bytes", "temperature_c", "smart_status", "power_on_hours", "written_bytes", "read_bytes", "smart_source", "collection_status"); diskErr != nil {
			return diskErr
		}
		if rawError, exists := disk["error"]; exists {
			if diskErr = validateNullableObjectFields(rawError, field+".error", "code", "message", "source", "retryable", "http_status"); diskErr != nil {
				return diskErr
			}
		}
	}
	var filesystems []json.RawMessage
	if err := json.Unmarshal(object["filesystems"], &filesystems); err != nil || filesystems == nil {
		return validationError(validationCodeInvalidJSON, "hardware.storage.filesystems", "field must be an array")
	}
	for index, rawFilesystem := range filesystems {
		field := fmt.Sprintf("hardware.storage.filesystems[%d]", index)
		filesystem, filesystemErr := requiredObject(rawFilesystem, field)
		if filesystemErr != nil {
			return filesystemErr
		}
		if filesystemErr = requireFields(filesystem, field, "source", "mountpoint", "fs_type", "total_bytes", "used_bytes", "available_bytes", "usage_percent", "backing_disk_ids", "stack_type", "collection_status"); filesystemErr != nil {
			return filesystemErr
		}
		if rawError, exists := filesystem["error"]; exists {
			if filesystemErr = validateNullableObjectFields(rawError, field+".error", "code", "message", "source", "retryable", "http_status"); filesystemErr != nil {
				return filesystemErr
			}
		}
	}
	summary, err := requiredObject(object["summary"], "hardware.storage.summary")
	if err != nil {
		return err
	}
	if err := requireFields(summary, "hardware.storage.summary", "physical_disk_count", "smart_passed", "smart_failed", "smart_unknown", "temperature_min_c", "temperature_max_c", "filesystem_count"); err != nil {
		return err
	}
	return validateNullableObjectFields(object["error"], "hardware.storage.error", "code", "message", "source", "retryable", "http_status")
}

func validateRequiredSystemIdentity(raw json.RawMessage) error {
	object, err := requiredObject(raw, "hardware.system_identity")
	if err != nil {
		return err
	}
	return requireFields(object, "hardware.system_identity", "distribution", "release_version", "pretty_name", "kernel_release", "architecture", "source")
}

func validateRequiredClientBuild(raw json.RawMessage) error {
	object, err := requiredObject(raw, "client_build")
	if err != nil {
		return err
	}
	return requireFields(object, "client_build", "version", "revision", "build_time", "protocol")
}

func validateRequiredDocker(raw json.RawMessage) error {
	object, err := requiredObject(raw, "docker")
	if err != nil {
		return err
	}
	if err := requireFields(object, "docker", "running", "total", "limit", "truncated", "containers", "updated_at", "stale", "error"); err != nil {
		return err
	}
	var containers []json.RawMessage
	if err := json.Unmarshal(object["containers"], &containers); err != nil || containers == nil {
		return validationError(validationCodeInvalidJSON, "docker.containers", "field must be an array")
	}
	for index, rawContainer := range containers {
		field := fmt.Sprintf("docker.containers[%d]", index)
		container, err := requiredObject(rawContainer, field)
		if err != nil {
			return err
		}
		if err := requireFields(container, field, "names", "image", "status", "ports"); err != nil {
			return err
		}
	}
	return validateNullableObjectFields(object["error"], "docker.error", "code", "message", "source", "retryable", "http_status")
}

func validateRequiredHermes(raw json.RawMessage) error {
	object, err := requiredObject(raw, "hermes")
	if err != nil {
		return err
	}
	if err := requireFields(object, "hermes", "profiles", "updated_at", "stale", "error"); err != nil {
		return err
	}
	var profiles []json.RawMessage
	if err := json.Unmarshal(object["profiles"], &profiles); err != nil || profiles == nil {
		return validationError(validationCodeInvalidJSON, "hermes.profiles", "field must be an array")
	}
	for index, rawProfile := range profiles {
		field := fmt.Sprintf("hermes.profiles[%d]", index)
		profile, err := requiredObject(rawProfile, field)
		if err != nil {
			return err
		}
		if err := requireFields(profile, field, "profile", "agent_version", "api_status", "service_status", "gateway_service", "manager_mode", "usage_mode", "provider", "model", "auth_refreshed_at", "scheduled_jobs_active", "scheduled_jobs_total", "sessions_active", "sessions_total", "usage", "config_summary", "updated_at", "stale", "error"); err != nil {
			return err
		}
		usage, err := requiredObject(profile["usage"], field+".usage")
		if err != nil {
			return err
		}
		if err := requireFields(usage, field+".usage", "input_tokens", "output_tokens", "total_tokens", "estimated", "source", "window_start", "window_end"); err != nil {
			return err
		}
		if err := validateNullableObjectFields(profile["config_summary"], field+".config_summary", "docker_volumes"); err != nil {
			return err
		}
		if err := validateNullableObjectFields(profile["error"], field+".error", "code", "message", "source", "retryable", "http_status"); err != nil {
			return err
		}
	}
	return validateNullableObjectFields(object["error"], "hermes.error", "code", "message", "source", "retryable", "http_status")
}

func requiredObject(raw []byte, field string) (map[string]json.RawMessage, error) {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(raw, &object); err != nil || object == nil {
		return nil, validationError(validationCodeInvalidJSON, field, "field must be an object")
	}
	return object, nil
}

func requireFields(object map[string]json.RawMessage, field string, names ...string) error {
	for _, name := range names {
		if _, ok := object[name]; !ok {
			return validationError(validationCodeMissingField, field+"."+name, "required field is missing")
		}
	}
	return nil
}

func validateNullableObjectFields(raw json.RawMessage, field string, names ...string) error {
	if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		return nil
	}
	object, err := requiredObject(raw, field)
	if err != nil {
		return err
	}
	return requireFields(object, field, names...)
}

func validateRequiredString(field, value string, maxLength int) error {
	length := utf8.RuneCountInString(value)
	if length == 0 {
		return validationError(validationCodeInvalidValue, field, "value must not be empty")
	}
	if length > maxLength {
		return validationError(validationCodeInvalidValue, field, "value exceeds the allowed length")
	}
	if controlCharacterPattern.MatchString(value) {
		return validationError(validationCodeInvalidValue, field, "value contains control characters")
	}
	if ContainsSecretLikeText(value) {
		return validationError(validationCodeInvalidValue, field, "value contains disallowed content")
	}
	return nil
}

func validateOptionalString(field string, value *string, maxLength int) error {
	if value == nil {
		return nil
	}
	if utf8.RuneCountInString(*value) > maxLength {
		return validationError(validationCodeInvalidValue, field, "value exceeds the allowed length")
	}
	if controlCharacterPattern.MatchString(*value) {
		return validationError(validationCodeInvalidValue, field, "value contains control characters")
	}
	if ContainsSecretLikeText(*value) {
		return validationError(validationCodeInvalidValue, field, "value contains disallowed content")
	}
	return nil
}

func validateOptionalEnum(field string, value *string, allowed ...string) error {
	if value == nil {
		return nil
	}
	for _, candidate := range allowed {
		if *value == candidate {
			return nil
		}
	}
	return validationError(validationCodeInvalidValue, field, "value is not supported")
}

func validateStringValue(field, value string, maxLength int) error {
	if utf8.RuneCountInString(value) > maxLength {
		return validationError(validationCodeInvalidValue, field, "value exceeds the allowed length")
	}
	if controlCharacterPattern.MatchString(value) {
		return validationError(validationCodeInvalidValue, field, "value contains control characters")
	}
	if ContainsSecretLikeText(value) {
		return validationError(validationCodeInvalidValue, field, "value contains disallowed content")
	}
	return nil
}

func validateDuration(field string, value *float64) error {
	if value == nil {
		return nil
	}
	if math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > 86400 {
		return validationError(validationCodeInvalidValue, field, "duration is outside the allowed range")
	}
	return nil
}

func validateCounter(field string, value *int64, max int64) error {
	if value != nil && (*value < 0 || *value > max) {
		return validationError(validationCodeInvalidValue, field, "value is outside the allowed range")
	}
	return nil
}

func validateTemperature(field string, value float64) error {
	if math.IsNaN(value) || math.IsInf(value, 0) || value < MinTemperatureCelsius || value > MaxTemperatureCelsius {
		return validationError(validationCodeInvalidValue, field, "temperature is outside the allowed range")
	}
	return nil
}

func validateDateTime(field string, value *string, nullable bool) error {
	if value == nil {
		if nullable {
			return nil
		}
		return validationError(validationCodeInvalidValue, field, "timestamp is required")
	}
	if utf8.RuneCountInString(*value) > MaxTimestampLength {
		return validationError(validationCodeInvalidValue, field, "timestamp exceeds the allowed length")
	}
	if _, err := time.Parse(time.RFC3339, *value); err != nil {
		return validationError(validationCodeInvalidValue, field, "timestamp must use RFC3339")
	}
	return nil
}

func validateUpdatedAt(field string, value *string, stale bool) error {
	if value == nil && !stale {
		return validationError(validationCodeInvalidValue, field+".stale", "data without updated_at must be stale")
	}
	return validateDateTime(field+".updated_at", value, true)
}

func validatePayloadSize(field string, value any, limit int) error {
	data, err := json.Marshal(value)
	if err != nil {
		return validationError(validationCodeInvalidValue, field, "object cannot be encoded")
	}
	if len(data) > limit {
		return validationError(validationCodePayloadTooLarge, field, "object exceeds the allowed size")
	}
	return nil
}

func validDiskSMARTStatus(value DiskSMARTStatus) bool {
	return value == DiskSMARTPassed || value == DiskSMARTFailed || value == DiskSMARTUnknown
}

func validHermesAPIStatus(value HermesAPIStatus) bool {
	switch value {
	case HermesAPIOK, HermesAPIHealthy, HermesAPIUnauthorized, HermesAPITimeout, HermesAPIUnavailable, HermesAPIError, HermesAPIUnknown:
		return true
	default:
		return false
	}
}

func validHermesUsageMode(value HermesUsageMode) bool {
	return value == HermesUsageAPI || value == HermesUsageAuthProvider || value == HermesUsageUnknown
}

func validTokenSource(value TokenUsageSource) bool {
	switch value {
	case TokenSourceHermesAPI, TokenSourceLocalSessionState, TokenSourceLocalLogs, TokenSourceUnavailable:
		return true
	default:
		return false
	}
}
