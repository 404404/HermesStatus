package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

const (
	hardwareStaleAfter     = 900 * time.Second
	dockerStaleAfter       = 120 * time.Second
	hermesStaleAfter       = 900 * time.Second
	luckyStaleAfter        = 900 * time.Second
	luckyVersionStaleAfter = 24 * time.Hour
	profileStaleAfter      = 900 * time.Second
	maxFutureClockSkew     = 300 * time.Second
)

type extensionDecodeIssue struct {
	Domain        string
	Code          string
	PayloadLength int
}

func decodeAgentUpdate(data []byte) (AgentStats, ExtensionStats, []extensionDecodeIssue, error) {
	var native AgentStats
	if len(data) > maxRequestBody {
		return native, ExtensionStats{}, nil, fmt.Errorf("update payload exceeds the allowed size")
	}
	if err := json.Unmarshal(data, &native); err != nil {
		return native, ExtensionStats{}, nil, fmt.Errorf("update payload is not valid JSON")
	}

	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil || fields == nil {
		return native, ExtensionStats{}, nil, fmt.Errorf("update payload must be a JSON object")
	}

	extension := newNotReportedExtensionStats()
	issues := make([]extensionDecodeIssue, 0, 3)
	hasStructured := hasAnyField(fields, "hardware", "docker", "hermes", "lucky")
	versionCode := ""
	if raw, ok := fields["extension_version"]; ok {
		var version string
		if err := json.Unmarshal(raw, &version); err != nil || version != ExtensionSchemaVersion || len(version) > MaxExtensionVersionLength {
			versionCode = validationCodeInvalidValue
			issues = append(issues, extensionDecodeIssue{Domain: "extension", Code: versionCode, PayloadLength: len(raw)})
		}
	} else if hasStructured {
		versionCode = validationCodeMissingField
		issues = append(issues, extensionDecodeIssue{Domain: "extension", Code: versionCode, PayloadLength: len(data)})
	}

	extension.Hardware = decodeWireDomain(
		fields, "hardware", "hardware_json", versionCode,
		MaxHardwarePayloadBytes, MaxLegacyHardwareJSONBytes,
		DecodeHardwareStatsJSON, pointerTo(NewNotReportedHardwareStats()), newDegradedHardwareStats, &issues,
	)
	extension.Docker = decodeWireDomain(
		fields, "docker", "docker_json", versionCode,
		MaxDockerPayloadBytes, MaxLegacyDockerJSONBytes,
		DecodeDockerStatsJSON, pointerTo(NewNotReportedDockerStats()), newDegradedDockerStats, &issues,
	)
	extension.Hermes = decodeWireDomain(
		fields, "hermes", "hermes_json", versionCode,
		MaxHermesPayloadBytes, MaxLegacyHermesJSONBytes,
		DecodeHermesStatsJSON, pointerTo(NewNotReportedHermesStats()), newDegradedHermesStats, &issues,
	)
	if raw, ok := fields["lucky"]; ok {
		if versionCode != "" {
			issues = append(issues, extensionDecodeIssue{Domain: "lucky", Code: versionCode, PayloadLength: len(raw)})
			extension.Lucky = newDegradedLuckyStats(versionCode)
		} else {
			extension.Lucky = decodeDomainPayload("lucky", raw, MaxLuckyPayloadBytes, DecodeLuckyStatsJSON, newDegradedLuckyStats, &issues)
		}
	}
	return native, extension, issues, nil
}

func decodeWireDomain[T any](
	fields map[string]json.RawMessage,
	domain string,
	legacyField string,
	structuredVersionCode string,
	structuredLimit int,
	legacyLimit int,
	decode func([]byte) (*T, error),
	notReported *T,
	degraded func(string) *T,
	issues *[]extensionDecodeIssue,
) *T {
	if raw, ok := fields[domain]; ok {
		if structuredVersionCode != "" {
			*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: structuredVersionCode, PayloadLength: len(raw)})
			return degraded(structuredVersionCode)
		}
		return decodeDomainPayload(domain, raw, structuredLimit, decode, degraded, issues)
	}

	raw, ok := fields[legacyField]
	if !ok {
		return notReported
	}
	var legacy string
	if err := json.Unmarshal(raw, &legacy); err != nil {
		code := validationCodeInvalidJSON
		*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: code, PayloadLength: len(raw)})
		return degraded(code)
	}
	if len(legacy) > legacyLimit {
		code := validationCodePayloadTooLarge
		*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: code, PayloadLength: len(legacy)})
		return degraded(code)
	}
	legacyData := bytes.TrimSpace([]byte(legacy))
	if len(legacyData) == 0 || legacyData[0] != '{' {
		code := validationCodeInvalidJSON
		*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: code, PayloadLength: len(legacy)})
		return degraded(code)
	}
	return decodeDomainPayload(domain, legacyData, legacyLimit, decode, degraded, issues)
}

func decodeDomainPayload[T any](
	domain string,
	data []byte,
	limit int,
	decode func([]byte) (*T, error),
	degraded func(string) *T,
	issues *[]extensionDecodeIssue,
) *T {
	if len(data) > limit {
		code := validationCodePayloadTooLarge
		*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: code, PayloadLength: len(data)})
		return degraded(code)
	}
	value, err := decode(data)
	if err == nil {
		return value
	}
	code := extensionValidationCode(err)
	*issues = append(*issues, extensionDecodeIssue{Domain: domain, Code: code, PayloadLength: len(data)})
	return degraded(code)
}

func extensionValidationCode(err error) string {
	var validationErr *ExtensionValidationError
	if errors.As(err, &validationErr) {
		return validationErr.Code
	}
	return validationCodeInvalidValue
}

func hasAnyField(fields map[string]json.RawMessage, names ...string) bool {
	for _, name := range names {
		if _, ok := fields[name]; ok {
			return true
		}
	}
	return false
}

func pointerTo[T any](value T) *T {
	return &value
}

func newNotReportedExtensionStats() ExtensionStats {
	hardware := NewNotReportedHardwareStats()
	dockerStats := NewNotReportedDockerStats()
	hermesStats := NewNotReportedHermesStats()
	luckyStats := NewNotReportedLuckyStats()
	return ExtensionStats{
		ExtensionVersion: ExtensionSchemaVersion,
		Hardware:         &hardware,
		Docker:           &dockerStats,
		Hermes:           &hermesStats,
		Lucky:            &luckyStats,
	}
}

func newDegradedHardwareStats(code string) *HardwareStats {
	stats := NewNotReportedHardwareStats()
	stats.Error = newPipelineError("hardware", code)
	return &stats
}

func newDegradedDockerStats(code string) *DockerStats {
	stats := NewNotReportedDockerStats()
	stats.Error = newPipelineError("docker", code)
	return &stats
}

func newDegradedHermesStats(code string) *HermesStats {
	stats := NewNotReportedHermesStats()
	stats.Error = newPipelineError("hermes", code)
	return &stats
}

func newDegradedLuckyStats(code string) *LuckyStats {
	stats := newEmptyLuckyStats(LuckyStatusError, LuckySourceUnavailable, newPipelineError("lucky", code))
	return &stats
}

func newPipelineError(source, code string) *ExtensionError {
	return &ExtensionError{
		Code:      code,
		Message:   safeErrorMessage(code),
		Source:    source,
		Retryable: false,
	}
}

func newNotReportedExtensionSnapshot(receivedAt time.Time) ExtensionSnapshot {
	return extensionSnapshotAt(newNotReportedExtensionStats(), receivedAt)
}

func extensionSnapshotAt(stats ExtensionStats, receivedAt time.Time) ExtensionSnapshot {
	return ExtensionSnapshot{
		ExtensionVersion: ExtensionSchemaVersion,
		ReceivedAt:       receivedAt.UTC().Format(time.RFC3339Nano),
		Hardware:         stats.Hardware,
		Docker:           stats.Docker,
		Hermes:           stats.Hermes,
		Lucky:            stats.Lucky,
	}
}

func snapshotExtension(input ExtensionSnapshot, now time.Time) ExtensionSnapshot {
	stats := SanitizeExtensionStats(ExtensionStats{
		ExtensionVersion: input.ExtensionVersion,
		Hardware:         input.Hardware,
		Docker:           input.Docker,
		Hermes:           input.Hermes,
		Lucky:            input.Lucky,
	})
	if stats.ExtensionVersion != ExtensionSchemaVersion {
		stats.ExtensionVersion = ExtensionSchemaVersion
	}
	if stats.Hardware == nil {
		stats.Hardware = pointerTo(NewNotReportedHardwareStats())
	}
	if stats.Docker == nil {
		stats.Docker = pointerTo(NewNotReportedDockerStats())
	}
	if stats.Hermes == nil {
		stats.Hermes = pointerTo(NewNotReportedHermesStats())
	}
	if stats.Lucky == nil {
		stats.Lucky = pointerTo(NewNotReportedLuckyStats())
	}
	receivedAt := input.ReceivedAt
	if _, err := time.Parse(time.RFC3339, receivedAt); err != nil {
		receivedAt = now.UTC().Format(time.RFC3339Nano)
	}

	applyDomainFreshness("hardware", stats.Hardware.UpdatedAt, hardwareStaleAfter, now, &stats.Hardware.Stale, &stats.Hardware.Error)
	applyDomainFreshness("docker", stats.Docker.UpdatedAt, dockerStaleAfter, now, &stats.Docker.Stale, &stats.Docker.Error)
	applyDomainFreshness("hermes", stats.Hermes.UpdatedAt, hermesStaleAfter, now, &stats.Hermes.Stale, &stats.Hermes.Error)
	applyDomainFreshness("lucky", stats.Lucky.UpdatedAt, luckyStaleAfter, now, &stats.Lucky.Stale, &stats.Lucky.Error)
	applyLuckyModuleFreshness("lucky.ip_resolution", stats.Lucky.IPResolution.UpdatedAt, now, &stats.Lucky.IPResolution.Stale, &stats.Lucky.IPResolution.Error)
	applyLuckyModuleFreshness("lucky.dynamic_dns", stats.Lucky.DynamicDNS.UpdatedAt, now, &stats.Lucky.DynamicDNS.Stale, &stats.Lucky.DynamicDNS.Error)
	applyLuckyModuleFreshness("lucky.web_services", stats.Lucky.WebServices.UpdatedAt, now, &stats.Lucky.WebServices.Stale, &stats.Lucky.WebServices.Error)
	applyLuckyModuleFreshness("lucky.port_forwards", stats.Lucky.PortForwards.UpdatedAt, now, &stats.Lucky.PortForwards.Stale, &stats.Lucky.PortForwards.Error)
	applyLuckyModuleFreshness("lucky.certificates", stats.Lucky.Certificates.UpdatedAt, now, &stats.Lucky.Certificates.Stale, &stats.Lucky.Certificates.Error)
	applyDomainFreshness("lucky.version", stats.Lucky.Version.CheckedAt, luckyVersionStaleAfter, now, &stats.Lucky.Version.Stale, &stats.Lucky.Version.Error)
	for index := range stats.Hermes.Profiles {
		profile := &stats.Hermes.Profiles[index]
		applyDomainFreshness("hermes", profile.UpdatedAt, profileStaleAfter, now, &profile.Stale, &profile.Error)
	}

	return ExtensionSnapshot{
		ExtensionVersion: stats.ExtensionVersion,
		ReceivedAt:       receivedAt,
		Hardware:         stats.Hardware,
		Docker:           stats.Docker,
		Hermes:           stats.Hermes,
		Lucky:            stats.Lucky,
	}
}

func applyLuckyModuleFreshness(source string, updatedAt *string, now time.Time, stale *bool, extensionError **ExtensionError) {
	applyDomainFreshness(source, updatedAt, luckyStaleAfter, now, stale, extensionError)
}

func applyDomainFreshness(source string, updatedAt *string, threshold time.Duration, now time.Time, stale *bool, extensionError **ExtensionError) {
	*stale = true
	if updatedAt == nil {
		return
	}
	collectedAt, err := time.Parse(time.RFC3339, *updatedAt)
	if err != nil {
		*extensionError = newPipelineError(source, validationCodeInvalidValue)
		return
	}
	if collectedAt.Sub(now) > maxFutureClockSkew {
		*extensionError = newPipelineError(source, "clock_skew")
		return
	}
	*stale = now.Sub(collectedAt) > threshold
}
