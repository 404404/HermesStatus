package contracts

import (
	"encoding/json"
	"fmt"
	"sort"
	"time"
)

var (
	identityStatusSet = map[string]bool{
		"matched": true, "fqdn_mismatch": true, "missing_fqdn": true,
		"unregistered": true, "disabled": true, "unknown": true,
	}
	deviceStatusSet = map[string]bool{
		"online": true, "degraded": true, "stale": true, "offline": true,
		"never_seen": true, "disabled": true, "identity_error": true,
	}
	protocolModeSet = map[string]bool{
		"legacy_single_device": true, "device_v2": true, "none": true,
	}
)

type DeviceObservation struct {
	IdentityStatus string
	Status         string
	ProtocolMode   string
	LastSeen       *string
	CollectedAt    *string
	Stale          bool
	LegacyFields   map[string]any
}

type StatsV2Server struct {
	DeviceID     string  `json:"device_id"`
	DisplayName  string  `json:"display_name"`
	Status       string  `json:"status"`
	Identity     string  `json:"identity_status"`
	ProtocolMode string  `json:"protocol_mode"`
	LastSeen     *string `json:"last_seen"`
	CollectedAt  *string `json:"collected_at"`
	Stale        bool    `json:"stale"`
	ExpectedFQDN *string `json:"expected_fqdn"`
	ReportedFQDN *string `json:"reported_fqdn"`
	legacyFields map[string]any
	order        int
}

func (server StatsV2Server) MarshalJSON() ([]byte, error) {
	value := make(map[string]any, len(server.legacyFields)+11)
	for key, item := range server.legacyFields {
		value[key] = item
	}
	value["device_id"] = server.DeviceID
	value["display_name"] = server.DisplayName
	value["status"] = server.Status
	value["identity_status"] = server.Identity
	value["protocol_mode"] = server.ProtocolMode
	value["last_seen"] = server.LastSeen
	value["collected_at"] = server.CollectedAt
	value["stale"] = server.Stale
	value["expected_fqdn"] = nil
	value["reported_fqdn"] = nil
	return json.Marshal(value)
}

type StatsV2Document struct {
	SchemaVersion   int             `json:"schema_version"`
	GeneratedAt     string          `json:"generated_at"`
	Updated         string          `json:"updated"`
	DefaultDeviceID string          `json:"default_device_id"`
	Servers         []StatsV2Server `json:"servers"`
	SSLCerts        []any           `json:"sslcerts"`
}

func ProjectStatsV2(
	registry DeviceRegistry,
	observations map[string]DeviceObservation,
	sslCerts []any,
	generatedAt time.Time,
) StatsV2Document {
	servers := make([]StatsV2Server, 0, len(registry.Devices))
	for _, device := range registry.Devices {
		observation, found := observations[device.ID]
		if !found {
			observation = DeviceObservation{
				IdentityStatus: "unknown",
				Status:         "never_seen",
				ProtocolMode:   "none",
				Stale:          true,
				LegacyFields:   map[string]any{},
			}
		}
		if device.Enabled != nil && !*device.Enabled {
			observation.Status = "disabled"
			observation.ProtocolMode = "none"
			observation.Stale = true
		}
		legacy := make(map[string]any, len(observation.LegacyFields)+1)
		for key, value := range observation.LegacyFields {
			legacy[key] = value
		}
		if _, exists := legacy["name"]; !exists {
			legacy["name"] = device.DisplayName
		}
		servers = append(servers, StatsV2Server{
			DeviceID:     device.ID,
			DisplayName:  device.DisplayName,
			Status:       observation.Status,
			Identity:     observation.IdentityStatus,
			ProtocolMode: observation.ProtocolMode,
			LastSeen:     observation.LastSeen,
			CollectedAt:  observation.CollectedAt,
			Stale:        observation.Stale,
			ExpectedFQDN: nil,
			ReportedFQDN: nil,
			legacyFields: legacy,
			order:        device.Order,
		})
	}
	sort.SliceStable(servers, func(i, j int) bool {
		if servers[i].order == servers[j].order {
			return servers[i].DeviceID < servers[j].DeviceID
		}
		return servers[i].order < servers[j].order
	})
	return StatsV2Document{
		SchemaVersion:   2,
		GeneratedAt:     generatedAt.UTC().Format(time.RFC3339),
		Updated:         fmt.Sprintf("%d", generatedAt.Unix()),
		DefaultDeviceID: registry.Defaults.DefaultDeviceID,
		Servers:         servers,
		SSLCerts:        sslCerts,
	}
}

// SerializeStatsV2 isolates a single bad legacy projection. The replacement
// item contains only safe contract fields and does not prevent other devices
// from being serialized.
func SerializeStatsV2(document StatsV2Document) ([]byte, error) {
	safeServers := make([]json.RawMessage, 0, len(document.Servers))
	for _, server := range document.Servers {
		encoded, err := json.Marshal(server)
		if err != nil {
			server.Status = "degraded"
			server.Stale = true
			server.legacyFields = map[string]any{"name": server.DisplayName}
			encoded, err = json.Marshal(server)
			if err != nil {
				return nil, err
			}
		}
		safeServers = append(safeServers, encoded)
	}
	projection := struct {
		SchemaVersion   int               `json:"schema_version"`
		GeneratedAt     string            `json:"generated_at"`
		Updated         string            `json:"updated"`
		DefaultDeviceID string            `json:"default_device_id"`
		Servers         []json.RawMessage `json:"servers"`
		SSLCerts        []any             `json:"sslcerts"`
	}{
		SchemaVersion:   document.SchemaVersion,
		GeneratedAt:     document.GeneratedAt,
		Updated:         document.Updated,
		DefaultDeviceID: document.DefaultDeviceID,
		Servers:         safeServers,
		SSLCerts:        document.SSLCerts,
	}
	return json.Marshal(projection)
}

func ValidateStatsV2(document StatsV2Document) error {
	if document.SchemaVersion != 2 {
		return contractError("schema_version", "must equal 2")
	}
	if _, err := parseRFC3339UTC(document.GeneratedAt); err != nil {
		return contractError("generated_at", "must be RFC3339 UTC")
	}
	if !ValidateDeviceID(document.DefaultDeviceID) {
		return contractError("default_device_id", "is invalid")
	}
	if len(document.Servers) < 1 || len(document.Servers) > MaxDevices {
		return contractError("servers", "must contain 1..16 entries")
	}
	seen := map[string]bool{}
	defaultFound := false
	for index, server := range document.Servers {
		prefix := fmt.Sprintf("servers[%d]", index)
		if !ValidateDeviceID(server.DeviceID) || seen[server.DeviceID] {
			return contractError(prefix+".device_id", "is invalid or duplicated")
		}
		seen[server.DeviceID] = true
		defaultFound = defaultFound || server.DeviceID == document.DefaultDeviceID
		if !validHumanText(server.DisplayName, MaxDisplayNameRunes) {
			return contractError(prefix+".display_name", "is invalid")
		}
		if !deviceStatusSet[server.Status] || !identityStatusSet[server.Identity] ||
			!protocolModeSet[server.ProtocolMode] {
			return contractError(prefix, "contains an invalid enum")
		}
		if server.LastSeen != nil {
			if _, err := parseRFC3339UTC(*server.LastSeen); err != nil {
				return contractError(prefix+".last_seen", "must be RFC3339 UTC or null")
			}
		}
		if server.CollectedAt != nil {
			if _, err := parseRFC3339UTC(*server.CollectedAt); err != nil {
				return contractError(prefix+".collected_at", "must be RFC3339 UTC or null")
			}
		}
		if server.ExpectedFQDN != nil || server.ReportedFQDN != nil {
			return contractError(prefix, "browser-facing FQDN fields must be null")
		}
		if index > 0 {
			previous := document.Servers[index-1]
			if previous.order > server.order ||
				(previous.order == server.order && previous.DeviceID >= server.DeviceID) {
				return contractError("servers", "is not sorted by order then device_id")
			}
		}
	}
	if !defaultFound {
		return contractError("default_device_id", "is not present in servers")
	}
	return nil
}

type GenerationState struct {
	DeviceID    string
	Generation  uint64
	Protocol    string
	PayloadMark string
}

func ApplyGeneration(
	current map[string]GenerationState,
	deviceID string,
	ownership IngestionOwnership,
	protocol string,
	generation uint64,
	payloadMark string,
	now time.Time,
) (map[string]GenerationState, error) {
	if !ValidateDeviceID(deviceID) {
		return nil, contractError("device_id", "is invalid")
	}
	if !OwnershipAllows(ownership, protocol, now) {
		return nil, contractError("protocol", "is not the active writer")
	}
	next := make(map[string]GenerationState, len(current)+1)
	for key, value := range current {
		next[key] = value
	}
	if previous, exists := next[deviceID]; exists && generation <= previous.Generation {
		return nil, contractError("generation", "must be newer than the accepted generation")
	}
	next[deviceID] = GenerationState{
		DeviceID: deviceID, Generation: generation, Protocol: protocol, PayloadMark: payloadMark,
	}
	return next, nil
}
