// Package contracts contains Stage A multi-device contracts and pure helpers.
//
// It is deliberately not imported by the production server. Runtime wiring is
// reserved for later stages.
package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	MaxDevices          = 128
	MaxEnvelopeBytes    = 1 << 20
	MaxDisplayNameRunes = 128
	MaxFQDNBytes        = 253
)

var (
	deviceIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,62}$`)
	labelPattern    = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]*$`)
	digestPattern   = regexp.MustCompile(`^[0-9a-f]{64}$`)
	safeTextPattern = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)
	credentialIDSet = map[string]bool{"current": true, "next": true}
	statsKeys       = map[string]bool{
		"uptime": true, "load_1": true, "load_5": true, "load_15": true,
		"ping_10010": true, "ping_189": true, "ping_10086": true,
		"time_10010": true, "time_189": true, "time_10086": true,
		"tcp": true, "udp": true, "process": true, "thread": true,
		"network_rx": true, "network_tx": true, "network_in": true, "network_out": true,
		"memory_total": true, "memory_used": true, "swap_total": true, "swap_used": true,
		"hdd_total": true, "hdd_used": true, "io_read": true, "io_write": true,
		"cpu": true, "cpu_cores": true, "cpu_model": true, "custom": true, "os": true,
		"online4": true, "online6": true,
		"extension_version": true, "hardware": true, "docker": true, "hermes": true, "lucky": true,
		"hardware_json": true, "docker_json": true, "hermes_json": true,
	}
)

type ContractError struct {
	Field   string
	Message string
}

func (e *ContractError) Error() string {
	return e.Field + ": " + e.Message
}

func contractError(field, message string) error {
	return &ContractError{Field: field, Message: message}
}

type IngestionOwnership struct {
	Mode            string  `json:"mode"`
	ActiveProtocol  *string `json:"active_protocol"`
	CutoverNotAfter *string `json:"cutover_not_after"`
}

type RegistryDefaults struct {
	DefaultDeviceID string `json:"default_device_id"`
	StaleSeconds    int    `json:"stale_seconds"`
	OfflineSeconds  int    `json:"offline_seconds"`
}

type RegistryDevice struct {
	ID           string             `json:"id"`
	DisplayName  string             `json:"display_name"`
	ExpectedFQDN *string            `json:"expected_fqdn"`
	Enabled      *bool              `json:"enabled"`
	Order        int                `json:"order"`
	Tags         []string           `json:"tags"`
	Group        *string            `json:"group"`
	Ingestion    IngestionOwnership `json:"ingestion"`
}

type DeviceRegistry struct {
	Version  int              `json:"version"`
	Defaults RegistryDefaults `json:"defaults"`
	Devices  []RegistryDevice `json:"devices"`
}

type Credential struct {
	ID        string `json:"id"`
	Digest    string `json:"digest"`
	NotBefore string `json:"not_before"`
	NotAfter  string `json:"not_after"`
}

type CredentialRecord struct {
	Version     int          `json:"version"`
	DeviceID    string       `json:"device_id"`
	Algorithm   string       `json:"algorithm"`
	Credentials []Credential `json:"credentials"`
}

type LegacyDeviceMapping struct {
	Username string `json:"username"`
	DeviceID string `json:"device_id"`
}

type LegacyMappingDocument struct {
	Version  int                   `json:"version"`
	Mappings []LegacyDeviceMapping `json:"mappings"`
}

type EnvelopeDevice struct {
	ID           string  `json:"id"`
	ReportedName *string `json:"reported_name,omitempty"`
	ReportedFQDN *string `json:"reported_fqdn,omitempty"`
	Hostname     *string `json:"hostname,omitempty"`
}

type DeviceUpdateEnvelope struct {
	SchemaVersion int                        `json:"schema_version"`
	Device        EnvelopeDevice             `json:"device"`
	CollectedAt   string                     `json:"collected_at"`
	Stats         map[string]json.RawMessage `json:"stats"`
}

type SuccessResponse struct {
	Accepted         bool               `json:"accepted"`
	ServerTime       string             `json:"server_time"`
	ConfigGeneration string             `json:"config_generation"`
	Monitors         []SanitizedMonitor `json:"monitors"`
}

type SanitizedMonitor struct {
	Name     string `json:"name"`
	Host     string `json:"host"`
	Interval int    `json:"interval"`
	Type     string `json:"type"`
}

type ErrorResponse struct {
	Error PublicError `json:"error"`
}

type PublicError struct {
	Code      string `json:"code"`
	RequestID string `json:"request_id"`
}

func DecodeRegistry(data []byte, now time.Time) (*DeviceRegistry, error) {
	if err := validateRegistryRequiredFields(data); err != nil {
		return nil, err
	}
	var registry DeviceRegistry
	if err := decodeStrict(data, &registry); err != nil {
		return nil, err
	}
	if err := ValidateRegistry(&registry, now); err != nil {
		return nil, err
	}
	NormalizeRegistry(&registry)
	return &registry, nil
}

func validateRegistryRequiredFields(data []byte) error {
	var raw struct {
		Defaults map[string]json.RawMessage   `json:"defaults"`
		Devices  []map[string]json.RawMessage `json:"devices"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return contractError("json", "invalid")
	}
	if !hasAllKeys(raw.Defaults, "default_device_id", "stale_seconds", "offline_seconds") {
		return contractError("defaults", "is missing required fields")
	}
	for index, device := range raw.Devices {
		if !hasAllKeys(
			device,
			"id",
			"display_name",
			"expected_fqdn",
			"enabled",
			"order",
			"tags",
			"group",
			"ingestion",
		) {
			return contractError(fmt.Sprintf("devices[%d]", index), "is missing required fields")
		}
		var ingestion map[string]json.RawMessage
		if err := json.Unmarshal(device["ingestion"], &ingestion); err != nil ||
			!hasAllKeys(ingestion, "mode", "active_protocol", "cutover_not_after") {
			return contractError(fmt.Sprintf("devices[%d].ingestion", index), "is missing required fields")
		}
	}
	return nil
}

func hasAllKeys(value map[string]json.RawMessage, keys ...string) bool {
	for _, key := range keys {
		if _, exists := value[key]; !exists {
			return false
		}
	}
	return true
}

func DecodeCredentialRecord(data []byte) (*CredentialRecord, error) {
	var record CredentialRecord
	if err := decodeStrict(data, &record); err != nil {
		return nil, err
	}
	if err := ValidateCredentialRecord(&record); err != nil {
		return nil, err
	}
	return &record, nil
}

func DecodeLegacyMappings(data []byte, registry *DeviceRegistry, now time.Time) (*LegacyMappingDocument, error) {
	var mappings LegacyMappingDocument
	if err := decodeStrict(data, &mappings); err != nil {
		return nil, err
	}
	if err := ValidateLegacyMappings(&mappings, registry, now); err != nil {
		return nil, err
	}
	return &mappings, nil
}

func DecodeDeviceUpdateEnvelope(data []byte) (*DeviceUpdateEnvelope, error) {
	if len(data) > MaxEnvelopeBytes {
		return nil, contractError("body", "exceeds 1 MiB")
	}
	var envelope DeviceUpdateEnvelope
	if err := decodeStrict(data, &envelope); err != nil {
		return nil, err
	}
	if err := ValidateDeviceUpdateEnvelope(&envelope); err != nil {
		return nil, err
	}
	return &envelope, nil
}

func decodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return contractError("json", "invalid or contains unknown fields")
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return contractError("json", "contains more than one value")
	}
	return nil
}

func ValidateRegistry(registry *DeviceRegistry, now time.Time) error {
	if registry == nil {
		return contractError("registry", "is required")
	}
	if registry.Version != 1 {
		return contractError("version", "must equal 1")
	}
	if len(registry.Devices) < 1 || len(registry.Devices) > MaxDevices {
		return contractError("devices", "must contain 1..128 entries")
	}
	if !ValidateDeviceID(registry.Defaults.DefaultDeviceID) {
		return contractError("defaults.default_device_id", "is invalid")
	}
	if registry.Defaults.StaleSeconds < 30 || registry.Defaults.StaleSeconds > 86400 {
		return contractError("defaults.stale_seconds", "must be in 30..86400")
	}
	if registry.Defaults.OfflineSeconds <= registry.Defaults.StaleSeconds ||
		registry.Defaults.OfflineSeconds > 604800 {
		return contractError("defaults.offline_seconds", "must exceed stale_seconds and be <= 604800")
	}

	seen := make(map[string]bool, len(registry.Devices))
	var defaultFound, defaultEnabled bool
	for index := range registry.Devices {
		device := &registry.Devices[index]
		prefix := fmt.Sprintf("devices[%d]", index)
		if !ValidateDeviceID(device.ID) {
			return contractError(prefix+".id", "is invalid")
		}
		if seen[device.ID] {
			return contractError(prefix+".id", "is duplicated")
		}
		seen[device.ID] = true
		if device.Enabled == nil {
			return contractError(prefix+".enabled", "must be explicit")
		}
		device.DisplayName = strings.TrimSpace(device.DisplayName)
		if !validHumanText(device.DisplayName, MaxDisplayNameRunes) {
			return contractError(prefix+".display_name", "must be non-empty, bounded, and contain no controls")
		}
		if device.ExpectedFQDN != nil {
			normalized, err := NormalizeFQDN(*device.ExpectedFQDN)
			if err != nil {
				return contractError(prefix+".expected_fqdn", err.Error())
			}
			device.ExpectedFQDN = &normalized
		}
		if device.Order < 0 || device.Order > 1000000 {
			return contractError(prefix+".order", "must be in 0..1000000")
		}
		if len(device.Tags) > 16 {
			return contractError(prefix+".tags", "must contain no more than 16 entries")
		}
		tagSeen := map[string]bool{}
		for tagIndex, tag := range device.Tags {
			if len(tag) > 32 || !labelPattern.MatchString(tag) {
				return contractError(fmt.Sprintf("%s.tags[%d]", prefix, tagIndex), "is invalid")
			}
			if tagSeen[tag] {
				return contractError(prefix+".tags", "contains a duplicate")
			}
			tagSeen[tag] = true
		}
		if device.Group != nil && (len(*device.Group) > 64 || !labelPattern.MatchString(*device.Group)) {
			return contractError(prefix+".group", "is invalid")
		}
		if err := ValidateIngestionOwnership(device.Ingestion, now); err != nil {
			return contractError(prefix+".ingestion", err.Error())
		}
		if device.ID == registry.Defaults.DefaultDeviceID {
			defaultFound = true
			defaultEnabled = *device.Enabled
		}
	}
	if !defaultFound {
		return contractError("defaults.default_device_id", "does not exist")
	}
	if !defaultEnabled {
		return contractError("defaults.default_device_id", "must identify an enabled device")
	}
	return nil
}

func NormalizeRegistry(registry *DeviceRegistry) {
	sort.SliceStable(registry.Devices, func(i, j int) bool {
		if registry.Devices[i].Order == registry.Devices[j].Order {
			return registry.Devices[i].ID < registry.Devices[j].ID
		}
		return registry.Devices[i].Order < registry.Devices[j].Order
	})
}

func ValidateIngestionOwnership(ownership IngestionOwnership, now time.Time) error {
	active := ""
	if ownership.ActiveProtocol != nil {
		active = *ownership.ActiveProtocol
	}
	switch ownership.Mode {
	case "legacy":
		if active != "legacy_single_device" || ownership.CutoverNotAfter != nil {
			return errors.New("legacy requires active_protocol=legacy_single_device and null cutover")
		}
	case "device_v2":
		if active != "device_v2" || ownership.CutoverNotAfter != nil {
			return errors.New("device_v2 requires active_protocol=device_v2 and null cutover")
		}
	case "cutover":
		if active != "legacy_single_device" && active != "device_v2" {
			return errors.New("cutover requires one explicit active protocol")
		}
		if ownership.CutoverNotAfter == nil {
			return errors.New("cutover requires cutover_not_after")
		}
		expires, err := parseRFC3339UTC(*ownership.CutoverNotAfter)
		if err != nil {
			return errors.New("cutover_not_after must be RFC3339 UTC")
		}
		if !expires.After(now) {
			return errors.New("cutover window expired; explicit final owner is required")
		}
	default:
		return errors.New("mode must be legacy, device_v2, or cutover")
	}
	return nil
}

func OwnershipAllows(ownership IngestionOwnership, protocol string, now time.Time) bool {
	if err := ValidateIngestionOwnership(ownership, now); err != nil || ownership.ActiveProtocol == nil {
		return false
	}
	return *ownership.ActiveProtocol == protocol
}

func ValidateCredentialRecord(record *CredentialRecord) error {
	if record == nil {
		return contractError("credential", "is required")
	}
	if record.Version != 1 {
		return contractError("version", "must equal 1")
	}
	if !ValidateDeviceID(record.DeviceID) {
		return contractError("device_id", "is invalid")
	}
	if record.Algorithm != "sha256" {
		return contractError("algorithm", "must equal sha256")
	}
	if len(record.Credentials) < 1 || len(record.Credentials) > 2 {
		return contractError("credentials", "must contain 1..2 entries")
	}
	seen := map[string]bool{}
	for index, credential := range record.Credentials {
		prefix := fmt.Sprintf("credentials[%d]", index)
		if !credentialIDSet[credential.ID] {
			return contractError(prefix+".id", "must be current or next")
		}
		if seen[credential.ID] {
			return contractError(prefix+".id", "is duplicated")
		}
		seen[credential.ID] = true
		if !digestPattern.MatchString(credential.Digest) {
			return contractError(prefix+".digest", "must be 64 lowercase hexadecimal characters")
		}
		notBefore, err := parseRFC3339UTC(credential.NotBefore)
		if err != nil {
			return contractError(prefix+".not_before", "must be RFC3339 UTC")
		}
		notAfter, err := parseRFC3339UTC(credential.NotAfter)
		if err != nil {
			return contractError(prefix+".not_after", "must be RFC3339 UTC")
		}
		if !notAfter.After(notBefore) {
			return contractError(prefix, "not_after must be later than not_before")
		}
	}
	return nil
}

func ActiveCredentialIDs(record CredentialRecord, now time.Time) []string {
	active := make([]string, 0, len(record.Credentials))
	for _, credential := range record.Credentials {
		notBefore, beforeErr := parseRFC3339UTC(credential.NotBefore)
		notAfter, afterErr := parseRFC3339UTC(credential.NotAfter)
		if beforeErr == nil && afterErr == nil && !now.Before(notBefore) && now.Before(notAfter) {
			active = append(active, credential.ID)
		}
	}
	sort.Strings(active)
	return active
}

func ValidateLegacyMappings(mappings *LegacyMappingDocument, registry *DeviceRegistry, now time.Time) error {
	if mappings == nil || registry == nil {
		return contractError("legacy_mapping", "mapping and registry are required")
	}
	if mappings.Version != 1 {
		return contractError("version", "must equal 1")
	}
	devices := map[string]RegistryDevice{}
	for _, device := range registry.Devices {
		devices[device.ID] = device
	}
	usernames := map[string]bool{}
	deviceIDs := map[string]bool{}
	for index, mapping := range mappings.Mappings {
		prefix := fmt.Sprintf("mappings[%d]", index)
		if !validHumanText(mapping.Username, 128) || strings.TrimSpace(mapping.Username) != mapping.Username {
			return contractError(prefix+".username", "is invalid")
		}
		if usernames[mapping.Username] {
			return contractError(prefix+".username", "is duplicated")
		}
		if !ValidateDeviceID(mapping.DeviceID) {
			return contractError(prefix+".device_id", "is invalid")
		}
		if deviceIDs[mapping.DeviceID] {
			return contractError(prefix+".device_id", "is duplicated")
		}
		device, ok := devices[mapping.DeviceID]
		if !ok {
			return contractError(prefix+".device_id", "does not exist in registry")
		}
		if device.Enabled == nil || !*device.Enabled {
			return contractError(prefix+".device_id", "must identify an enabled device")
		}
		if !OwnershipAllows(device.Ingestion, "legacy_single_device", now) {
			return contractError(prefix+".device_id", "does not allow legacy ingestion")
		}
		usernames[mapping.Username] = true
		deviceIDs[mapping.DeviceID] = true
	}
	return nil
}

func ValidateDeviceUpdateEnvelope(envelope *DeviceUpdateEnvelope) error {
	if envelope == nil {
		return contractError("envelope", "is required")
	}
	if envelope.SchemaVersion != 2 {
		return contractError("schema_version", "must equal 2")
	}
	if !ValidateDeviceID(envelope.Device.ID) {
		return contractError("device.id", "is invalid")
	}
	if envelope.Device.ReportedName != nil {
		name := strings.TrimSpace(*envelope.Device.ReportedName)
		if name != *envelope.Device.ReportedName || !validHumanText(name, 128) {
			return contractError("device.reported_name", "is invalid")
		}
	}
	if envelope.Device.ReportedFQDN != nil {
		normalized, err := NormalizeFQDN(*envelope.Device.ReportedFQDN)
		if err != nil {
			return contractError("device.reported_fqdn", err.Error())
		}
		envelope.Device.ReportedFQDN = &normalized
	}
	if envelope.Device.Hostname != nil {
		hostname := strings.TrimSpace(*envelope.Device.Hostname)
		if hostname != *envelope.Device.Hostname || !validHumanText(hostname, 253) {
			return contractError("device.hostname", "is invalid")
		}
	}
	if _, err := parseRFC3339UTC(envelope.CollectedAt); err != nil {
		return contractError("collected_at", "must be RFC3339 UTC")
	}
	if len(envelope.Stats) == 0 {
		return contractError("stats", "must be a non-empty object")
	}
	for key := range envelope.Stats {
		if !statsKeys[key] {
			return contractError("stats."+key, "is not part of the retained flat update contract")
		}
	}
	return nil
}

func ValidateEnvelopeIdentity(headerDeviceID string, envelope DeviceUpdateEnvelope) error {
	if !ValidateDeviceID(headerDeviceID) || headerDeviceID != envelope.Device.ID {
		return contractError("device.id", "header and body identity must match")
	}
	return nil
}

func ValidateSuccessResponse(response SuccessResponse) error {
	if !response.Accepted {
		return contractError("accepted", "must be true")
	}
	if _, err := parseRFC3339UTC(response.ServerTime); err != nil {
		return contractError("server_time", "must be RFC3339 UTC")
	}
	if len(response.ConfigGeneration) < 1 || len(response.ConfigGeneration) > 128 ||
		!safeTextPattern.MatchString(response.ConfigGeneration) {
		return contractError("config_generation", "is invalid")
	}
	for index, monitor := range response.Monitors {
		if !validHumanText(monitor.Name, 128) || !validHumanText(monitor.Host, 253) ||
			monitor.Interval < 1 || monitor.Type == "" {
			return contractError(fmt.Sprintf("monitors[%d]", index), "is invalid")
		}
	}
	return nil
}

func ValidateErrorResponse(response ErrorResponse) error {
	if len(response.Error.Code) > 64 || !labelPattern.MatchString(response.Error.Code) {
		return contractError("error.code", "is invalid")
	}
	if len(response.Error.RequestID) > 128 || !safeTextPattern.MatchString(response.Error.RequestID) {
		return contractError("error.request_id", "is invalid")
	}
	return nil
}

func ValidateDeviceID(value string) bool {
	return deviceIDPattern.MatchString(value)
}

func NormalizeFQDN(value string) (string, error) {
	normalized := strings.ToLower(strings.TrimSpace(value))
	normalized = strings.TrimSuffix(normalized, ".")
	if normalized == "" || len(normalized) > MaxFQDNBytes ||
		strings.ContainsAny(normalized, `/*:@?#[]`) || net.ParseIP(normalized) != nil {
		return "", errors.New("must be a bounded DNS name, not a URL, wildcard, or IP literal")
	}
	parsed, err := url.Parse("https://" + normalized)
	if err != nil || parsed.Hostname() != normalized {
		return "", errors.New("must be a valid DNS name")
	}
	labels := strings.Split(normalized, ".")
	if len(labels) < 2 {
		return "", errors.New("must contain at least two DNS labels")
	}
	for _, label := range labels {
		if len(label) < 1 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return "", errors.New("contains an invalid DNS label")
		}
		for _, char := range label {
			if !(char >= 'a' && char <= 'z') && !(char >= '0' && char <= '9') && char != '-' {
				return "", errors.New("contains an invalid DNS character")
			}
		}
	}
	return normalized, nil
}

func parseRFC3339UTC(value string) (time.Time, error) {
	if !strings.HasSuffix(value, "Z") || len(value) > 40 {
		return time.Time{}, errors.New("timestamp is not UTC")
	}
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil || parsed.Location() != time.UTC {
		return time.Time{}, errors.New("timestamp is not RFC3339 UTC")
	}
	return parsed, nil
}

func validHumanText(value string, maxRunes int) bool {
	if value == "" || !utf8.ValidString(value) || utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, char := range value {
		if unicode.IsControl(char) {
			return false
		}
	}
	return true
}
